"""
6B: AgentCognitionManager — Budget tracking, phase detection, and safety guards.

Tracks tool usage against the lease budget, detects cognitive phases,
catches spinning (same tool 3+ times in a row), and enforces a cognitive
gate (can't call done() without having taken any action).
"""

from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional

from .lease import ExecutionLease


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
    "read_mailbox",
})

ACTION_TOOLS = frozenset({
    "generate_code",
    "validate_code",
    "fix_code",
    "execute_code",
    "send_message",
    "send_mailbox",
    "broadcast",
    "done",
})

# Spinning detection: N consecutive identical tool calls
_SPIN_THRESHOLD = 3


class AgentCognitionManager:
    """
    Tracks cognitive budget, phase transitions, and safety guards.

    Usage:
        cognition = AgentCognitionManager(lease)
        cognition.track_usage("web_search", tokens=500)
        if cognition.detect_spinning("web_search"):
            # Inject warning into prompt
        if not cognition.should_continue():
            # Budget exhausted — stop
    """

    def __init__(self, lease: ExecutionLease):
        self.lease = lease
        self._tool_history: List[str] = []
        self._recent_tools: deque = deque(maxlen=_SPIN_THRESHOLD)
        self._has_acted: bool = False
        self._phase: AgentPhase = AgentPhase.DISCOVERY
        self._done_called: bool = False

    def classify_tool(self, tool_name: str) -> str:
        """
        Classify a tool as 'thinking' or 'action'.

        Unknown tools default to 'action' (conservative — charges action budget).
        """
        if tool_name in THINKING_TOOLS:
            return "thinking"
        return "action"

    def track_usage(self, tool_name: str, tokens: int = 0) -> None:
        """
        Record a tool invocation and charge tokens to the appropriate budget.

        Args:
            tool_name: Name of the tool invoked
            tokens: Tokens consumed by this invocation
        """
        phase = self.classify_tool(tool_name)
        if tokens > 0:
            self.lease.consume(tokens, phase)

        self._tool_history.append(tool_name)
        self._recent_tools.append(tool_name)

        if phase == "action" and tool_name != "done":
            self._has_acted = True

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

    def detect_spinning(self, tool_name: str) -> bool:
        """
        Detect if the same tool has been called N+ times consecutively.

        Call this AFTER track_usage() to check the latest state.
        """
        if len(self._recent_tools) < _SPIN_THRESHOLD:
            return False
        return all(t == tool_name for t in self._recent_tools)

    def detect_premature_done(self, has_acted: bool = None) -> bool:
        """
        Detect if done() is being called too early.

        Returns True if:
        - Still in DISCOVERY phase (haven't done enough research)
        - No action tools have been called (nothing was actually done)
        """
        acted = has_acted if has_acted is not None else self._has_acted
        if self._phase == AgentPhase.DISCOVERY:
            return True
        if not acted:
            return True
        return False

    def get_intervention(self) -> Optional[str]:
        """
        Return a warning message if the agent needs course correction.

        Returns None if everything is fine.
        """
        # Check spinning
        if len(self._recent_tools) >= _SPIN_THRESHOLD:
            last_tool = self._recent_tools[-1]
            if all(t == last_tool for t in self._recent_tools):
                return (
                    f"WARNING: You have called '{last_tool}' {_SPIN_THRESHOLD} times "
                    f"in a row. This suggests you may be stuck. Try a different approach "
                    f"or call 'done' if you have a result."
                )

        # Check budget warnings
        total_remaining = self.lease.remaining_total()
        total_budget = self.lease.max_total_tokens
        if total_budget > 0 and total_remaining / total_budget < 0.1:
            return (
                f"WARNING: Only {total_remaining} tokens remaining "
                f"({total_remaining / total_budget:.0%} of budget). "
                f"Wrap up and call 'done' soon."
            )

        return None

    def get_budget_summary(self) -> Dict[str, Any]:
        """Return a summary for prompt injection."""
        return {
            "phase": self._phase.value,
            "has_acted": self._has_acted,
            "tool_count": len(self._tool_history),
            "done_called": self._done_called,
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
