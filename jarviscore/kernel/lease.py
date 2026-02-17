"""
6A: ExecutionLease — Token/turn/time budgets for subagent execution.

Each subagent dispatch gets a lease that tracks:
- Thinking budget (research, analysis, context gathering)
- Action budget (code generation, execution, messaging)
- Wall clock time limit
- Emergency turn fuse (hard stop on runaway loops)

Role-based profiles configure different budgets per subagent type.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Literal


# Role-specific lease profiles
ROLE_LEASE_PROFILES: Dict[str, Dict[str, Any]] = {
    "coder": {
        "thinking_budget": 132_000,
        "action_budget": 108_000,
        "max_total_tokens": 240_000,
        "wall_clock_ms": 240_000,
        "emergency_turn_fuse": 24,
        "model_tier": "coding",
    },
    "researcher": {
        "thinking_budget": 180_000,
        "action_budget": 60_000,
        "max_total_tokens": 240_000,
        "wall_clock_ms": 240_000,
        "emergency_turn_fuse": 28,
        "model_tier": "task",
    },
    "communicator": {
        "thinking_budget": 72_000,
        "action_budget": 48_000,
        "max_total_tokens": 120_000,
        "wall_clock_ms": 120_000,
        "emergency_turn_fuse": 14,
        "model_tier": "task",
    },
}


@dataclass
class ExecutionLease:
    """
    Token/turn/time budget for a single subagent dispatch.

    Budget is split into thinking (research/analysis) and action
    (code gen/execution/messaging) phases. The lease tracks consumption
    and provides expiration checks.

    Usage:
        lease = ExecutionLease.for_role("coder")
        lease.consume(1500, "thinking")
        if lease.is_expired():
            # Budget exhausted — stop execution
    """

    max_total_tokens: int = 80_000
    thinking_budget: int = 56_000
    action_budget: int = 24_000
    wall_clock_ms: int = 180_000
    emergency_turn_fuse: int = 30
    model_tier: str = "task"

    # Mutable tracking
    thinking_used: int = 0
    action_used: int = 0
    turns_used: int = 0
    start_time: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        """Check if any budget dimension is exhausted."""
        if self.thinking_used + self.action_used >= self.max_total_tokens:
            return True
        if self.thinking_used >= self.thinking_budget:
            return True
        if self.action_used >= self.action_budget:
            return True
        if self.turns_used >= self.emergency_turn_fuse:
            return True
        if self.elapsed_ms() >= self.wall_clock_ms:
            return True
        return False

    def remaining_thinking(self) -> int:
        """Remaining thinking tokens."""
        return max(0, self.thinking_budget - self.thinking_used)

    def remaining_action(self) -> int:
        """Remaining action tokens."""
        return max(0, self.action_budget - self.action_used)

    def remaining_total(self) -> int:
        """Remaining total tokens across both budgets."""
        used = self.thinking_used + self.action_used
        return max(0, self.max_total_tokens - used)

    def elapsed_ms(self) -> float:
        """Milliseconds elapsed since lease started."""
        return (time.time() - self.start_time) * 1000

    def remaining_wall_clock_ms(self) -> float:
        """Remaining wall clock time in milliseconds."""
        return max(0, self.wall_clock_ms - self.elapsed_ms())

    def consume(self, tokens: int, phase: str) -> None:
        """
        Consume tokens from the specified budget phase.

        Args:
            tokens: Number of tokens consumed
            phase: "thinking" or "action"

        Raises:
            ValueError: If phase is not "thinking" or "action"
        """
        if phase == "thinking":
            self.thinking_used += tokens
        elif phase == "action":
            self.action_used += tokens
        else:
            raise ValueError(f"Unknown phase: {phase!r}. Must be 'thinking' or 'action'.")

    def consume_turn(self) -> None:
        """Increment the turn counter."""
        self.turns_used += 1

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict of current lease state."""
        return {
            "thinking": {
                "used": self.thinking_used,
                "budget": self.thinking_budget,
                "remaining": self.remaining_thinking(),
            },
            "action": {
                "used": self.action_used,
                "budget": self.action_budget,
                "remaining": self.remaining_action(),
            },
            "total": {
                "used": self.thinking_used + self.action_used,
                "budget": self.max_total_tokens,
                "remaining": self.remaining_total(),
            },
            "turns": {
                "used": self.turns_used,
                "fuse": self.emergency_turn_fuse,
            },
            "wall_clock": {
                "elapsed_ms": round(self.elapsed_ms(), 1),
                "budget_ms": self.wall_clock_ms,
                "remaining_ms": round(self.remaining_wall_clock_ms(), 1),
            },
            "model_tier": self.model_tier,
            "expired": self.is_expired(),
        }

    @classmethod
    def for_role(cls, role: str) -> "ExecutionLease":
        """
        Create a lease from a role profile.

        Args:
            role: One of "coder", "researcher", "communicator"

        Returns:
            ExecutionLease configured for the role

        Raises:
            KeyError: If role not found in ROLE_LEASE_PROFILES
        """
        if role not in ROLE_LEASE_PROFILES:
            raise KeyError(
                f"Unknown role: {role!r}. "
                f"Available: {list(ROLE_LEASE_PROFILES.keys())}"
            )
        return cls(**ROLE_LEASE_PROFILES[role])
