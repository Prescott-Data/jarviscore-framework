"""A bounded outbox, so a memory write is not a step in the agent's turn.

`log_turn` used to await an HTTP round trip in the middle of reasoning, and a
failed write was logged at debug and forgotten. Both are the same mistake: the
turn was made to care about the state of a downstream service. Memory is a
consequence of thinking, not a part of it.

A submitted write is queued and returns immediately. One worker drains the queue
in order, so events reach Athena in the order the agent produced them. The queue
is bounded, because an unbounded one turns a memory outage into a memory leak.

Retries need care, and this is the part worth reading. Replaying a write that
actually landed stores it twice, and a memory tier with duplicates is its own
kind of wrong — worse than a gap, because a gap is visible and a duplicate reads
as corroboration. So a retry only happens when the caller can promise the
receiver deduplicates on the key we attach. Without that promise a failed write
is dropped and counted, which is a smaller lie than an invented one.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: Metadata field carrying the client-generated key a receiver deduplicates on.
IDEMPOTENCY_KEY = "idempotency_key"

Send = Callable[..., Awaitable[Any]]


class BreakerOpen(RuntimeError):
    """Raised instead of calling a service that is known to be down."""


@dataclass
class CircuitBreaker:
    """Stops calling a service that is failing, and notices when it returns.

    Owned by the boundary it protects. The previous behaviour disabled the whole
    memory tier after one failed initialisation, which turned a thirty-second
    Athena restart into a dead tier for the life of the process. A breaker is
    that protection without the permanence: it opens after repeated failure, and
    after a cooldown lets exactly one call through to find out what is true now.
    """

    threshold: int = 3
    cooldown: float = 30.0
    _failures: int = field(default=0, init=False)
    _opened_at: Optional[float] = field(default=None, init=False)
    _probing: bool = field(default=False, init=False)

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "probing" if self._probing else "open"

    def allows(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= self.cooldown:
            self._probing = True
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probing = False

    def record_failure(self) -> None:
        self._failures += 1
        self._probing = False
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()


@dataclass
class Write:
    """One queued call: the bound method to make it with, and its arguments."""

    send: Send
    kwargs: Dict[str, Any]
    key: str = field(default_factory=lambda: uuid.uuid4().hex)
    attempts: int = 0


@dataclass
class OutboxStats:
    """What the outbox has done. A quiet tier and a working tier look alike."""

    submitted: int = 0
    shipped: int = 0
    retried: int = 0
    dropped_overflow: int = 0
    dropped_exhausted: int = 0
    depth: int = 0
    breaker: str = "closed"
    last_success_at: Optional[float] = None
    last_error: Optional[str] = None

    @property
    def dropped(self) -> int:
        return self.dropped_overflow + self.dropped_exhausted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "submitted": self.submitted,
            "shipped": self.shipped,
            "retried": self.retried,
            "dropped": self.dropped,
            "dropped_overflow": self.dropped_overflow,
            "dropped_exhausted": self.dropped_exhausted,
            "depth": self.depth,
            "breaker": self.breaker,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
        }


class Outbox:
    """Queues writes and ships them in order behind a circuit breaker.

    Args:
        max_queue: Events held before the oldest is dropped. A gap in old
            history costs less than losing what the agent just did.
        max_attempts: Tries per write. Forced to 1 unless ``deduplicates``,
            because a retry without deduplication invents history.
        deduplicates: The receiver honours ``IDEMPOTENCY_KEY``. This is a
            statement about the deployment, so it is the operator's to make.
        breaker: Shared with the boundary being called, when there is one.
    """

    def __init__(
        self,
        *,
        max_queue: int = 1000,
        max_attempts: int = 4,
        base_delay: float = 0.5,
        max_delay: float = 15.0,
        deduplicates: bool = False,
        breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        if max_attempts > 1 and not deduplicates:
            logger.debug(
                "Outbox: retries disabled — the receiver does not promise to "
                "deduplicate, and a replayed write would duplicate history."
            )
        self._max_queue = max_queue
        self._max_attempts = max_attempts if deduplicates else 1
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._deduplicates = deduplicates
        self._breaker = breaker or CircuitBreaker()
        self._queue: "deque[Write]" = deque()
        self._wake = asyncio.Event()
        self._drained = asyncio.Event()
        self._drained.set()
        self._worker: Optional[asyncio.Task] = None
        self._stopping = False
        self.stats = OutboxStats()

    # ── submitting ───────────────────────────────────────────────────────────

    def submit(self, send: Send, **kwargs: Any) -> None:
        """Queue a call. Returns as soon as it is queued; never raises."""
        write = Write(send=send, kwargs=dict(kwargs))
        if self._deduplicates:
            metadata = dict(write.kwargs.get("metadata") or {})
            metadata[IDEMPOTENCY_KEY] = write.key
            write.kwargs["metadata"] = metadata

        if len(self._queue) >= self._max_queue:
            self._queue.popleft()
            self.stats.dropped_overflow += 1
            logger.warning(
                "Outbox full at %d events; oldest dropped (%d lost so far)",
                self._max_queue, self.stats.dropped_overflow,
            )

        self._queue.append(write)
        self.stats.submitted += 1
        self.stats.depth = len(self._queue)
        self._drained.clear()
        self._wake.set()
        self._ensure_worker()

    # ── lifecycle ────────────────────────────────────────────────────────────

    def _ensure_worker(self) -> None:
        if self._worker is not None and not self._worker.done():
            return
        try:
            self._worker = asyncio.get_running_loop().create_task(
                self._run(), name="athena-outbox",
            )
        except RuntimeError:
            # No loop yet: the first submit inside a running loop starts it.
            self._worker = None

    async def flush(self, timeout: float = 5.0) -> bool:
        """Wait for the queue to drain. False when it did not finish in time."""
        if not self._queue:
            return True
        self._ensure_worker()
        self._wake.set()
        try:
            await asyncio.wait_for(self._drained.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return False
        return True

    async def close(self, timeout: float = 5.0) -> bool:
        """Ship what is queued, then stop. Reports whether anything was left."""
        drained = await self.flush(timeout=timeout)
        self._stopping = True
        self._wake.set()
        worker, self._worker = self._worker, None
        if worker is not None:
            try:
                await asyncio.wait_for(worker, timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                worker.cancel()
        if not drained:
            logger.warning(
                "Outbox closed with %d event(s) still queued", len(self._queue),
            )
        return drained

    # ── shipping ─────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        while True:
            if not self._queue:
                self._drained.set()
                if self._stopping:
                    return
                self._wake.clear()
                await self._wake.wait()
                continue

            if not self._breaker.allows():
                self.stats.breaker = self._breaker.state
                if self._stopping:
                    return
                await asyncio.sleep(min(self._base_delay, 1.0))
                continue

            write = self._queue[0]
            delivered = await self._attempt(write)
            self.stats.breaker = self._breaker.state

            if delivered:
                self._queue.popleft()
                self.stats.shipped += 1
                self.stats.depth = len(self._queue)
                continue

            write.attempts += 1
            if write.attempts >= self._max_attempts:
                self._queue.popleft()
                self.stats.dropped_exhausted += 1
                self.stats.depth = len(self._queue)
                logger.warning(
                    "Outbox gave up after %d attempt(s): %s",
                    write.attempts, self.stats.last_error,
                )
                continue

            self.stats.retried += 1
            await asyncio.sleep(self._backoff(write.attempts))

    async def _attempt(self, write: Write) -> bool:
        try:
            await write.send(**write.kwargs)
        except Exception as exc:  # noqa: BLE001 - the outcome matters, not the type
            self.stats.last_error = f"{type(exc).__name__}: {exc}"
            self._breaker.record_failure()
            return False
        self.stats.last_success_at = time.time()
        self.stats.last_error = None
        self._breaker.record_success()
        return True

    def _backoff(self, attempt: int) -> float:
        """Exponential with jitter, so a fleet does not retry in lockstep."""
        delay = min(self._base_delay * (2 ** (attempt - 1)), self._max_delay)
        return delay * (0.5 + random.random() / 2)
