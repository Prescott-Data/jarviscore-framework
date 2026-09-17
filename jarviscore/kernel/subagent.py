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
import ast
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
from jarviscore.kernel.gate import GateEvidence, as_evidence, record_attempt
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
_DONE_PATTERN = re.compile(r"^DONE:\s*(.+?)(?=\nRESULT:|\Z)", re.MULTILINE | re.DOTALL)
_RESULT_PATTERN = re.compile(r"^RESULT:\s*(.+)$", re.MULTILINE | re.DOTALL)
_COMBINED_DONE_RESULT_PATTERN = re.compile(
    r"^DONE/RESULT\s*:?\s*\n(.+)$", re.MULTILINE | re.DOTALL
)
_THOUGHT_PATTERN = re.compile(r"^THOUGHT:\s*(.+?)(?=\n(?:TOOL|DONE|RESULT|THOUGHT):|\Z)", re.MULTILINE | re.DOTALL)

# ── Observation channel integrity (issue #57) ─────────────────────────────
# How much of a tool result the agent sees inline per turn. Anything beyond
# the cap is clipped WITH an explicit marker and remains retrievable via the
# built-in read_turn_result tool for the lifetime of the dispatch.
_OBSERVATION_LIMIT = int(os.getenv("SUBAGENT_OBSERVATION_LIMIT", "800"))
# Full-result retention per turn (chars) and how many turns are kept.
_TURN_RESULT_RETENTION = int(os.getenv("SUBAGENT_TURN_RESULT_RETENTION", "16000"))
_TURN_RESULT_WINDOW = int(os.getenv("SUBAGENT_TURN_RESULT_WINDOW", "10"))


def _clip_observation(text: str, turn: int, limit: int = 0) -> str:
    """Clip a tool result for the observation channel — honestly.

    A model that KNOWS data is missing asks for the rest; a model that
    doesn't confabulates. Every clip therefore carries an explicit marker
    with the exact retrieval call for the remainder.
    """
    limit = limit or _OBSERVATION_LIMIT
    if len(text) <= limit:
        return text
    return (
        f"{text[:limit]}\n"
        f"…[showing {limit} of {len(text)} chars — call TOOL: read_turn_result "
        f'PARAMS: {{"turn": {turn}, "offset": {limit}}} for the rest]'
    )

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
        pass

    # Repair path: trailing commas before } or ] (valid python, invalid JSON).
    detrailed = re.sub(r",(\s*[}\]])", r"\1", repaired)
    if detrailed != repaired:
        try:
            return json.loads(detrailed)
        except (json.JSONDecodeError, ValueError):
            pass

    # Repair path: python-literal dicts (single quotes, True/False/None).
    # Normalization of common structured variants, never prose guessing.
    try:
        result = ast.literal_eval(candidate)
        if isinstance(result, dict):
            return result
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        pass
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

    #: How many times the same completion attempt may be rejected before the step
    #: ends. An attempt only counts as the same when the gate observed identical
    #: values, the agent submitted an identical result, and no tool ran in between
    #: — so an agent that is still working is never cut off, however long it takes.
    max_identical_done_attempts: int = 3

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

        # Live KernelState for the current dispatch — set at the top of run()
        # so built-in tools (read_turn_result) can reach the retention ring.
        self._current_state: Optional[KernelState] = None
        self._current_memory = None

        # Let subclass register its tools explicitly
        self.setup_tools()

        # Auto-discover any _tool_* methods not already registered by setup_tools()
        self._autodiscover_tools()

    def register_tool(
        self, name: str, func: Callable, description: str, phase: str = "action"
    ) -> None:
        """Register a tool available to this subagent."""
        self._tools[name] = ToolDefinition(name, func, description, phase)

    async def _tool_remember(self, fact: str, kind: str = "fact") -> Dict[str, Any]:
        """Keep something worth knowing in a later session (params: fact, optional kind).

        You are the memory lifecycle: nothing persists across sessions unless
        you decide it should. Record outcomes and durable facts, in the words a
        future you would want to read: what was done, what was found, what a
        person decided. Do not record diagnoses of failures or guesses about
        why something did not work; those expire with the bug.
        """
        memory = self._current_memory
        if memory is None or not hasattr(memory, "remember"):
            return {
                "status": "error",
                "error": "No cross-session memory is attached to this run, so nothing can be kept.",
                "semantic_error": "NO_MEMORY",
            }
        text = (fact or "").strip()
        if not text:
            return {"status": "error", "error": "Nothing to remember: fact was empty."}
        kept = await memory.remember(text, kind=kind, role=self.role)
        if not kept:
            return {
                "status": "error",
                "error": "The memory tier did not accept this; it was not kept.",
                "semantic_error": "NOT_KEPT",
            }
        return {"status": "success", "kept": text, "kind": kind}

    async def _tool_recall(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """Ask what earlier sessions recorded about something (params: query, optional limit).

        Results are the past, scored by relevance. They tell you what was true
        then, not what is true now.
        """
        memory = self._current_memory
        if memory is None or not hasattr(memory, "recall"):
            return {"status": "success", "results": [], "note": "No cross-session memory is attached to this run."}
        results = await memory.recall((query or "").strip(), limit=max(1, min(int(limit), 20)))
        return {"status": "success", "results": results, "count": len(results)}

    def _tool_read_turn_result(self, turn: int, offset: int = 0, length: int = 0) -> Dict[str, Any]:
        """Read the FULL output of a previous tool call when the inline view was clipped (params: turn, optional offset/length).

        The observation channel shows at most a fixed window of each tool
        result; the untruncated output of the last few turns is retained and
        readable here in chunks. This is the honest counterpart to the
        …[showing X of Y chars] marker.
        """
        state = self._current_state
        ring = (state.internal_variables.get("_turn_results") or {}) if state is not None else {}
        full = ring.get(str(turn))
        if full is None:
            available = sorted(ring, key=int) if ring else []
            return {
                "status": "error",
                "error": (
                    f"No retained result for turn {turn}. "
                    f"Retained turns: {available or 'none'} "
                    f"(the last {_TURN_RESULT_WINDOW} tool turns are kept)."
                ),
            }
        offset = max(0, int(offset))
        length = int(length) or _OBSERVATION_LIMIT * 4
        chunk = full[offset:offset + length]
        remaining = max(0, len(full) - (offset + len(chunk)))
        return {
            "status": "success",
            "turn": turn,
            "offset": offset,
            "total_chars": len(full),
            "remaining_chars": remaining,
            "output": chunk,
            **({"note": f'call again with {{"turn": {turn}, "offset": {offset + len(chunk)}}} for the rest'}
               if remaining else {}),
        }

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
        """Build the full system prompt including tool descriptions and protocol.

        The calling agent's identity leads: a sub-agent prompt is an execution
        harness, not a persona, and an application that trains its agent through
        ``system_prompt`` must not lose that the moment work enters the kernel.
        """
        state = getattr(self, "_current_state", None)
        identity = ((getattr(state, "context", None) or {}).get("system_prompt") or "").strip()
        parts = []
        if identity:
            parts += [
                identity,
                "",
                "═══ EXECUTION HARNESS (how you operate this turn) ═══",
                "",
            ]
        parts += [
            self.get_system_prompt(),
            "",
            self.get_tool_descriptions(),
            "",
            "Protocol:",
            "  To use a tool: THOUGHT: <reasoning>\\nTOOL: <name>\\nPARAMS: <json>",
            "  To finish:     THOUGHT: <reasoning>\\nDONE: <complete human answer>\\nRESULT: <json>",
            "  JSON alternative: {\"thought\": \"...\", \"tool\": \"...\", \"params\": {...}}",
            "  JSON finish:      {\"thought\": \"...\", \"done\": \"<summary>\", \"result\": {...}}",
            "",
            "Finishing:",
            "  DONE is read by the person who asked. Put the complete answer there,",
            "  including any lists or details they asked for. DONE may span lines.",
            "  RESULT carries the data behind that answer, shaped for whoever will",
            "  use it next: the list, the record, the figures. It is not a place",
            "  for status flags, booleans about your own process, or a diagnosis",
            "  of the runtime. If there is no data beyond the answer, RESULT may",
            "  repeat the answer as a string. When the answer needs more than one",
            "  line, put the complete prose in RESULT under an `answer` field; that",
            "  prose becomes the human-facing result while the other fields remain",
            "  available to downstream agents.",
        ]
        return "\n".join(parts)

    async def _landing_turn(
        self,
        state,
        system_prompt: str,
        conversation_history: list,
        model,
        total_tokens: dict,
        total_cost: float,
        exhausted: str,
    ):
        """One tools-disabled synthesis turn after lease expiry (issue #139).

        Gives the agent a chance to land the plane: produce a final answer from
        what it already gathered instead of yielding dead air. Returns an
        AgentOutput on a usable synthesis, None to fall through to the yield.
        """
        if not conversation_history:
            return None  # nothing gathered, nothing to synthesize
        try:
            messages = [{"role": "system", "content": system_prompt}]
            for hist_entry in conversation_history[-10:]:
                messages.append({"role": "assistant", "content": hist_entry["assistant"]})
                messages.append({"role": "user", "content": hist_entry["observation"]})
            messages.append({"role": "user", "content": (
                f"Your execution budget is exhausted ({exhausted}). Tools are no "
                "longer available. Produce your final answer NOW from what you "
                "have already gathered. Respond with exactly:\n"
                "DONE: <complete human answer; may span lines>\nRESULT: <json result>\n"
                "If your findings are partial, say so inside the result."
            )})
            kwargs = {"model": model} if model else {}
            llm_result = await self.llm_client.generate(messages=messages, **kwargs)
            content = llm_result.get("content", "")
            tokens = llm_result.get("tokens", {})
            total_tokens["input"] += tokens.get("input", 0)
            total_tokens["output"] += tokens.get("output", 0)
            total_tokens["total"] += tokens.get("total", 0)
            parsed = self._parse_response_for_contract(content, state.context)
            if parsed.get("type") != "done":
                return None
            state.status = "completed"
            state.output = parsed.get("result")
            await self._persist_memory(state)
            self._log.info("Landing turn produced a final result after lease expiry")
            return AgentOutput(
                status="success",
                summary=f"Completed on landing turn after budget exhaustion ({exhausted}): {parsed['summary']}",
                payload=state.get_final_output(),
                trajectory=[{"turn": state.turn, "type": "landing", "summary": parsed["summary"]}],
                metadata={"tokens": total_tokens, "cost_usd": total_cost,
                          "lease_exhausted": exhausted, "landing_turn": True,
                          "typed_outcome": "SUCCESS_ON_LANDING"},
            )
        except Exception as exc:
            self._log.warning("Landing turn failed: %s", exc)
            return None

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
        if "ask_peer" in self._tools:
            parts.append(
                "**PEER RESOLUTION:** Before concluding blocked, incomplete, or DONE "
                "with a material gap, ask whether an available peer can resolve it. "
                "Use `ask_capability` for the exact missing fact when you know the "
                "needed capability, or `ask_peer` when a specific role is already clear. "
                "Include known identifiers, then treat the response as new context and "
                "re-evaluate. Do not delegate work you can complete with your own tools."
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

        # ── Initialize or resume state ──
        state = KernelState(
            workflow_id=context.get("workflow_id", "unknown") if context else "unknown",
            step_id=context.get("step_id", "unknown") if context else "unknown",
            agent_id=self.agent_id,
            task=task,
            context=context or {},
            tokens_budget=self._cognition.lease.max_total_tokens,
        )

        if context and context.get("_resume") and memory is not None:
            raw_checkpoint = await memory.load_checkpoint()
            if raw_checkpoint:
                restored = KernelState.model_validate_json(raw_checkpoint)
                if restored.agent_id == self.agent_id and restored.task == task:
                    state = restored
                    state.status = "active"
                    state.context.update(context)
                    self._cognition.lease.thinking_used = state.thinking_tokens_used
                    self._cognition.lease.action_used = state.action_tokens_used
                    self._cognition.lease.turns_used = state.turn
                    self._restore_subagent_state(state)
                    if context.get("_new_execution_epoch"):
                        state.turn = 0
                        state.retry_count = 0
                        state.last_error = None
                        state.thinking_tokens_used = 0
                        state.action_tokens_used = 0
                        state.tokens_used = 0
                        state.total_cost_usd = 0.0
                        self._cognition.lease.thinking_used = 0
                        self._cognition.lease.action_used = 0
                        self._cognition.lease.turns_used = 0

        # Restore cross-task memory (no-op unless memory_enabled=True)
        await self._restore_memory(state)

        # Expose state to built-in tools (read_turn_result) for this dispatch.
        self._current_state = state
        # And the memory handle, so remember/recall reach the same tiers.
        self._current_memory = memory

        # Pre-run hook — subclasses can do deterministic pre-flight work
        await self._pre_run_hook(state)

        # ── TraceManager: use injected trace or no-op ──
        from jarviscore.kernel.tracing import create_noop_trace
        _trace = trace if trace is not None else create_noop_trace()
        total_tokens = {"input": 0, "output": 0, "total": state.tokens_used}
        total_cost = state.total_cost_usd
        system_prompt = self._build_system_prompt()

        # Rolling conversation history for multi-turn LLM continuity
        # (prevents amnesia — the LLM sees its own prior reasoning)
        conversation_history: List[Dict[str, str]] = []

        # Epistemic consistency enforcement — blocks redundant searches/URLs
        # before they execute (deterministic, unlike prompt-based nudges)
        _epistemic = EpistemicLedger()

        # Per-dispatch metadata channel (issue #88): tools stamp identity
        # facts here (e.g. the coder's registry function_id) and the success
        # envelope carries them out. Reset every run so nothing leaks across
        # dispatches.
        self._dispatch_metadata: Dict[str, Any] = {}

        for turn in range(state.turn, max_turns):
            state.turn = turn
            self._log.set_turn(turn)

            # ── Emergency guards ──
            if self._cognition.lease.is_expired():
                exhausted = ", ".join(self._cognition.lease.expired_dimensions()) or "unknown"
                self._log.warning(f"Lease expired: {exhausted}")
                # Landing turn (issue #139): one tools-disabled synthesis attempt
                # so exhaustion yields a partial result instead of dead air.
                landing = await self._landing_turn(
                    state, system_prompt, conversation_history, model,
                    total_tokens, total_cost, exhausted,
                )
                if landing is not None:
                    return landing
                return AgentOutput(
                    status="yield",
                    summary=f"Lease budget exhausted after {turn} turns: {exhausted}",
                    payload=state.get_final_output(),
                    trajectory=trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost,
                              "lease_exhausted": exhausted,
                              "typed_outcome": "YIELD_LEASE_EXHAUSTED"},
                )

            if not self._cognition.should_continue():
                reason = (
                    ", ".join(self._cognition.lease.expired_dimensions())
                    or ("completion already signalled" if self._cognition.done_called else "unknown")
                )
                return AgentOutput(
                    status="yield",
                    summary=f"Cognitive budget exhausted: {reason}",
                    payload=state.get_final_output(),
                    trajectory=trajectory,
                    metadata={"tokens": total_tokens, "cost_usd": total_cost,
                              "exhausted": reason,
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

            _trace.log_llm_request(system_prompt[:300], user_prompt[:500], model=model)

            kwargs = {}
            if model:
                kwargs["model"] = model

            _llm_t0 = __import__('time').monotonic()
            try:
                llm_result = await self.llm_client.generate(
                    messages=messages, **kwargs
                )
            except Exception as e:
                from jarviscore.orchestration.budget import WorkflowBudgetExceeded

                if isinstance(e, WorkflowBudgetExceeded):
                    state.status = "active"
                    state.last_error = str(e)
                    state.thinking_tokens_used = self._cognition.lease.thinking_used
                    state.action_tokens_used = self._cognition.lease.action_used
                    state.tokens_used = total_tokens["total"]
                    state.total_cost_usd = total_cost
                    if memory is not None:
                        await memory.save_checkpoint(state.model_dump_json())
                    _trace.log_step_complete(
                        False,
                        "Active execution epoch exhausted; checkpointed for continuation.",
                    )
                    return AgentOutput(
                        status="epoch_exhausted",
                        payload=state.output,
                        summary=(
                            "Active execution epoch exhausted; durable state was "
                            "checkpointed for continuation."
                        ),
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens,
                            "cost_usd": total_cost,
                            "typed_outcome": "CONTINUE_NEW_EXECUTION_EPOCH",
                            "checkpointed": memory is not None,
                        },
                    )
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
            _trace.log_llm_response(
                content[:500],
                round((__import__('time').monotonic() - _llm_t0) * 1000, 1),
                tokens=tokens.get("total", 0),
                model=llm_result.get("model") or model,
            )
            llm_tokens_this_turn = tokens.get("total", 0)
            state.tokens_used = total_tokens["total"]

            # Parse response
            parsed = self._parse_response_for_contract(content, context)

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
                    evidence = as_evidence(reject_reason)
                    attempts = state.internal_variables.setdefault("done_gate_attempts", [])
                    _, streak, previous = record_attempt(
                        attempts,
                        turn=turn,
                        evidence=evidence,
                        payload=parsed.get("result"),
                        tool_calls=len(state.tool_history),
                    )
                    self._log.info(
                        "Done rejected: check=%s attempt=%d", evidence.check, streak,
                    )
                    report = evidence.render()
                    if previous is not None and streak > 1:
                        report += (
                            f"\n  unchanged  since turn {previous.turn}: same check, same values, "
                            f"same result submitted, no tool call in between"
                        )

                    if streak >= self.max_identical_done_attempts:
                        # A boundary, not a verdict on the work. The agent has the
                        # facts and has stopped producing anything new, so another
                        # turn cannot change the outcome — and an unsatisfied gate
                        # is not a success to be granted on the way out.
                        summary = (
                            f"Completion gate '{evidence.check}' unsatisfied after "
                            f"{streak} identical attempts"
                        )
                        state.status = "failed"
                        state.add_thought(f"[DONE_GATE] {report}")
                        trajectory.append({
                            "turn": turn,
                            "type": "done_gate_unsatisfied",
                            "check": evidence.check,
                            "attempts": streak,
                        })
                        _trace.log_step_complete(False, summary)
                        return AgentOutput(
                            status="failure",
                            summary=summary,
                            payload=state.get_final_output(),
                            trajectory=trajectory,
                            metadata={
                                "tokens": total_tokens, "cost_usd": total_cost,
                                "typed_outcome": "FAIL_DONE_GATE_UNSATISFIED",
                                "gate_evidence": evidence.as_dict(),
                                "gate_attempts": streak,
                                "cognition": self._cognition.get_budget_summary(),
                            },
                        )

                    state.add_thought(f"[DONE_GATE] {report}")
                    conversation_history.append({
                        "assistant": content,
                        "observation": (
                            f"[Turn {turn}] {report}\n"
                            f"DONE was not recorded. It may be attempted again."
                        ),
                    })
                    # Charge tokens WITHOUT the "done" label: track_usage("done")
                    # sets done_called, which made should_continue() kill the agent
                    # next turn for a completion that was just rejected (issue #139).
                    self._cognition.track_usage("continue_after_done_gate", tokens=llm_tokens_this_turn)
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
                    metadata={
                        "tokens": total_tokens,
                        "cost_usd": total_cost,
                        **getattr(self, "_dispatch_metadata", {}),
                    },
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
                    hook_succeeded = (
                        isinstance(hook_result, dict)
                        and hook_result.get("status") == "success"
                    )
                    hook_event = (
                        "pre_execute_resolution" if hook_succeeded
                        else "pre_execute_block"
                    )
                    self._record_pre_execute_result(
                        state, trajectory, conversation_history, content,
                        turn, tool_name, tool_params, hook_result, hook_event,
                    )
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

                # ── Retain the full result for honest retrieval (issue #57) ──
                # The observation channel clips below; the bytes it clips stay
                # reachable via read_turn_result for the last N turns.
                if tool_name != "read_turn_result":
                    ring = state.internal_variables.setdefault("_turn_results", {})
                    ring[str(turn)] = str(tool_result)[:_TURN_RESULT_RETENTION]
                    for stale in sorted(ring, key=int)[:-_TURN_RESULT_WINDOW]:
                        del ring[stale]

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
                    params=tool_params,
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

                if isinstance(tool_result, dict) and tool_result.get("status") == "waiting":
                    state.status = "waiting"
                    state.turn = turn + 1
                    state.thinking_tokens_used = self._cognition.lease.thinking_used
                    state.action_tokens_used = self._cognition.lease.action_used
                    state.total_cost_usd = total_cost
                    self._save_subagent_state(state)
                    trajectory.append(turn_log)
                    if memory is not None:
                        await memory.save_checkpoint(state.model_dump_json())
                    return AgentOutput(
                        status="yield",
                        payload=tool_result,
                        summary=tool_result.get("detail", "Waiting for user action."),
                        trajectory=trajectory,
                        metadata={
                            "tokens": total_tokens,
                            "cost_usd": total_cost,
                            "yield_pending": True,
                            "typed_outcome": tool_result.get("typed_outcome"),
                            "hitl_type": tool_result.get("hitl_type"),
                            "system": tool_result.get("system"),
                            "connection_id": tool_result.get("connection_id"),
                            "workflow_id": state.workflow_id,
                            "step_id": state.step_id,
                            "action_id": tool_result.get("action_id"),
                            "action": tool_result.get("action"),
                            "consequence": tool_result.get("consequence"),
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
                        # Grant a fresh convergence window for the pivot turn.
                        self._cognition.convergence.reset_streaks(
                            reason=f"strategic pivot granted to {self.role}"
                        )
                        logger.info(
                            f"[{self.role}] Strategic pivot granted — "
                            f"resetting convergence for one more turn"
                        )
                        trajectory.append(turn_log)
                        # Record conversation for continuity through the pivot
                        observation = (
                            f"Tool '{tool_name}' returned: "
                            f"{_clip_observation(str(tool_result), turn)}"
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
                result_str = _clip_observation(str(tool_result), turn)
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

    def _save_subagent_state(self, state: KernelState) -> None:
        """Place subclass runtime state into the serializable checkpoint."""

    def _restore_subagent_state(self, state: KernelState) -> None:
        """Restore subclass runtime state from a checkpoint."""

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

        Returns ``(True, "")`` to allow completion, or ``(False, reason)`` to
        reject it. On rejection the loop continues and the agent sees the reason.

        ``reason`` should be a :class:`~jarviscore.kernel.gate.GateEvidence`:
        the check that did not hold, what it reads, and what was observed in the
        agent's own output. A gate that reports a verdict instead ("evidence is
        required") gives the agent nothing it can act on, so its next attempt is
        a reworded version of the last one — which is how a rejection turns into
        a loop. A bare string is still accepted and carried through unchanged.

        Do not advise here. Naming the missing fact is this method's whole job;
        deciding what to do about it is the agent's.

        The generic boundary requires one real peer-resolution attempt when a
        top-level result explicitly declares unresolved work and peer tools are
        available. Incoming peer responders are already the resolution attempt,
        so they may return their bounded finding without recursive delegation.
        """
        result = parsed.get("result")
        result_status = (
            str(result.get("status", "")).lower()
            if isinstance(result, dict)
            else ""
        )
        unresolved = result.get("unresolved") if isinstance(result, dict) else None
        materially_incomplete = (
            result_status in {"blocked", "incomplete", "partial"}
            or bool(unresolved)
        )
        peer_tools = {"ask_capability", "ask_peer"}
        available_peer_tools = peer_tools & set(getattr(self, "_tools", {}))
        peer_attempted = any(
            item.tool_name in peer_tools
            and (
                item.succeeded
                or (
                    isinstance(item.tool_output, dict)
                    and item.tool_output.get("peer_request_attempted") is True
                )
            )
            for item in state.tool_history
        )
        fulfilling_peer_request = bool(
            state.context.get("peer_requester_agent_id")
        )
        if (
            materially_incomplete
            and available_peer_tools
            and not peer_attempted
            and not fulfilling_peer_request
        ):
            return (
                False,
                GateEvidence(
                    check="peer_resolution_review",
                    requirement=(
                        "one actual attempt using an available peer capability "
                        "before accepting a blocked or incomplete result"
                    ),
                    observed={
                        "peer_tool_calls": 0,
                        "unresolved_facts": (
                            len(unresolved) if isinstance(unresolved, list) else 0
                        ),
                        "available_peer_tools": sorted(available_peer_tools),
                    },
                ),
            )
        return (True, "")

    # ──────────────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────────────

    def _record_pre_execute_result(
        self,
        state: KernelState,
        trajectory: list,
        conversation_history: list,
        content: str,
        turn: int,
        tool_name: str,
        tool_params: Dict[str, Any],
        hook_result: Dict[str, Any],
        hook_event: str,
    ) -> None:
        hook_succeeded = hook_result.get("status") == "success"
        disposition = "resolved" if hook_succeeded else "blocked"
        self._log.info(
            "Pre-execute hook %s '%s': %s",
            disposition,
            tool_name,
            str(hook_result)[:200],
        )
        state.add_tool_result(
            tool_name,
            tool_params,
            hook_result,
            error=hook_result.get("error"),
        )
        trajectory.append({
            "turn": turn,
            "type": hook_event,
            "tool": tool_name,
            "reason": hook_result.get(
                "reason",
                hook_result.get("error", "blocked by pre-execute hook"),
            ),
        })
        conversation_history.append({
            "assistant": content,
            "observation": (
                f"[Turn {turn}] Tool '{tool_name}' {disposition} by "
                f"pre-execute review: {str(hook_result)[:500]}"
            ),
        })

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

        combined_match = _COMBINED_DONE_RESULT_PATTERN.search(content)
        done_match = _DONE_PATTERN.search(content)
        result_match = _RESULT_PATTERN.search(content)
        tool_match = _TOOL_PATTERN.search(content)

        if combined_match and not tool_match:
            result = _extract_json_object(combined_match.group(1).strip())
            if result is not None:
                return {
                    "type": "done",
                    "thought": thought,
                    "summary": "Completed via DONE/RESULT block",
                    "result": result,
                }

        # RESULT alone (no DONE, no TOOL) only completes when it carries a
        # structured JSON object. "RESULT: pending" prose mid-thought must not
        # end the dispatch with a fabricated completion (issue #61).
        if result_match and not done_match and not tool_match:
            if _extract_json_object(result_match.group(1).strip()) is None:
                result_match = None

        # Directive precedence: models quote protocol keywords in their
        # reasoning constantly — the system prompt itself teaches the magic
        # strings. When one response carries BOTH an actionable TOOL and a
        # DONE/RESULT completion, the LAST directive wins (models emit their
        # decision at the end). A false completion destroys the dispatch;
        # a false tool call costs one turn (issue #61).
        if tool_match and (done_match or result_match):
            completion_pos = max(
                done_match.start() if done_match else -1,
                result_match.start() if result_match else -1,
            )
            logger.info(
                "Protocol ambiguity: TOOL@%d and DONE/RESULT@%d in one response — "
                "taking the later directive",
                tool_match.start(), completion_pos,
            )
            if tool_match.start() > completion_pos:
                done_match = None
                result_match = None

        # Check for DONE
        if done_match or result_match:
            summary = done_match.group(1).strip() if done_match else "Completed via RESULT block"
            result = None
            if result_match:
                try:
                    result = json.loads(result_match.group(1).strip())
                except (json.JSONDecodeError, ValueError):
                    result = result_match.group(1).strip()
            return {"type": "done", "thought": thought, "summary": summary, "result": result}

        # Check for TOOL (matched above, before precedence resolution)
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

    @classmethod
    def _parse_response_for_contract(
        cls, content: str, context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        parsed = cls._parse_response(content)
        contract = (context or {}).get("execution_contract")
        if (
            parsed.get("type") == "raw"
            and isinstance(contract, dict)
            and contract.get("execution_shape") == "single_artifact"
        ):
            artifact = _extract_json_object(content)
            if artifact is not None:
                return {
                    "type": "done",
                    "thought": "",
                    "summary": "Structured artifact completed.",
                    "result": artifact,
                }
        return parsed
