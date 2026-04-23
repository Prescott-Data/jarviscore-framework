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
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

from jarviscore.context.truth import AgentOutput
from jarviscore.kernel.cognition import AgentCognitionManager, ConvergenceGovernor, FailureLedger
from jarviscore.kernel.state import KernelState, ToolResult

logger = logging.getLogger(__name__)

# Regex patterns for parsing LLM tool call responses
_TOOL_PATTERN = re.compile(r"^TOOL:\s*(.+)$", re.MULTILINE)
_PARAMS_PATTERN = re.compile(r"^PARAMS:\s*(.+)$", re.MULTILINE | re.DOTALL)
_DONE_PATTERN = re.compile(r"^DONE:\s*(.+)$", re.MULTILINE)
_RESULT_PATTERN = re.compile(r"^RESULT:\s*(.+)$", re.MULTILINE | re.DOTALL)
_THOUGHT_PATTERN = re.compile(r"^THOUGHT:\s*(.+?)(?=\n(?:TOOL|DONE|RESULT|THOUGHT):|\Z)", re.MULTILINE | re.DOTALL)

# JSON protocol fallback (for models that prefer JSON output)
_JSON_BLOCK_PATTERN = re.compile(r"\{[^{}]*\"tool\"\s*:", re.DOTALL)


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
    ):
        self.agent_id = agent_id
        self.role = role
        self.llm_client = llm_client
        self.redis_store = redis_store
        self.blob_storage = blob_storage
        self._tools: Dict[str, ToolDefinition] = {}

        # Cognition infrastructure — reset per run() call
        self._cognition: Optional[AgentCognitionManager] = None

        # Let subclass register its tools
        self.setup_tools()

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

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle hooks — override in subclasses for setup/teardown
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_run_hook(self, state) -> None:
        """Called before the OODA loop starts. Override for resource setup (e.g. browser)."""
        pass

    async def _post_run_hook(self) -> None:
        """Called after the OODA loop exits (even on exception). Override for cleanup."""
        pass

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
        ]
        return "\n".join(parts)

    def _build_user_prompt(self, state: KernelState, context_block: str) -> str:
        """Build the user prompt for a single OODA turn.

        Combines the context block (from ContextManager) with the
        decision contract.
        """
        return (
            f"{context_block}\n\n"
            f"---\n"
            f"**ROLE: {self.role.upper()} AGENT**\n\n"
            f"**DECISION:**\n"
            f"Decide the next action to complete your mission.\n"
            f"Use the text protocol above (THOUGHT/TOOL/PARAMS or THOUGHT/DONE/RESULT)."
        )

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

        # Pre-run hook — subclasses can do deterministic pre-flight work
        await self._pre_run_hook(state)

        total_tokens = {"input": 0, "output": 0, "total": 0}
        total_cost = 0.0
        system_prompt = self._build_system_prompt()

        for turn in range(max_turns):
            state.turn = turn

            # ── Emergency guards ──
            if self._cognition.lease.is_expired():
                logger.warning(f"[{self.role}] Lease expired on turn {turn}")
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
                logger.warning(f"[{self.role}] Cognition intervention: {intervention[:120]}")
                state.add_thought(f"[META] {intervention}")

            # Inject failure memory into state for context building
            failure_block = self._cognition.failure_memory_block()
            if failure_block:
                state.failure_ledger = self._cognition.failures.recent_failures

            # ═══ 3. DECIDE — LLM call ═══
            user_prompt = self._build_user_prompt(state, context_block)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            kwargs = {}
            if model:
                kwargs["model"] = model

            try:
                llm_result = await self.llm_client.generate(
                    messages=messages, **kwargs
                )
            except Exception as e:
                logger.error(f"[{self.role}] LLM call failed on turn {turn}: {e}")
                state.retry_count += 1
                if state.retry_count > state.max_retries:
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
                logger.warning(f"[{self.role}] Auto-summarization failed: {e}")

            # ═══ Handle DONE ═══
            if parsed["type"] == "done":
                state.status = "completed"
                state.output = parsed.get("result")
                trajectory.append({
                    "turn": turn,
                    "type": "done",
                    "thought": parsed.get("thought", ""),
                    "summary": parsed["summary"],
                })
                self._cognition.track_usage("done", tokens=llm_tokens_this_turn)

                # Log turn to memory
                if memory:
                    try:
                        await memory.log_turn(
                            turn_id=str(turn), thought=parsed.get("thought", ""),
                            action="done", result=parsed["summary"],
                            tokens=llm_tokens_this_turn,
                        )
                    except Exception:
                        pass

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
                    logger.warning(
                        f"[{self.role}] Blocked repeat failure: {tool_name}"
                    )
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

                # Execute tool
                turn_log: Dict[str, Any] = {
                    "turn": turn,
                    "type": "tool_call",
                    "thought": parsed.get("thought", ""),
                    "tool": tool_name,
                    "params": tool_params,
                    "status": "pending",
                }

                tool_result = await self._execute_tool(tool_name, tool_params)
                turn_log["result"] = str(tool_result)[:500]

                # Record in state
                error_str = tool_result.get("error") if isinstance(tool_result, dict) else None
                state.add_tool_result(tool_name, tool_params, tool_result, error=error_str)

                # ── Track usage + convergence ──
                self._cognition.track_usage(
                    tool_name, tokens=llm_tokens_this_turn, tool_output=tool_result,
                )

                # ── Record failure if tool errored ──
                if tool_result.get("status") == "error":
                    turn_log["status"] = "error"
                    turn_log["error"] = tool_result.get("error", "")
                    self._cognition.record_failure(
                        tool_name, tool_params, error=tool_result.get("error"),
                    )
                else:
                    turn_log["status"] = "success"

                # ── Check convergence stall ──
                stall = self._cognition.convergence.evaluate(tool_name, tool_result)
                if stall:
                    stall_reason = stall.get("reason", "Convergence stall")
                    logger.warning(f"[{self.role}] Convergence stall: {stall_reason}")
                    state.add_thought(f"[CONVERGENCE] {stall_reason}")
                    trajectory.append(turn_log)
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

                # Log turn to memory
                if memory:
                    try:
                        await memory.log_turn(
                            turn_id=str(turn), thought=parsed.get("thought", ""),
                            action=tool_name,
                            result=str(tool_result)[:1000],
                            tokens=llm_tokens_this_turn,
                        )
                    except Exception:
                        pass

                # Save checkpoint
                if memory:
                    try:
                        await memory.save_checkpoint(state.model_dump_json())
                    except Exception as e:
                        logger.debug(f"Checkpoint save failed: {e}")

                continue

            # ── Unparseable response — treat as done with raw content ──
            trajectory.append({
                "turn": turn,
                "type": "raw",
                "content": content[:500],
            })
            return AgentOutput(
                status="success",
                payload=content,
                summary=content[:200],
                trajectory=trajectory,
                metadata={"tokens": total_tokens, "cost_usd": total_cost},
            )

        # Max turns reached (emergency fuse)
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
    # Pre-run Hook (overridable by subclasses)
    # ──────────────────────────────────────────────────────────────────────

    async def _pre_run_hook(self, state: KernelState) -> None:
        """Deterministic pre-flight operations before the OODA loop starts.

        Override in subclasses for pre-run setup (e.g. API discovery,
        registry warm-up, context seeding). Default is a no-op.
        """
        pass

    # ──────────────────────────────────────────────────────────────────────
    # Tool Execution
    # ──────────────────────────────────────────────────────────────────────

    async def _execute_tool(self, tool_name: str, params: Dict) -> Dict[str, Any]:
        """Execute a registered tool."""
        tool = self._tools.get(tool_name)
        if not tool:
            return {"status": "error", "error": f"Unknown tool: {tool_name}", "available": self.tool_names}

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
            logger.warning(f"[{self.role}] Tool '{tool_name}' failed: {e}")
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
        if done_match:
            summary = done_match.group(1).strip()
            result = None
            result_match = _RESULT_PATTERN.search(content)
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
                # Extract just the first JSON object/line
                try:
                    params = json.loads(params_str.split("\n")[0])
                except (json.JSONDecodeError, ValueError):
                    params = {"raw": params_str}
            return {"type": "tool", "thought": thought, "tool": tool_name, "params": params}

        # ── JSON protocol fallback ──
        # Some models prefer to return JSON instead of the text protocol
        json_match = _JSON_BLOCK_PATTERN.search(content)
        if json_match:
            try:
                # Find the full JSON object
                start = json_match.start()
                # Simple brace-counting parser
                depth = 0
                end = start
                for i in range(start, len(content)):
                    if content[i] == '{':
                        depth += 1
                    elif content[i] == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                json_str = content[start:end]
                obj = json.loads(json_str)
                if "tool" in obj:
                    return {
                        "type": "tool",
                        "thought": obj.get("thought", thought),
                        "tool": obj["tool"],
                        "params": obj.get("parameters", obj.get("params", {})),
                    }
            except (json.JSONDecodeError, ValueError):
                pass

        # Unparseable
        return {"type": "raw", "content": content}
