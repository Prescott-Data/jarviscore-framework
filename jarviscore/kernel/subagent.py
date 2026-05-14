"""
6C: BaseSubAgent — Abstract base for all kernel subagents.

Subagents are specialized execution units dispatched by the kernel.
Each has a set of tools, a system prompt, and uses a text-based
tool call protocol that works with any LLM provider.

Tool call protocol (LLM output):
    THOUGHT: <reasoning>
    TOOL: <tool_name>
    PARAMS: <json>

Completion protocol:
    THOUGHT: <reasoning>
    DONE: <summary>
    RESULT: <json>

OODA Loop Architecture:
    Each turn follows OBSERVE → ORIENT → DECIDE → ACT:
    1. OBSERVE  — ContextManager builds a priority-stack prompt from state
    2. ORIENT   — Cognition manager checks for interventions (stalls, budget)
    3. DECIDE   — LLM call produces a tool call or completion signal
    4. ACT      — Tool execution, failure recording, convergence evaluation

    The loop is governed by:
    - ExecutionLease budget (thinking + action tokens, wall clock, turn fuse)
    - ConvergenceGovernor (stagnation, same-tool streak, equivalent outcomes)
    - FailureLedger (fingerprint-based repeat-action blocking)
    - EpistemicLedger (search/URL dedup, knowledge plateau detection)

    Subclass hooks (all have safe defaults):
    - _pre_run_hook()       — one-time setup before the loop starts
    - _pre_execute_hook()   — gate tool calls (e.g. research phase gating)
    - _can_complete()       — gate DONE signals (e.g. evidence quality check)

    Exit paths:
    - parsed["type"] == "done"  — LLM signals completion (subject to _can_complete)
    - state.status == "completed" — tool-driven exit (e.g. publish_research_findings)
    - Lease/budget exhaustion   — emergency yield
    - Convergence stall         — post-pivot yield
    - Emergency turn fuse       — max_turns reached
"""

import inspect
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, cast

from jarviscore.context.truth import AgentOutput
from jarviscore.kernel.cognition import AgentCognitionManager, ConvergenceGovernor, FailureLedger
from jarviscore.kernel.epistemic import EpistemicLedger
from jarviscore.kernel.state import KernelState, ToolResult

logger = logging.getLogger(__name__)


class SubagentLogAdapter(logging.LoggerAdapter):
    """LoggerAdapter that automatically prepends [role][turn=N] to every log line.

    Subclasses should use ``self._log`` instead of ``logger`` directly so that
    all log lines carry the agent's role and current OODA turn without
    requiring manual f-string prefixes.

    Usage in subclasses::

        self._log.info("Starting pre-flight")
        # emits: [researcher][turn=0] Starting pre-flight
    """

    def __init__(self, base_logger: logging.Logger, role: str) -> None:
        super().__init__(base_logger, extra={"role": role, "turn": 0})

    def set_turn(self, turn: int) -> None:
        cast(Dict[str, Any], self.extra)["turn"] = turn

    def process(self, msg, kwargs):
        role = self.extra.get("role", "?")
        turn = self.extra.get("turn", 0)
        return f"[{role}][turn={turn}] {msg}", kwargs

# Regex patterns for parsing LLM tool call responses
_TOOL_PATTERN = re.compile(r"^TOOL:\s*(.+)$", re.MULTILINE)
_PARAMS_PATTERN = re.compile(r"^PARAMS:\s*(.+)$", re.MULTILINE | re.DOTALL)
_DONE_PATTERN = re.compile(r"^DONE:\s*(.*)$", re.MULTILINE)
_RESULT_PATTERN = re.compile(r"^RESULT:\s*(.+)$", re.MULTILINE | re.DOTALL)
_THOUGHT_PATTERN = re.compile(r"^THOUGHT:\s*(.+?)(?=\n(?:TOOL|DONE|RESULT|THOUGHT):|\Z)", re.MULTILINE | re.DOTALL)

def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first complete JSON object from *text* using brace-counting.

    Handles multi-line JSON (e.g. when a ``code`` param contains literal
    newlines) which would break the naive ``split("\\n")[0]`` approach.
    Returns the parsed dict, or None if no valid JSON object is found.

    String-aware: braces inside quoted strings are ignored so that code
    like ``{"code": "if x > 0: {print('yes')}"}`` parses correctly.

    If the initial ``json.loads`` fails (typically because the LLM emitted
    literal newlines/tabs inside JSON string values), the function repairs
    the JSON by escaping unescaped control characters within strings and
    retries the parse.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape_next = False
    end = start

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    else:
        # Never closed — incomplete JSON
        return None

    candidate = text[start:end]

    # Fast path: valid JSON as-is
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        pass

    # Repair path: escape raw newlines/tabs/carriage-returns inside strings.
    # LLMs frequently emit multi-line code values with literal newlines
    # instead of \\n escape sequences, producing invalid JSON.
    repaired = _repair_json_strings(candidate)
    try:
        return json.loads(repaired)
    except (json.JSONDecodeError, ValueError):
        return None


def _repair_json_strings(text: str) -> str:
    """Escape unescaped control characters (newlines, tabs) inside JSON string values.

    Walks the JSON text character-by-character, tracking whether we're inside
    a string literal. When a raw \\n, \\r, or \\t is found inside a string,
    it's replaced with the JSON escape sequence.
    """
    out: list[str] = []
    in_string = False
    escape_next = False

    for ch in text:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue

        if ch == "\\":
            out.append(ch)
            escape_next = True
            continue

        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue

        if in_string:
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue

        out.append(ch)

    return "".join(out)



class ToolDefinition:
    """A registered tool available to a subagent."""

    def __init__(self, name: str, func: Callable, description: str, phase: str = "action"):
        self.name = name
        self.func = func
        self.description = description
        self.phase = phase  # "thinking" or "action"


class BaseSubAgent(ABC):
    """
    Abstract base for all subagents dispatched by the kernel.

    Subclasses implement:
    - get_system_prompt(): Returns the system prompt for this subagent
    - setup_tools(): Registers tools via register_tool()

    The base class handles:
    - Tool registration and lookup
    - OODA loop execution with turn-by-turn reasoning
    - Context management with priority-stack prompt building
    - Convergence detection and failure memory
    - AgentOutput construction
    """

    def __init__(
        self,
        agent_id: str,
        role: str,
        llm_client,
        redis_store=None,
        blob_storage=None,
        search_client=None,
        code_registry=None,
        memory_enabled: bool = False,
    ):
        self.agent_id = agent_id
        self.role = role
        self.llm_client = llm_client
        self.redis_store = redis_store
        self.blob_storage = blob_storage
        self.search_client = search_client
        self.code_registry = code_registry
        self.memory_enabled = memory_enabled
        self._tools: Dict[str, ToolDefinition] = {}

        # Structured logger — use self._log instead of bare logger in subclasses
        self._log = SubagentLogAdapter(logger, role)

        # Cognition infrastructure — reset per run() call
        self._cognition: Optional[AgentCognitionManager] = None

        # Let subclass register its tools explicitly
        self.setup_tools()

        # Auto-discover any _tool_* methods not already registered by setup_tools()
        self._autodiscover_tools()

    def register_tool(
        self, name: str, func: Callable, description: str, phase: str = "action"
    ) -> None:
        """Register a tool available to this subagent."""
        self._tools[name] = ToolDefinition(name, func, description, phase)

    @property
    def tool_names(self) -> List[str]:
        """List of registered tool names."""
        return list(self._tools.keys())

    def get_tool_descriptions(self) -> str:
        """Format tool descriptions for prompt injection."""
        lines = ["Available tools:"]
        for tool in self._tools.values():
            lines.append(f"  - {tool.name}: {tool.description} [{tool.phase}]")
        return "\n".join(lines)

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this subagent."""
        ...

    @abstractmethod
    def setup_tools(self) -> None:
        """Register tools for this subagent. Called during __init__."""
        ...

    def _autodiscover_tools(self) -> None:
        """Auto-register any _tool_* methods not already registered by setup_tools().

        Walks the MRO of the concrete subclass and picks up methods whose names
        begin with ``_tool_`` that were not already registered via register_tool().
        This lets subclass authors use arbitrary decorators (``@property``,
        ``@cached_property``, custom wrappers) without losing tool discovery.

        Explicit register_tool() calls always take priority — auto-discovered
        tools only fill in the gaps.
        """
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if not name.startswith("_tool_"):
                continue
            tool_name = name[len("_tool_"):]
            if tool_name in self._tools:
                continue  # already registered explicitly
            doc = inspect.getdoc(method) or ""
            description = doc.splitlines()[0] if doc else "No description"
            self._tools[tool_name] = ToolDefinition(tool_name, method, description)

    # ──────────────────────────────────────────────────────────────────────
    # Cross-task persistent memory (opt-in via memory_enabled=True)
    # ──────────────────────────────────────────────────────────────────────

    _MEMORY_KEY_PREFIX = "subagent_memory"

    def _memory_key(self) -> str:
        return f"{self._MEMORY_KEY_PREFIX}:{self.agent_id}"

    async def _restore_memory(self, state: KernelState) -> None:
        """Load persisted internal_variables from Redis into state (if memory_enabled)."""
        if not self.memory_enabled or not self.redis_store:
            return
        try:
            raw = await self.redis_store.get(self._memory_key())
            if raw:
                data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
                state.internal_variables.update(data)
                self._log.info("Restored %d memory keys from previous run", len(data))
        except Exception as exc:
            self._log.warning("Memory restore failed: %s", exc)

    async def _persist_memory(self, state: KernelState) -> None:
        """Save state.internal_variables to Redis for the next run (if memory_enabled)."""
        if not self.memory_enabled or not self.redis_store:
            return
        try:
            await self.redis_store.set(
                self._memory_key(),
                json.dumps(state.internal_variables),
            )
            self._log.info("Persisted %d memory keys for next run", len(state.internal_variables))
        except Exception as exc:
            self._log.warning("Memory persist failed: %s", exc)

    # ──────────────────────────────────────────────────────────────────────
    # Prompt Building
    # ──────────────────────────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Build the full system prompt including tool descriptions and protocol."""
        parts = [
            self.get_system_prompt(),
            "",
            self.get_tool_descriptions(),
            "",
            "Protocol:",
            "  To use a tool: THOUGHT: <reasoning>\\nTOOL: <name>\\nPARAMS: <json>",
            "  To finish:     THOUGHT: <reasoning>\\nDONE: <summary>\\nRESULT: <json>",
            "  JSON alternative: {\"thought\": \"...\", \"tool\": \"...\", \"params\": {...}}",
            "  JSON finish:      {\"thought\": \"...\", \"done\": \"<summary>\", \"result\": {...}}",
        ]
        return "\n".join(parts)

    def _build_user_prompt(self, state: KernelState, context_block: str) -> str:
        """Build the user prompt for a single OODA turn.

        Combines the context block (from ContextManager) with the
        Epistemic Decision Contract — a structured self-assessment
        that forces the LLM to reason about gaps before acting.
        """
        parts = [context_block, "\n---"]
        parts.append(f"**ROLE: {self.role.upper()} AGENT** | Turn {state.turn}")

        # Epistemic Decision Contract — forces self-assessment
        parts.append(
            "**DECISION CONTRACT (follow this structure in your THOUGHT):**\n"
            "1. **KNOWN:** What have I established so far? (refer to WHAT I KNOW SO FAR above)\n"
            "2. **GAP:** What specific information am I still missing?\n"
            "3. **STRATEGY:** What is the most efficient next step to close the gap?\n"
            "4. **EXIT CHECK:** Do I have enough to produce a useful result? If yes, call DONE.\n\n"
            "Then emit your TOOL/PARAMS or DONE/RESULT."
        )
        return "\n\n".join(parts)

    # ──────────────────────────────────────────────────────────────────────
    # OODA Loop
    # ──────────────────────────────────────────────────────────────────────

    async def run(
        self,
        task: str,
        context: Optional[Dict] = None,
        max_turns: int = 15,
        model: Optional[str] = None,
        cognition: Optional[AgentCognitionManager] = None,
        context_manager=None,
        memory=None,
        trace=None,  # Optional[TraceManager] — injected by Kernel
    ) -> AgentOutput:
        """
        Execute the subagent's task via the OODA loop.

        Args:
            task: Natural language task description
            context: Optional context from kernel (prior steps, auth, etc.)
            max_turns: Emergency turn fuse (not the primary governor)
            model: Optional model override
            cognition: Optional pre-built AgentCognitionManager from the Kernel.
                If not provided a minimal one is created.
            context_manager: Optional ContextManager for priority-stack prompts.
                If not provided, falls back to simple prompt building.
            memory: Optional UnifiedMemory for turn logging and checkpoints.

        Returns:
            AgentOutput with status, payload, summary, trajectory
        """
        trajectory: List[Dict[str, Any]] = []

        # ── Initialize cognition (budget governance) ──
        if cognition is not None:
            self._cognition = cognition
        else:
            from jarviscore.kernel.lease import ExecutionLease
            self._cognition = AgentCognitionManager(
                lease=ExecutionLease(),
                agent_id=self.agent_id,
                workflow_id=context.get("workflow_id", "unknown") if context else "unknown",
                redis_store=self.redis_store,
            )

        # ── Initialize context manager ──
        if context_manager is None:
            from jarviscore.context.context_manager import ContextManager
            context_manager = ContextManager()

        # ── Initialize state ──
        state = KernelState(
            workflow_id=context.get("workflow_id", "unknown") if context else "unknown",
            step_id=context.get("step_id", "unknown") if context else "unknown",
            agent_id=self.agent_id,
            task=task,
            context=context or {},
            tokens_budget=self._cognition.lease.max_total_tokens,
        )

        # Restore cross-task memory (no-op unless memory_enabled=True)
        await self._restore_memory(state)

        # Pre-run hook — subclasses can do deterministic pre-flight work
        await self._pre_run_hook(state)

        # ── TraceManager: use injected trace or no-op ──
        from jarviscore.kernel.tracing import create_noop_trace
        _trace = trace if trace is not None else create_noop_trace()
        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0
        system_prompt = self._build_system_prompt()

        # Rolling conversation history for multi-turn LLM continuity
        # (prevents amnesia — the LLM sees its own prior reasoning)
        conversation_history: List[Dict[str, str]] = []

        # Epistemic consistency enforcement — blocks redundant searches/URLs
        # before they execute (deterministic, unlike prompt-based nudges)
        _epistemic = EpistemicLedger()

        for turn in range(max_turns):
            state.turn = turn
            self._log.set_turn(turn)

            # ── Emergency guards ──
            if self._cognition.lease.is_expired():
                self._log.warning("Lease expired")
                return AgentOutput(
                    status="yield",
                    summary=f"Lease budget exhausted after {turn} turns",
                    payload=state.get_final_output(),
                    trajectory=trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost,
                              "typed_outcome": "YIELD_LEASE_EXHAUSTED"},
                )

            if not self._cognition.should_continue():
                return AgentOutput(
                    status="yield",
                    summary="Cognitive budget exhausted",
                    payload=state.get_final_output(),
                    trajectory=trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost,
                              "typed_outcome": "YIELD_BUDGET_EXHAUSTED"},
                )

            self._cognition.lease.consume_turn()

            # ═══ 1. OBSERVE — Build context from state ═══
            context_block = context_manager.build_context(state)

            # ═══ 2. ORIENT — Meta-cognition check ═══
            intervention = self._cognition.get_intervention()
            if intervention:
                self._log.warning("Cognition intervention: %s", intervention[:120])
                state.add_thought(f"[META] {intervention}")

            # Inject failure memory into state for context building
            failure_block = self._cognition.failure_memory_block()
            if failure_block:
                state.failure_ledger = self._cognition.failures.recent_failures

            # ═══ 3. DECIDE — LLM call ═══
            user_prompt = self._build_user_prompt(state, context_block)
            messages = [{"role": "system", "content": system_prompt}]
            # Thread prior turns as assistant/user pairs (last 10 for continuity)
            for hist_entry in conversation_history[-10:]:
                messages.append({"role": "assistant", "content": hist_entry["assistant"]})
                messages.append({"role": "user", "content": hist_entry["observation"]})
            messages.append({"role": "user", "content": user_prompt})

            _trace.log_llm_request(system_prompt[:300], user_prompt[:500])

            kwargs = {}
            if model:
                kwargs["model"] = model

            _llm_t0 = __import__('time').monotonic()
            try:
                llm_result = await self.llm_client.generate(
                    messages=messages, **kwargs
                )
            except Exception as e:
                self._log.error("LLM call failed: %s", e)
                state.retry_count += 1
                if state.retry_count > state.max_retries:
                    _trace.log_step_complete(False, f"LLM call failed: {e}")
                    return AgentOutput(
                        status="failure",
                        summary=f"LLM call failed: {e}",
                        trajectory=trajectory,
                        metadata={"error": str(e), "tokens": total_tokens,
                                  "cost_usd": total_cost},
                    )
                continue

            content = llm_result.get("content", "")
            tokens = llm_result.get("tokens", {})
            total_tokens["input"] += tokens.get("input", 0)
            total_tokens["output"] += tokens.get("output", 0)
            total_tokens["total"] += tokens.get("total", 0)
            total_cost += llm_result.get("cost_usd", 0.0)
            _trace.log_llm_response(content[:500], round((__import__('time').monotonic() - _llm_t0) * 1000, 1))
            llm_tokens_this_turn = tokens.get("total", 0)
            state.tokens_used = total_tokens["total"]

            # Parse response
            parsed = self._parse_response(content)

            # ── Auto-summarize if context is getting large ──
            try:
                await context_manager.auto_summarize_if_needed(
                    state, self.llm_client, memory
                )
            except Exception as e:
                self._log.warning("Auto-summarization failed: %s", e)

            # ═══ Handle DONE ═══
            if parsed["type"] == "done":
                # ── Done-gate: subclasses can reject premature completion ──
                can_exit, reject_reason = self._can_complete(state, parsed)
                if not can_exit:
                    self._log.info("Done rejected: %s", reject_reason)
                    state.add_thought(
                        f"[DONE_GATE] Cannot complete yet: {reject_reason}. "
                        f"Continue working."
                    )
                    conversation_history.append({
                        "assistant": content,
                        "observation": (
                            f"[Turn {turn}] DONE rejected: {reject_reason}\n"
                            f"You must address this before calling DONE again."
                        ),
                    })
                    self._cognition.track_usage("done", tokens=llm_tokens_this_turn)
                    continue

                state.status = "completed"
                state.output = parsed.get("result")
                thought = parsed.get("thought", "")
                if thought:
                    _trace.log_thinking(thought)
                trajectory.append({
                    "turn": turn,
                    "type": "done",
                    "thought": thought,
                    "summary": parsed["summary"],
                })
                _trace.log_step_complete(True, parsed["summary"])
                self._cognition.track_usage("done", tokens=llm_tokens_this_turn)

                # Log turn to memory
                if memory:
                    try:
                        await memory.log_turn(
                            turn_id=str(turn), thought=parsed.get("thought", ""),
                            action="done", result=parsed["summary"],
                            tokens=llm_tokens_this_turn,
                        )
                    except Exception as exc:
                        self._log.warning(
                            "Memory turn log failed on DONE for %s turn=%s: %s",
                            self.agent_id,
                            turn,
                            exc,
                        )

                await self._persist_memory(state)
                return AgentOutput(
                    status="success",
                    payload=parsed.get("result"),
                    summary=parsed["summary"],
                    trajectory=trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost},
                )

            # ═══ 4. ACT — Tool execution ═══
            if parsed["type"] == "tool":
                tool_name = parsed["tool"]
                tool_params = parsed.get("params", {})

                # ── Repeat failure guard ──
                if self._cognition.is_repeat_failure(tool_name, tool_params):
                    self._log.warning("Blocked repeat failure: %s", tool_name)
                    state.add_thought(
                        f"[GUARD] Blocked repeat of failing action: {tool_name}. "
                        "Must try a different tool or different parameters."
                    )
                    state.add_tool_result(
                        tool_name, tool_params,
                        {"status": "blocked", "error": "REPEAT_BLOCKED"},
                        error="Identical failing action blocked by failure guard",
                    )
                    continue

                # ── Epistemic consistency check ──
                # Blocks redundant searches and URL re-reads BEFORE execution.
                # Unlike the convergence governor (which reacts after stalls),
                # this prevents the wasteful action from happening at all.
                _ep_verdict = _epistemic.validate_action(
                    tool_name, tool_params, turn, state
                )
                if _ep_verdict.action == "redirect":
                    self._log.info("Epistemic redirect: %s", _ep_verdict.reason)
                    state.add_thought(f"[EPISTEMIC] {_ep_verdict.injection}")
                    state.add_tool_result(
                        tool_name, tool_params,
                        {"status": "blocked", "reason": _ep_verdict.reason},
                        error=_ep_verdict.reason,
                    )
                    trajectory.append({
                        "turn": turn, "type": "epistemic_redirect",
                        "tool": tool_name, "reason": _ep_verdict.reason,
                    })
                    conversation_history.append({
                        "assistant": content,
                        "observation": (
                            f"[Turn {turn}] BLOCKED by epistemic ledger: "
                            f"{_ep_verdict.reason}\n{_ep_verdict.injection}"
                        ),
                    })
                    continue

                # ── Pre-execute hook: subclass-level gating ──
                # Subclasses override _pre_execute_hook to enforce constraints
                # (e.g. researcher phase gating). If it returns a dict, that
                # dict is used as the tool result and execution is skipped.
                hook_result = await self._pre_execute_hook(
                    tool_name, tool_params, state
                )
                if hook_result is not None:
                    self._log.info("Pre-execute hook blocked '%s': %s", tool_name, str(hook_result)[:200])
                    state.add_tool_result(
                        tool_name, tool_params, hook_result,
                        error=hook_result.get("error") if isinstance(hook_result, dict) else None,
                    )
                    trajectory.append({
                        "turn": turn, "type": "pre_execute_block",
                        "tool": tool_name,
                        "reason": hook_result.get("error", "blocked by pre-execute hook"),
                    })
                    conversation_history.append({
                        "assistant": content,
                        "observation": (
                            f"[Turn {turn}] Tool '{tool_name}' blocked by pre-execute hook: "
                            f"{str(hook_result)[:500]}"
                        ),
                    })
                    continue

                # Execute tool
                turn_log: Dict[str, Any] = {
                    "turn": turn,
                    "type": "tool_call",
                    "thought": parsed.get("thought", ""),
                    "tool": tool_name,
                    "params": tool_params,
                    "status": "pending",
                }

                # Emit thinking + tool_start trace events
                thought = parsed.get("thought", "")
                if thought:
                    _trace.log_thinking(thought)
                _trace.log_tool_start(tool_name, tool_params)

                tool_result = await self._execute_tool(tool_name, tool_params)
                turn_log["result"] = str(tool_result)[:500]

                # Record in state
                error_str = tool_result.get("error") if isinstance(tool_result, dict) else None
                state.add_tool_result(tool_name, tool_params, tool_result, error=error_str)

                # ── Record in epistemic ledger + check knowledge plateau ──
                _epistemic.record_outcome(
                    tool_name, tool_params, tool_result, turn, state
                )
                _plateau_signal = _epistemic.check_plateau(state, turn)
                if _plateau_signal:
                    state.add_thought(f"[EPISTEMIC] {_plateau_signal}")

                # ── Track usage + convergence ──
                self._cognition.track_usage(
                    tool_name, tokens=llm_tokens_this_turn, tool_output=tool_result,
                )

                # ── Record failure if tool errored ──
                if tool_result.get("status") == "error":
                    turn_log["status"] = "error"
                    turn_log["error"] = tool_result.get("error", "")
                    _trace.log_tool_result(tool_name, tool_result, error=tool_result.get("error"))
                    self._cognition.record_failure(
                        tool_name, tool_params, error=tool_result.get("error"),
                    )
                else:
                    turn_log["status"] = "success"
                    _trace.log_tool_result(tool_name, tool_result)

                if isinstance(tool_result, dict) and tool_result.get("_auto_complete"):
                    payload = tool_result.get("output", tool_result)
                    state.status = "completed"
                    state.output = payload
                    trajectory.append(turn_log)
                    summary = tool_result.get("message", f"Tool '{tool_name}' completed the task.")
                    _trace.log_step_complete(True, summary)
                    await self._persist_memory(state)
                    return AgentOutput(
                        status="success",
                        payload=payload,
                        summary=summary,
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens,
                            "cost_usd": total_cost,
                            "exit_type": "tool_auto_complete",
                        },
                    )

                # ── Check convergence stall (already evaluated inside track_usage) ──
                stall = self._cognition.check_stall_verdict()
                if stall:
                    if not state.internal_variables.get("_pivot_attempted"):
                        # Grant ONE pivot turn — inject strategic redirect
                        state.internal_variables["_pivot_attempted"] = True
                        state.add_thought(
                            "[STRATEGIC PIVOT] You are repeating the same approach "
                            "without making progress. You MUST try a completely "
                            "different strategy this turn. Consider: different tool, "
                            "different parameters, or call DONE with partial results."
                        )
                        # Reset governor streaks to allow one more turn
                        self._cognition.convergence._same_tool_streak = 0
                        self._cognition.convergence._equiv_streak = 0
                        self._cognition.convergence._last_verdict = None
                        logger.info(
                            f"[{self.role}] Strategic pivot granted — "
                            f"resetting convergence for one more turn"
                        )
                        trajectory.append(turn_log)
                        # Record conversation for continuity through the pivot
                        observation = (
                            f"Tool '{tool_name}' returned: "
                            f"{str(tool_result)[:800]}"
                        )
                        conversation_history.append({
                            "assistant": content,
                            "observation": observation,
                        })
                        continue
                    else:
                        # Pivot was already attempted — escalate now
                        stall_reason = stall.get("reason", "Convergence stall")
                        self._log.warning("Convergence stall (post-pivot): %s", stall_reason)
                        state.add_thought(f"[CONVERGENCE] {stall_reason}")
                        trajectory.append(turn_log)
                        _trace.log_step_complete(False, stall_reason)
                        return AgentOutput(
                            status=stall.get("action", "yield"),
                            summary=stall_reason,
                            payload=state.get_final_output(),
                            trajectory=trajectory,
                            metadata={
                                "tokens": total_tokens, "cost_usd": total_cost,
                                "typed_outcome": stall.get("typed_outcome"),
                                "cognition": self._cognition.get_budget_summary(),
                            },
                        )

                trajectory.append(turn_log)

                # Record conversation history for multi-turn LLM continuity
                # Structured turn digest instead of raw output — helps the LLM
                # retain what was learned and reason about strategy changes.
                result_str = str(tool_result)[:800]
                observation = (
                    f"[Turn {turn}] Tool '{tool_name}' returned ({turn_log['status']}):\n"
                    f"{result_str}\n\n"
                    f"Reflect: What new information does this provide? "
                    f"Does it change your strategy?"
                )
                conversation_history.append({
                    "assistant": content,
                    "observation": observation,
                })

                # Log turn to memory
                if memory:
                    try:
                        await memory.log_turn(
                            turn_id=str(turn), thought=parsed.get("thought", ""),
                            action=tool_name,
                            result=str(tool_result)[:1000],
                            tokens=llm_tokens_this_turn,
                        )
                    except Exception as exc:
                        self._log.warning(
                            "Memory turn log failed for %s turn=%s tool=%s: %s",
                            self.agent_id,
                            turn,
                            tool_name,
                            exc,
                        )

                # Save checkpoint
                if memory:
                    try:
                        await memory.save_checkpoint(state.model_dump_json())
                    except Exception as e:
                        self._log.warning("Checkpoint save failed for %s turn=%s: %s", self.agent_id, turn, e)

                # ── State-driven exit ──
                # Tools like publish_research_findings set state.status = "completed"
                # to signal they've produced a final result. This check makes that
                # a first-class exit path — no separate DONE emission needed.
                if getattr(state, "status", None) == "completed":
                    summary = (
                        f"Completed via tool '{tool_name}' "
                        f"(state-driven exit on turn {turn})"
                    )
                    _trace.log_step_complete(True, summary)
                    await self._persist_memory(state)
                    return AgentOutput(
                        status="success",
                        payload=tool_result,
                        summary=summary,
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens, "cost_usd": total_cost,
                            "exit_type": "state_driven",
                        },
                    )

                continue

            # ── Unparseable response — protocol failure, not completion ──
            # Keep this inside the OODA loop so the agent sees the failure and
            # can repair its protocol on the next turn. If it cannot repair
            # before the turn fuse, return an explicit failure.
            raw_turn = {
                "turn": turn,
                "type": "raw",
                "content": content[:500],
                "status": "protocol_violation",
            }
            trajectory.append(raw_turn)
            protocol_violations = int(
                state.internal_variables.get("_protocol_violation_count", 0)
            ) + 1
            state.internal_variables["_protocol_violation_count"] = protocol_violations
            max_protocol_repairs = int(os.getenv("SUBAGENT_MAX_PROTOCOL_REPAIRS", "1"))
            self._cognition.track_usage(
                "protocol_violation",
                tokens=llm_tokens_this_turn,
                tool_output={"status": "error", "error": "Protocol violation"},
            )
            self._cognition.record_failure(
                "protocol_violation",
                {"raw": content[:500]},
                error="Subagent response did not match TOOL or DONE protocol.",
            )
            if protocol_violations <= max_protocol_repairs and turn < max_turns - 1:
                conversation_history.append({
                    "assistant": content,
                    "observation": (
                        f"[Turn {turn}] PROTOCOL VIOLATION: Your response did not match "
                        "the required TOOL/PARAMS or DONE/RESULT protocol.\n"
                        "Repair on the next turn. Emit exactly one of:\n"
                        "THOUGHT: <reasoning>\\nTOOL: <tool_name>\\nPARAMS: <json>\n"
                        "or\n"
                        "THOUGHT: <reasoning>\\nDONE: <summary>\\nRESULT: <json>."
                    ),
                })
                state.add_thought(
                    "[PROTOCOL_VIOLATION] Previous response did not match the required "
                    "TOOL/PARAMS or DONE/RESULT protocol. Repair on the next turn."
                )
                continue
            return AgentOutput(
                status="failure",
                payload={
                    "error": (
                        "Subagent response did not match TOOL or DONE protocol "
                        f"after {protocol_violations} violation(s)."
                    ),
                    "raw": content[:1000],
                },
                summary=(
                    "Subagent response repeatedly violated the required TOOL/DONE protocol."
                    if protocol_violations > 1
                    else "Subagent response violated the required TOOL/DONE protocol."
                ),
                trajectory=trajectory,
                metadata={
                    "tokens": total_tokens,
                    "cost_usd": total_cost,
                    "typed_outcome": "PROTOCOL_VIOLATION",
                    "protocol_violations": protocol_violations,
                },
            )

        # Max turns reached (emergency fuse)
        _trace.log_step_complete(False, f"Emergency turn fuse reached ({max_turns} turns)")
        return AgentOutput(
            status="yield",
            summary=f"Emergency turn fuse reached ({max_turns} turns)",
            payload=state.get_final_output(),
            trajectory=trajectory,
            metadata={
                "tokens": total_tokens, "cost_usd": total_cost,
                "typed_outcome": "YIELD_EMERGENCY_TURN_FUSE",
            },
        )

    # ──────────────────────────────────────────────────────────────────────
    # Subclass Hooks (overridable)
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_run_hook(self, state: KernelState) -> None:
        """Deterministic pre-flight operations before the OODA loop starts.

        Override in subclasses for pre-run setup (e.g. API discovery,
        registry warm-up, context seeding). Default is a no-op.
        """
        pass

    async def teardown(self) -> None:
        """Release resources owned by this subagent instance."""
        pass

    async def _pre_execute_hook(
        self,
        tool_name: str,
        params: Dict[str, Any],
        state: KernelState,
    ) -> Optional[Dict[str, Any]]:
        """Called before tool execution — subclass gate point.

        If this returns a dict, that dict is used as the tool result and
        the actual tool is NOT executed. This enables subclass-specific
        enforcement (e.g. research phase gating, tool allowlists).

        If this returns None, the tool executes normally.

        Default: always allow (returns None).
        """
        return None

    def _can_complete(
        self,
        state: KernelState,
        parsed: Dict[str, Any],
    ) -> tuple:
        """Called before accepting a DONE signal — subclass gate point.

        Returns (True, "") to allow completion, or (False, reason) to
        reject it. On rejection the loop continues — the LLM sees the
        reason and must address it before calling DONE again.

        Default: always allow.
        """
        return (True, "")

    # ──────────────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────────────

    async def _execute_tool(self, tool_name: str, params: Dict) -> Dict[str, Any]:
        """Execute a registered tool."""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "error": f"Unknown tool: {tool_name}", "available": self.tool_names}

        # Guard: if params are the {"raw": ...} fallback from _parse_response
        # (line 592), don't unpack them as kwargs — the tool won't accept a
        # 'raw' argument and will crash with "unexpected keyword argument".
        if "raw" in params and len(params) == 1:
            import inspect
            try:
                sig = inspect.signature(tool.func)
                expected = [p for p in sig.parameters if p != "self"]
            except (ValueError, TypeError):
                expected = ["(could not inspect)"]
            self._log.warning(
                "Tool '%s' received malformed params (JSON parse failed). Expected: %s",
                tool_name, expected,
            )
            return {
                "status": "error",
                "error": (
                    f"Could not parse your PARAMS as valid JSON. "
                    f"Tool '{tool_name}' expects these parameters: {expected}. "
                    f"Please re-emit TOOL/PARAMS with a valid JSON object."
                ),
                "semantic_error": "MALFORMED_PARAMS",
                "expected_params": expected,
            }

        try:
            result = tool.func(**params)
            # Handle coroutines
            if hasattr(result, "__await__"):
                result = await result
            # Normalize to dict
            if not isinstance(result, dict):
                return {"status": "success", "output": result}
            # Ensure status field exists
            if "status" not in result:
                result["status"] = "success"
            return result
        except Exception as e:
            self._log.warning("Tool '%s' failed: %s", tool_name, e)
            return {"status": "error", "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Response Parsing
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(content: str) -> Dict[str, Any]:
        """
        Parse LLM response for tool calls or completion.

        Supports two protocols:
        1. Text-based (THOUGHT/TOOL/PARAMS or THOUGHT/DONE/RESULT)
        2. JSON fallback ({"thought": ..., "tool": ..., "parameters": ...})

        Returns dict with:
            type: "tool" | "done" | "raw"
            + type-specific fields
        """
        thought_match = _THOUGHT_PATTERN.search(content)
        thought = thought_match.group(1).strip() if thought_match else ""

        # Check for DONE first
        done_match = _DONE_PATTERN.search(content)
        result_match = _RESULT_PATTERN.search(content)
        if done_match or result_match:
            summary = done_match.group(1).strip() if done_match else "Completed via RESULT block"
            result = None
            if result_match:
                try:
                    result = json.loads(result_match.group(1).strip())
                except (json.JSONDecodeError, ValueError):
                    result = result_match.group(1).strip()
            return {"type": "done", "thought": thought, "summary": summary, "result": result}

        # Check for TOOL
        tool_match = _TOOL_PATTERN.search(content)
        if tool_match:
            tool_name = tool_match.group(1).strip()
            params = {}
            params_match = _PARAMS_PATTERN.search(content)
            if params_match:
                params_str = params_match.group(1).strip()
                # Try parsing the full JSON object using brace-counting.
                # The LLM often emits multi-line JSON (e.g. write_code with
                # code containing literal newlines), so split("\n")[0] would
                # truncate the JSON and cause a parse failure.
                params = _extract_json_object(params_str)
                if params is None:
                    # Fallback: try first line (works for simple single-line params)
                    try:
                        params = json.loads(params_str.split("\n")[0])
                    except (json.JSONDecodeError, ValueError):
                        params = {"raw": params_str}
            return {"type": "tool", "thought": thought, "tool": tool_name, "params": params}

        # ── JSON protocol fallback ──
        # Some models emit the protocol as a single structured object. Accept
        # only explicit protocol fields; arbitrary JSON remains unparseable.
        obj = _extract_json_object(content)
        if obj is not None:
            json_thought = obj.get("thought", thought)
            if isinstance(obj.get("tool"), str) and obj["tool"].strip():
                return {
                    "type": "tool",
                    "thought": json_thought,
                    "tool": obj["tool"].strip(),
                    "params": obj.get("parameters", obj.get("params", {})),
                }

            done_summary = obj.get("done")
            if done_summary is None and "summary" in obj and "result" in obj:
                done_summary = obj.get("summary")
            if done_summary is not None:
                return {
                    "type": "done",
                    "thought": json_thought,
                    "summary": str(done_summary),
                    "result": obj.get("result"),
                }

        # Unparseable
        return {"type": "raw", "content": content}
