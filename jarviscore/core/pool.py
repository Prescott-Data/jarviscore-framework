"""Elastic worker pools: more instances of one agent while its work queues up.

A pooled agent is one logical agent. Every member shares the agent's id, so a step
one member started and checkpointed can be resumed by any other, and the step-claim
lease stays the only thing that decides who runs a step. Members are separate
instances because an agent's kernel, subagent cache and sandbox serve one step at
a time.

All work reaches an agent through its pool: durable steps, capability needs,
``Mesh.workflow``, ``Mesh.fanout``, ``Mesh.delegate`` and peer requests each lease
a member for as long as they run.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Deque, Iterator, List, Optional

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


# Members held by the current call chain, so a chain that already holds every
# member of a pool is told so instead of waiting on itself forever.
_HELD: ContextVar[frozenset] = ContextVar("jarviscore_pool_members_held", default=frozenset())


@contextmanager
def holding(member: Any) -> Iterator[None]:
    """Mark ``member`` as held by the current call chain while the block runs."""
    token = _HELD.set(_HELD.get() | {id(member)})
    try:
        yield
    finally:
        _HELD.reset(token)


@dataclass
class PoolState:
    """A pool's members in this process.

    Every agent the mesh runs has one: an agent registered without a ``Pool`` is a
    pool of exactly one instance, so all work reaches an instance the same way and
    no instance ever runs two pieces of work at once.
    """

    spec: Pool
    factory: Optional[Callable[[], Any]]
    base: Any
    declared: bool = True
    grow: Optional[Callable[[], Awaitable[Any]]] = None
    members: List[Any] = field(default_factory=list)
    idle: List[Any] = field(default_factory=list)
    last_active: dict = field(default_factory=dict)
    steps_started: int = 0
    growing: int = 0
    waiters: Deque[asyncio.Future] = field(default_factory=deque)

    def __post_init__(self) -> None:
        self.members = [self.base]
        self.idle = [self.base]
        self.last_active = {id(self.base): time.monotonic()}

    @property
    def busy(self) -> int:
        return len(self.members) - len(self.idle)

    def can_grow(self) -> bool:
        return (
            self.grow is not None
            and len(self.members) + self.growing < self.spec.max
        )

    def free(self) -> int:
        """Members available now or that could be added without waiting on work."""
        room = self.spec.max - len(self.members) - self.growing if self.grow else 0
        return len(self.idle) + max(0, room)

    async def try_acquire(self) -> Optional[Any]:
        """An idle member, or a new one if the pool may grow; None when it is full."""
        if self.idle:
            return self.idle.pop()
        if not self.can_grow():
            return None
        self.growing += 1
        try:
            return await self.grow()
        finally:
            self.growing -= 1

    async def acquire(self) -> Any:
        """A member for one piece of work, waiting for one to be released if all are busy."""
        member = await self.try_acquire()
        if member is not None:
            return member
        held = _HELD.get()
        if all(id(m) in held for m in self.members) and not self.growing:
            raise RuntimeError(
                f"Agent {getattr(self.base, 'agent_id', '?')!r} is waiting on itself: "
                f"this call chain already holds all {len(self.members)} of its "
                f"instance(s). Give it a Pool with a larger max to let work it "
                f"starts run on another instance."
            )
        waiter = asyncio.get_running_loop().create_future()
        self.waiters.append(waiter)
        try:
            return await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():
                self.release(waiter.result())
            raise

    @asynccontextmanager
    async def lease(self) -> AsyncIterator[Any]:
        """Hold one member for the duration of the block."""
        member = await self.acquire()
        try:
            with holding(member):
                yield member
        finally:
            self.release(member)

    def release(self, member: Any) -> None:
        self.last_active[id(member)] = time.monotonic()
        if member not in self.members or member in self.idle:
            return
        while self.waiters:
            waiter = self.waiters.popleft()
            if not waiter.done():
                waiter.set_result(member)
                return
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
