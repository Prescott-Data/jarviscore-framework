"""Elastic worker pools: more instances of one agent while its work queues up.

A pooled agent is one logical agent. Every member shares the agent's id, so a step
one member started and checkpointed can be resumed by any other, and the step-claim
lease stays the only thing that decides who runs a step. Members are separate
instances because an agent's kernel, subagent cache and sandbox serve one step at
a time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, List

from jarviscore.execution.governor import BULK, INTERACTIVE


@dataclass(frozen=True)
class Pool:
    """How far one agent may scale out.

    min: members kept warm, including the agent registered with ``mesh.add``.
    max: most members running steps at once in this process.
    idle_seconds: an idle member above ``min`` is retired after this long.
    lane: ``"bulk"`` lets the LLM governor hold capacity back for interactive work.
    """

    min: int = 1
    max: int = 8
    idle_seconds: float = 60.0
    lane: str = INTERACTIVE

    def __post_init__(self) -> None:
        if self.min < 1:
            raise ValueError("Pool.min must be at least 1: the registered agent is a member")
        if self.max < self.min:
            raise ValueError("Pool.max must be at least Pool.min")
        if self.idle_seconds < 0:
            raise ValueError("Pool.idle_seconds cannot be negative")
        if self.lane not in {INTERACTIVE, BULK}:
            raise ValueError(f"Pool.lane must be {INTERACTIVE!r} or {BULK!r}")


@dataclass
class PoolState:
    """A pool's members in this process."""

    spec: Pool
    factory: Callable[[], Any]
    base: Any
    members: List[Any] = field(default_factory=list)
    idle: List[Any] = field(default_factory=list)
    last_active: dict = field(default_factory=dict)
    steps_started: int = 0

    def __post_init__(self) -> None:
        self.members = [self.base]
        self.idle = [self.base]
        self.last_active = {id(self.base): time.monotonic()}

    @property
    def busy(self) -> int:
        return len(self.members) - len(self.idle)

    def release(self, member: Any) -> None:
        self.last_active[id(member)] = time.monotonic()
        if member in self.members and member not in self.idle:
            self.idle.append(member)

    def retirable(self) -> List[Any]:
        """Idle members beyond ``min`` that have waited out ``idle_seconds``."""
        now = time.monotonic()
        spare = len(self.members) - self.spec.min
        retiring = []
        for member in list(self.idle):
            if spare <= 0:
                break
            if member is self.base:
                continue
            if now - self.last_active.get(id(member), now) >= self.spec.idle_seconds:
                retiring.append(member)
                spare -= 1
        return retiring

    def snapshot(self) -> dict:
        return {
            "members": len(self.members),
            "busy": self.busy,
            "min": self.spec.min,
            "max": self.spec.max,
            "lane": self.spec.lane,
            "steps_started": self.steps_started,
        }
