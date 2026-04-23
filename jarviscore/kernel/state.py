"""
KernelState — Runtime state for subagent OODA loop + checkpoint/resume.

This is the single source of truth during a subagent's execution.
The ContextManager reads from it to build prompts.
The OODA loop mutates it via add_tool_result() / add_thought().
It serializes via model_dump_json() for Redis checkpoint/resume.

Design decisions:
  - Pydantic BaseModel for serialisation (checkpoint to Redis)
  - ToolResult is a structured model, not a raw dict
  - Mutation methods are explicit (add_tool_result, add_thought)
  - internal_variables is a flexible dict for subagent-specific state
  - belief_state tracks constraints and hypotheses
"""

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Record of a single tool invocation within the OODA loop."""

    tool_name: str
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    tool_output: Any = None
    error: Optional[str] = None
    status: Literal["success", "failure", "blocked"] = "success"
    timestamp: float = Field(default_factory=time.time)

    @property
    def succeeded(self) -> bool:
        return self.status == "success" and self.error is None


class KernelState(BaseModel):
    """
    Serializable runtime state for the kernel's OODA loop.

    Persisted to Redis via save_checkpoint() for crash recovery.
    The kernel can resume from any checkpoint by loading the state
    and continuing the OODA loop from where it left off.

    The ContextManager reads this state each turn to build a
    priority-ordered prompt that fits the token budget.
    """

    workflow_id: str = ""
    step_id: str = ""
    agent_id: str = ""
    task: str = ""
    status: Literal["active", "waiting", "completed", "failed"] = "active"
    turn: int = 0
    phase: str = "discovery"

    system_prompt: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)

    # Structured tool execution history (OODA loop audit trail)
    tool_history: List[ToolResult] = Field(default_factory=list)

    # Working memory — thoughts, scratchpad notes
    thoughts: List[str] = Field(default_factory=list)
    scratchpad_notes: str = ""

    # Flexible key-value store for subagent-specific state
    # (e.g. research_findings, candidate_code, shared_context)
    internal_variables: Dict[str, Any] = Field(default_factory=dict)

    # Belief state — constraints discovered, hypotheses formed
    belief_state: Dict[str, Any] = Field(default_factory=dict)

    # Budget tracking (mirrors lease state for checkpoint)
    thinking_tokens_used: int = 0
    action_tokens_used: int = 0
    tokens_used: int = 0
    tokens_budget: int = 240_000
    total_cost_usd: float = 0.0

    # Error tracking
    last_error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    # Failure ledger snapshot (for cross-session persistence)
    failure_ledger: List[Dict[str, Any]] = Field(default_factory=list)

    # Timestamps
    started_at: float = Field(default_factory=time.time)
    last_checkpoint_at: Optional[float] = None

    # Final output
    output: Optional[Any] = None

    # ──────────────────────────────────────────────────────────────
    # Mutation Methods
    # ──────────────────────────────────────────────────────────────

    def add_tool_result(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
        error: Optional[str] = None,
    ) -> ToolResult:
        """Record a tool invocation result.

        Returns the ToolResult for inspection by the caller.
        """
        status: Literal["success", "failure", "blocked"] = "success"
        if error:
            status = "failure"
        elif isinstance(tool_output, dict):
            out_status = str(tool_output.get("status", "")).lower()
            if out_status in ("error", "failed", "blocked"):
                status = "failure"
                if not error:
                    error = tool_output.get("error")

        result = ToolResult(
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            error=str(error) if error else None,
            status=status,
        )
        self.tool_history.append(result)

        if error:
            self.last_error = str(error)[:500]
        return result

    def add_thought(self, thought: str) -> None:
        """Record an internal thought / meta-cognition note."""
        self.thoughts.append(thought)
        # Keep bounded — only the last 20 thoughts are useful for context
        if len(self.thoughts) > 20:
            self.thoughts = self.thoughts[-20:]

    def get_last_tool_result(self) -> Optional[ToolResult]:
        """Return the most recent tool result, or None."""
        return self.tool_history[-1] if self.tool_history else None

    def get_final_output(self) -> Any:
        """Extract the best output for the caller.

        Priority:
        1. Explicit self.output (set by subagent)
        2. Last successful tool output
        3. Last thought
        """
        if self.output is not None:
            return self.output
        # Walk backwards for last successful tool output
        for tr in reversed(self.tool_history):
            if tr.succeeded and tr.tool_output is not None:
                return tr.tool_output
        if self.thoughts:
            return self.thoughts[-1]
        return None
