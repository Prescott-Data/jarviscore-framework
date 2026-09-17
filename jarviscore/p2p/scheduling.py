"""Knowing when this process was not scheduled to observe anything.

SWIM decides a peer is failing when a PONG does not arrive inside the probe
budget. That inference holds only if we were actually running while the budget
elapsed. When the SWIM thread is descheduled — a long GIL hold from tokenizer or
inference work in the same process, a blocking call on another thread — the PONG
may arrive perfectly on time and simply not be read until later. The timeout is
then a fact about this process, and turning it into a claim about a peer is the
same mistake as reporting a conclusion in place of an observation.

So measure it. A ticker that sleeps a fixed interval and compares the elapsed
time against the interval it asked for reports exactly how long this thread was
not running. Nothing else in the process needs to cooperate, and there is no
guess involved: the number is the difference between what we asked the loop for
and what the loop gave us.

Raising probe timeouts does not address this. A timeout large enough for the
worst pause is also large enough to miss a genuinely dead peer for that long,
and the pause has no fixed size — it scales with model, batch and hardware. The
question worth answering is not "how long might we stall" but "did we stall
during the window we are about to draw a conclusion from".
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Deque, Optional, Tuple

logger = logging.getLogger(__name__)


class SchedulingMonitor:
    """Records how long this event loop was unable to run.

    Args:
        tick: How often to sample. Shorter samples resolve short pauses;
            the cost is one wakeup per tick on an otherwise idle loop.
        window: How far back samples are kept. Only needs to cover the
            longest probe budget a caller will ask about.
    """

    def __init__(self, tick: float = 0.1, window: float = 60.0) -> None:
        self._tick = tick
        self._window = window
        self._stalls: Deque[Tuple[float, float]] = deque()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.max_stall = 0.0

    async def run(self) -> None:
        """Sample until stopped. Intended to be scheduled on the loop it watches."""
        self._running = True
        while self._running:
            asked_at = time.monotonic()
            await asyncio.sleep(self._tick)
            elapsed = time.monotonic() - asked_at
            stall = elapsed - self._tick
            if stall > 0:
                self._record(stall)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_event_loop().create_task(
                self.run(), name="swim-scheduling-monitor",
            )

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def _record(self, stall: float) -> None:
        now = time.monotonic()
        self._stalls.append((now, stall))
        self.max_stall = max(self.max_stall, stall)
        horizon = now - self._window
        while self._stalls and self._stalls[0][0] < horizon:
            self._stalls.popleft()

    def stall_within(self, seconds: float) -> float:
        """Total time this loop was not running over the last ``seconds``."""
        if seconds <= 0:
            return 0.0
        horizon = time.monotonic() - seconds
        return sum(stall for at, stall in self._stalls if at >= horizon)

    def observed_fraction(self, seconds: float) -> float:
        """How much of the last ``seconds`` this loop was actually running.

        1.0 means it never missed a beat; 0.0 means it was descheduled for the
        whole window and saw none of it.
        """
        if seconds <= 0:
            return 1.0
        return max(0.0, 1.0 - self.stall_within(seconds) / seconds)
