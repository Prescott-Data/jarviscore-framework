"""
6B: AgentCognitionManager — budget tracking, phase classification and failure records.

Tracks tool usage against the lease budget and classifies each tool as
thinking or action. FailureLedger fingerprints failing (tool, params) pairs
and records them, so a later attempt can be told that the identical call
failed before and how. What to do with that is the agent's decision.
"""

import hashlib
import json
import logging
import time
from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional

from .lease import ExecutionLease

logger = logging.getLogger(__name__)


class AgentPhase(str, Enum):
    """Cognitive phase of the agent within a single dispatch."""
    DISCOVERY = "discovery"
    ANALYSIS = "analysis"
    IMPLEMENTATION = "implementation"
    COMPLETION = "completion"


# Tool classification sets
THINKING_TOOLS = frozenset({
    "web_search",
    "extract_page",
    "analyze",
    "get_context",
    "inspect_error",
    "scan_peers",
    "list_peers",
    "inspect_workflow",
    "read_workflow_step",
    "read_mailbox",
    # Re-reading a retained tool result is recall, not action (issue #57).
    "read_turn_result",
})

ACTION_TOOLS = frozenset({
    "generate_code",
    "validate_code",
    "fix_code",
    "execute_code",
    "send_message",
    "send_mailbox",
    "ask_peer",
    "broadcast_update",
    "broadcast",
    "done",
})


# ─────────────────────────────────────────────────────────────────────────────
# FailureLedger
# ─────────────────────────────────────────────────────────────────────────────

class FailureLedger:
    """
    Fingerprints and records failing (tool, params) pairs.

    Each failure is fingerprinted as SHA-256(tool_name + canonical_params_json)
    and classified. If a redis_store is attached, the failure is also indexed
    there. Nothing is blocked: an identical call that failed before may succeed
    now, and whether to try it again is the agent's decision.
    """

    _MAX_LEDGER_ENTRIES = 50

    def __init__(
        self,
        agent_id: str = "unknown",
        workflow_id: str = "unknown",
        redis_store=None,
    ) -> None:
        self.agent_id = agent_id
        self.workflow_id = workflow_id
        self.redis_store = redis_store
        self._ledger: List[Dict[str, Any]] = []

    @staticmethod
    def fingerprint(tool_name: str, params: Dict[str, Any]) -> str:
        """SHA-256 of canonical (tool_name, params) pair."""
        try:
            payload = json.dumps(params or {}, sort_keys=True, default=str, separators=(",", ":"))
        except Exception:
            payload = str(params or {})
        return hashlib.sha256(f"{tool_name}:{payload}".encode("utf-8")).hexdigest()

    @staticmethod
    def _declared_error_type(output: Any = None) -> str:
        """The failure class the tool declared, or UNKNOWN; never guessed from prose or codes."""
        if isinstance(output, dict):
            explicit = output.get("error_type")
            if isinstance(explicit, str) and explicit.strip():
                return explicit.strip().upper()
        return "UNKNOWN"

    @staticmethod
    def _status_code(output: Any = None) -> Optional[int]:
        if isinstance(output, dict):
            for key in ("status_code", "code"):
                try:
                    return int(output.get(key))
                except (TypeError, ValueError):
                    continue
        return None

    def record(
        self,
        tool_name: str,
        params: Dict[str, Any],
        error: Optional[str] = None,
        output: Any = None,
    ) -> str:
        """
        Record a failure and return the fingerprint.

        The fingerprint is returned so callers can log it.
        The ledger is capped at _MAX_LEDGER_ENTRIES (oldest dropped).
        If redis_store is attached, the failure is also indexed there.
        """
        fp = self.fingerprint(tool_name, params)
        error_type = self._declared_error_type(output)
        entry: Dict[str, Any] = {
            "ts": time.time(),
            "tool": tool_name,
            "fingerprint": fp,
            "error_type": error_type,
            "status_code": self._status_code(output),
            "error": str(error or output or ""),
        }
        self._ledger.append(entry)
        # Keep bounded
        if len(self._ledger) > self._MAX_LEDGER_ENTRIES:
            self._ledger = self._ledger[-self._MAX_LEDGER_ENTRIES:]

        # Cross-session persistence via Redis (optional)
        if self.redis_store and hasattr(self.redis_store, "index_failure_event"):
            try:
                self.redis_store.index_failure_event(
                    tenant_id="global",
                    workflow_id=str(self.workflow_id),
                    agent_role=str(self.agent_id),
                    tool=str(tool_name),
                    fingerprint=str(fp),
                    error_type=str(error_type),
                    error_message=str(entry["error"]),
                    metadata={},
                )
            except Exception as exc:
                logger.debug(f"[FailureLedger] Redis index_failure_event failed: {exc}")

        return fp

    @property
    def recent_failures(self) -> List[Dict[str, Any]]:
        """Last N ledger entries (read-only copy)."""
        return list(self._ledger[-20:])


# ─────────────────────────────────────────────────────────────────────────────
# AgentCognitionManager
# ─────────────────────────────────────────────────────────────────────────────

class AgentCognitionManager:
    """
    Tracks the cognitive budget and records tool use and failures.

    Usage:
        cognition = AgentCognitionManager(lease)
        cognition.track_usage("web_search", tokens=500)
        if not cognition.should_continue():
            # Budget exhausted — stop
    """

    def __init__(
        self,
        lease: ExecutionLease,
        agent_id: str = "unknown",
        workflow_id: str = "unknown",
        redis_store=None,
    ):
        self.lease = lease
        self._tool_history: List[str] = []
        self._recent_tools: deque = deque(maxlen=6)  # diagnostic window
        self._has_acted: bool = False
        self._phase: AgentPhase = AgentPhase.DISCOVERY
        self._done_called: bool = False
        self._thinking_only_streak: int = 0

        self.failures = FailureLedger(
            agent_id=agent_id,
            workflow_id=workflow_id,
            redis_store=redis_store,
        )

    def classify_tool(self, tool_name: str, declared_phase: Any = None) -> str:
        """
        Classify a tool as 'thinking' or 'action'.

        A phase declared when the tool was registered wins: discovery and
        analysis tools gather information, so they draw on the thinking budget.
        Undeclared tools fall back to the name sets; unknown names default to
        'action' (conservative — charges action budget).
        """
        declared = getattr(declared_phase, "value", declared_phase)
        if declared in {"thinking", AgentPhase.DISCOVERY.value, AgentPhase.ANALYSIS.value}:
            return "thinking"
        if declared in {"action", AgentPhase.IMPLEMENTATION.value, AgentPhase.COMPLETION.value}:
            return "action"
        if tool_name in THINKING_TOOLS:
            return "thinking"
        return "action"

    def track_usage(
        self,
        tool_name: str,
        tokens: int = 0,
        tool_output: Any = None,
        params: Optional[Dict[str, Any]] = None,
        declared_phase: Any = None,
    ) -> None:
        """
        Record a tool invocation and charge tokens to the appropriate budget.

        Args:
            tool_name: Name of the tool invoked
            tokens: Tokens consumed by this invocation
            tool_output: Result from the tool (kept for API compatibility)
            params: Tool parameters (kept for API compatibility)
            declared_phase: The phase the subagent registered the tool with.
        """
        phase = self.classify_tool(tool_name, declared_phase)
        if tokens > 0:
            self.lease.consume(tokens, phase)

        self._tool_history.append(tool_name)
        self._recent_tools.append(tool_name)

        if phase == "action" and tool_name != "done":
            self._has_acted = True
            self._thinking_only_streak = 0
        elif phase == "thinking":
            self._thinking_only_streak += 1
        else:
            self._thinking_only_streak = 0

        if tool_name == "done":
            self._done_called = True

        # Update phase
        self._update_phase(tool_name)

    def _update_phase(self, tool_name: str) -> None:
        """Update cognitive phase based on budget consumption and tool usage."""
        if self._done_called:
            self._phase = AgentPhase.COMPLETION
            return

        if self._has_acted:
            self._phase = AgentPhase.IMPLEMENTATION
            return

        thinking_pct = (
            self.lease.thinking_used / self.lease.thinking_budget
            if self.lease.thinking_budget > 0
            else 0.0
        )

        if thinking_pct >= 0.6:
            self._phase = AgentPhase.IMPLEMENTATION
        elif thinking_pct >= 0.3:
            self._phase = AgentPhase.ANALYSIS
        else:
            self._phase = AgentPhase.DISCOVERY

    @property
    def phase(self) -> AgentPhase:
        """Current cognitive phase."""
        return self._phase

    def should_continue(self) -> bool:
        """Return True if the agent should keep running (budget remains, not done)."""
        if self._done_called:
            return False
        return not self.lease.is_expired()

    @property
    def done_called(self) -> bool:
        """True once the agent has signalled completion."""
        return self._done_called

    def budget_facts(self) -> str:
        """What remains of this run's budget, stated as facts for the agent."""
        lease = self.lease
        facts = [f"{lease.remaining_total()} of {lease.max_total_tokens} tokens"]
        if getattr(lease, "wall_clock_ms", 0) > 0:
            facts.append(
                f"{int(lease.remaining_wall_clock_ms() / 1000)}s of "
                f"{int(lease.wall_clock_ms / 1000)}s wall clock"
            )
        fuse = getattr(lease, "emergency_turn_fuse", 0)
        if fuse:
            facts.append(f"{max(0, fuse - lease.turns_used)} of {fuse} turns")
        return "Remaining: " + ", ".join(facts) + "."

    def budget_running_low(self, below: float = 0.25) -> bool:
        """Whether any part of this run's budget is down to its last quarter."""
        lease = self.lease
        left = []
        if getattr(lease, "max_total_tokens", 0) > 0:
            left.append(lease.remaining_total() / lease.max_total_tokens)
        if getattr(lease, "wall_clock_ms", 0) > 0:
            left.append(lease.remaining_wall_clock_ms() / lease.wall_clock_ms)
        fuse = getattr(lease, "emergency_turn_fuse", 0)
        if fuse:
            left.append(max(0, fuse - lease.turns_used) / fuse)
        return any(fraction <= below for fraction in left)

    # ── Failure Ledger convenience pass-throughs ──────────────────────────────

    def record_failure(
        self,
        tool_name: str,
        params: Dict[str, Any],
        error: Optional[str] = None,
        output: Any = None,
    ) -> str:
        """Record a tool failure. Returns the fingerprint."""
        return self.failures.record(tool_name, params, error=error, output=output)

    def get_budget_summary(self) -> Dict[str, Any]:
        """Return a summary for traces and result metadata."""
        return {
            "phase": self._phase.value,
            "has_acted": self._has_acted,
            "tool_count": len(self._tool_history),
            "done_called": self._done_called,
            "thinking_only_streak": self._thinking_only_streak,
            "failure_count": len(self.failures.recent_failures),
            "lease": self.lease.summary(),
        }

    @property
    def tool_history(self) -> List[str]:
        """List of all tools invoked (in order)."""
        return list(self._tool_history)

    @property
    def has_acted(self) -> bool:
        """Whether any action tool (excluding done) has been called."""
        return self._has_acted
