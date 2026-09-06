"""Refusing to call a peer suspect for a probe this process never watched.

`FailureDetector.ping` retries, times out, and calls `members.mark_suspect(target)`
with the default reason `ping_timeout`. That call is the moment an observation
about our own socket becomes a claim about someone else's liveness, and it is
made without asking whether we were running while the budget elapsed.

This guard sits on that one call. When the reason is a timeout we observed
ourselves, and the scheduling monitor says this loop was descheduled for a
meaningful part of that window, the suspicion is declined: the peer stays ALIVE
and gets probed again on the next cycle, by a probe we can actually watch. The
judgement is deferred, not overruled — nothing here decides a peer is healthy,
it only declines to claim the opposite from evidence we did not collect.

Suspicion arriving from other nodes is untouched. That travels through
`merge_digest`, is another node's observation rather than ours, and our own
scheduling has no bearing on whether it is true.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from .scheduling import SchedulingMonitor

logger = logging.getLogger(__name__)

#: Reasons that mean "we timed out waiting", as opposed to "a peer told us".
LOCAL_OBSERVATION_REASONS = frozenset({
    "ping_timeout",
    "indirect_ping_timeout",
    "probe_timeout",
    "timeout",
})


@dataclass
class SuspicionGuardStats:
    raised: int = 0
    declined: int = 0
    max_stall_seconds: float = 0.0
    last_declined_peer: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "raised": self.raised,
            "declined": self.declined,
            "max_stall_seconds": round(self.max_stall_seconds, 3),
            "last_declined_peer": self.last_declined_peer,
        }


class SuspicionGuard:
    """Wraps ``MemberList.mark_suspect`` so a starved probe cannot accuse a peer.

    Args:
        monitor: Scheduling monitor for the loop the probe ran on.
        probe_budget: Probe window to assume when the caller does not say.
        min_observed_fraction: How much of the window this loop must have been
            running before a timeout is allowed to mean anything. At 0.5, a
            probe that spent half its budget with the loop descheduled is
            treated as unwatched rather than failed.
    """

    def __init__(
        self,
        monitor: SchedulingMonitor,
        *,
        probe_budget: float = 2.0,
        min_observed_fraction: float = 0.5,
    ) -> None:
        self._monitor = monitor
        self._probe_budget = probe_budget
        self._min_observed = min_observed_fraction
        self.stats = SuspicionGuardStats()

    def attach(self, member_list: Any) -> None:
        """Install the guard on a live MemberList."""
        original = member_list.mark_suspect

        async def mark_suspect(
            addr: Tuple[str, int],
            incarnation: Optional[int] = None,
            suspicion_reason: str = "ping_timeout",
            timeout_duration: Optional[float] = None,
            *args: Any,
            **kwargs: Any,
        ) -> bool:
            if self._should_decline(suspicion_reason, timeout_duration):
                window = timeout_duration or self._probe_budget
                stalled = self._monitor.stall_within(window)
                self.stats.declined += 1
                self.stats.max_stall_seconds = max(self.stats.max_stall_seconds, stalled)
                self.stats.last_declined_peer = f"{addr[0]}:{addr[1]}"
                logger.info(
                    "SWIM suspicion declined for %s:%s — this process was descheduled "
                    "for %.2fs of a %.2fs probe window, so the timeout describes us, "
                    "not the peer. Re-probing next cycle.",
                    addr[0], addr[1], stalled, window,
                )
                return False

            self.stats.raised += 1
            return await original(
                addr, incarnation, suspicion_reason, timeout_duration, *args, **kwargs
            )

        member_list.mark_suspect = mark_suspect

    def _should_decline(
        self, suspicion_reason: str, timeout_duration: Optional[float]
    ) -> bool:
        if suspicion_reason not in LOCAL_OBSERVATION_REASONS:
            return False
        window = timeout_duration or self._probe_budget
        return self._monitor.observed_fraction(window) < self._min_observed
