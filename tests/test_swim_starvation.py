"""A starved probe says nothing about a peer (#138).

SWIM decided peers were failing while this process held the GIL doing inference.
LIFEGUARD flagged the results as likely false positives, which is the detector
noticing it had been misled without being able to say why. The reason is that
`FailureDetector.ping` converts "no PONG inside the budget" into "that peer is
suspect" without asking whether this process was running while the budget
elapsed. These tests hold the boundary: a timeout observed by a loop that was
descheduled describes the loop, not the peer.
"""

import asyncio
import time

import pytest

from jarviscore.p2p.scheduling import SchedulingMonitor
from jarviscore.p2p.suspicion import LOCAL_OBSERVATION_REASONS, SuspicionGuard


class FakeMonitor(SchedulingMonitor):
    """A monitor whose stalls are stated rather than measured."""

    def __init__(self, stall: float = 0.0):
        super().__init__()
        self._fixed = stall

    def stall_within(self, seconds: float) -> float:
        return min(self._fixed, seconds)


class RecordingMemberList:
    def __init__(self):
        self.suspected = []

    async def mark_suspect(
        self, addr, incarnation=None, suspicion_reason="ping_timeout",
        timeout_duration=None, attempt_number=None, indirect_ping_attempted=False,
    ):
        self.suspected.append((addr, suspicion_reason))
        return True


# ──────────────────────────────────────────────────────────────────
# Measuring the stall
# ──────────────────────────────────────────────────────────────────

class TestSchedulingMonitor:

    @pytest.mark.asyncio
    async def test_an_unblocked_loop_reports_almost_no_stall(self):
        monitor = SchedulingMonitor(tick=0.01)
        monitor.start()
        await asyncio.sleep(0.15)
        monitor.stop()

        assert monitor.stall_within(1.0) < 0.05
        assert monitor.observed_fraction(1.0) > 0.9

    @pytest.mark.asyncio
    async def test_a_blocked_loop_reports_the_stall(self):
        """A synchronous sleep is what a GIL-holding tokenizer looks like."""
        monitor = SchedulingMonitor(tick=0.01)
        monitor.start()
        await asyncio.sleep(0.02)
        time.sleep(0.3)                     # blocks the loop, as inference does
        await asyncio.sleep(0.02)
        monitor.stop()

        assert monitor.stall_within(2.0) >= 0.25
        assert monitor.max_stall >= 0.25

    def test_stalls_age_out_of_the_window(self):
        monitor = SchedulingMonitor(tick=0.01, window=0.05)
        monitor._record(0.5)
        assert monitor.stall_within(10.0) >= 0.5

        time.sleep(0.06)
        monitor._record(0.001)          # any sample prunes what is now too old

        assert monitor.stall_within(10.0) < 0.5
        assert monitor.max_stall >= 0.5   # the worst seen is not forgotten

    def test_observed_fraction_is_bounded(self):
        monitor = FakeMonitor(stall=99.0)
        assert monitor.observed_fraction(2.0) == 0.0
        assert FakeMonitor(stall=0.0).observed_fraction(2.0) == 1.0

    def test_a_zero_window_is_fully_observed(self):
        assert SchedulingMonitor().observed_fraction(0) == 1.0
        assert SchedulingMonitor().stall_within(0) == 0.0


# ──────────────────────────────────────────────────────────────────
# Declining the accusation
# ──────────────────────────────────────────────────────────────────

class TestSuspicionGuard:

    def _guard(self, stall, **kwargs):
        members = RecordingMemberList()
        guard = SuspicionGuard(FakeMonitor(stall), probe_budget=2.0, **kwargs)
        guard.attach(members)
        return members, guard

    @pytest.mark.asyncio
    async def test_a_watched_timeout_still_accuses(self):
        members, guard = self._guard(stall=0.0)

        assert await members.mark_suspect(("10.0.0.1", 7946)) is True
        assert members.suspected == [(("10.0.0.1", 7946), "ping_timeout")]
        assert guard.stats.raised == 1

    @pytest.mark.asyncio
    async def test_a_starved_timeout_does_not(self):
        members, guard = self._guard(stall=1.8)

        assert await members.mark_suspect(("10.0.0.1", 7946)) is False
        assert members.suspected == []
        assert guard.stats.declined == 1
        assert guard.stats.last_declined_peer == "10.0.0.1:7946"

    @pytest.mark.asyncio
    async def test_the_peer_is_left_alive_for_the_next_probe(self):
        """Declining defers the judgement; it does not assert the peer is well."""
        members, guard = self._guard(stall=1.8)
        await members.mark_suspect(("10.0.0.1", 7946))

        guard._monitor = FakeMonitor(0.0)     # the pause is over
        assert await members.mark_suspect(("10.0.0.1", 7946)) is True
        assert members.suspected == [(("10.0.0.1", 7946), "ping_timeout")]

    @pytest.mark.asyncio
    async def test_suspicion_from_another_node_is_never_declined(self):
        """Their observation is not affected by our scheduling."""
        members, guard = self._guard(stall=99.0)

        assert await members.mark_suspect(
            ("10.0.0.1", 7946), None, "gossip", None,
        ) is True
        assert guard.stats.declined == 0

    @pytest.mark.asyncio
    async def test_the_declared_probe_window_is_used_when_given(self):
        members, guard = self._guard(stall=1.0)

        # 1.0s stall against a 10s probe: most of the window was watched.
        assert await members.mark_suspect(
            ("10.0.0.1", 7946), None, "ping_timeout", 10.0,
        ) is True
        # The same stall against a 1.5s probe: most of it was not.
        assert await members.mark_suspect(
            ("10.0.0.2", 7946), None, "ping_timeout", 1.5,
        ) is False

    @pytest.mark.asyncio
    async def test_the_threshold_is_configurable(self):
        members, _ = self._guard(stall=1.0, min_observed_fraction=0.9)
        assert await members.mark_suspect(("10.0.0.1", 7946)) is False

        members, _ = self._guard(stall=1.0, min_observed_fraction=0.1)
        assert await members.mark_suspect(("10.0.0.1", 7946)) is True

    @pytest.mark.asyncio
    async def test_every_local_timeout_reason_is_covered(self):
        for reason in LOCAL_OBSERVATION_REASONS:
            members, guard = self._guard(stall=99.0)
            assert await members.mark_suspect(
                ("10.0.0.1", 7946), None, reason, None,
            ) is False, reason

    @pytest.mark.asyncio
    async def test_declines_are_counted_not_silent(self):
        members, guard = self._guard(stall=1.8)
        await members.mark_suspect(("10.0.0.1", 7946))

        stats = guard.stats.to_dict()
        assert stats["declined"] == 1
        assert stats["max_stall_seconds"] >= 1.7
        assert stats["last_declined_peer"] == "10.0.0.1:7946"


class TestEndToEnd:

    @pytest.mark.asyncio
    async def test_inference_in_process_does_not_flap_a_live_peer(self):
        """The reported failure: four nodes, LLM work, peers marked DEAD."""
        monitor = SchedulingMonitor(tick=0.01)
        monitor.start()
        await asyncio.sleep(0.03)             # the monitor is ticking
        members = RecordingMemberList()
        guard = SuspicionGuard(monitor, probe_budget=0.5)
        guard.attach(members)

        time.sleep(0.4)                       # a model holds the GIL
        await asyncio.sleep(0.02)
        declined = await members.mark_suspect(("10.0.0.1", 7946))

        monitor.stop()
        assert declined is False
        assert members.suspected == []
        assert guard.stats.declined == 1

    @pytest.mark.asyncio
    async def test_a_pause_small_against_the_budget_still_accuses(self):
        """The guard is proportional: a brief pause is not an excuse."""
        monitor = SchedulingMonitor(tick=0.01)
        monitor.start()
        await asyncio.sleep(0.03)
        members = RecordingMemberList()
        SuspicionGuard(monitor, probe_budget=10.0).attach(members)

        time.sleep(0.3)
        await asyncio.sleep(0.02)
        raised = await members.mark_suspect(("10.0.0.1", 7946))

        monitor.stop()
        assert raised is True
