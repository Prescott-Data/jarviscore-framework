"""
Tests for CONVERGENCE_STALL fixes:
  1. Double-evaluation bug — evaluate() called once per tool call, not twice
  2. check_stall_verdict() — cached verdict without re-evaluation
  3. Strategic pivot — one recovery turn before escalation
"""

import pytest

from jarviscore.kernel.cognition import (
    AgentCognitionManager,
    ConvergenceGovernor,
)
from jarviscore.kernel.lease import ExecutionLease


# ─────────────────────────────────────────────────────────────────────────────
# Fix 1: Single-evaluation — verify no double-counting
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleEvaluation:
    """Verify evaluate() is called exactly once per tool call via track_usage."""

    def test_track_usage_evaluates_once(self):
        """track_usage() should call evaluate() exactly once, incrementing
        the governor's turn counter by 1 (not 2)."""
        lease = ExecutionLease()
        mgr = AgentCognitionManager(lease=lease)

        mgr.track_usage("web_search", tokens=100, tool_output={"status": "success"})

        # Governor turn should be 1 (one evaluation), not 2
        assert mgr.convergence._turn == 1

    def test_three_different_tools_no_stall(self):
        """Calling 3 different tools should NOT trigger same_tool_streak."""
        lease = ExecutionLease()
        mgr = AgentCognitionManager(lease=lease)

        for tool in ["web_search", "analyze", "extract_page"]:
            mgr.track_usage(tool, tokens=100, tool_output={"status": "success", "content": "data"})

        assert mgr.convergence._same_tool_streak == 1  # Reset each time
        assert mgr.check_stall_verdict() is None

    def test_same_tool_five_times_triggers_stall(self):
        """Same tool called 5 times should trigger stall (tuned threshold)."""
        lease = ExecutionLease()
        mgr = AgentCognitionManager(lease=lease)

        result = {"status": "success", "content": "same content"}

        for i in range(5):
            mgr.track_usage("web_search", tokens=100, tool_output=result)

        # Should stall after 5 real calls
        verdict = mgr.check_stall_verdict()
        assert verdict is not None
        assert "same_tool_streak" in verdict["reason"]

    def test_four_same_tools_no_stall(self):
        """4 calls to the same tool should NOT trigger stall (threshold is 5).

        Uses outputs with different content lengths to produce distinct
        outcome signatures (the governor hashes content_len, not content text).
        """
        lease = ExecutionLease()
        mgr = AgentCognitionManager(lease=lease)

        for i in range(4):
            # Different content lengths → distinct outcome signatures
            result = {"status": "success", "content": "x" * (10 + i * 50)}
            mgr.track_usage("web_search", tokens=100, tool_output=result)

        verdict = mgr.check_stall_verdict()
        assert verdict is None


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2: check_stall_verdict() — cached without re-evaluation
# ─────────────────────────────────────────────────────────────────────────────

class TestCachedVerdict:
    """Verify check_stall_verdict() returns cached results."""

    def test_check_stall_verdict_no_reevaluate(self):
        """Calling check_stall_verdict() multiple times should NOT
        increment the governor's counters."""
        lease = ExecutionLease()
        mgr = AgentCognitionManager(lease=lease)

        mgr.track_usage("web_search", tokens=100, tool_output={"status": "success"})
        turn_after_track = mgr.convergence._turn

        # Call check_stall_verdict 5 times — should NOT change state
        for _ in range(5):
            mgr.check_stall_verdict()

        assert mgr.convergence._turn == turn_after_track

    def test_verdict_cached_after_stall(self):
        """After a stall is detected, check_stall_verdict() returns the
        same verdict object without re-evaluating."""
        gov = ConvergenceGovernor(max_same_tool_streak=2)

        result = {"status": "success"}
        gov.evaluate("web_search", result)
        gov.evaluate("web_search", result)  # Should trigger stall

        verdict1 = gov.check_stall_verdict()
        assert verdict1 is not None

        # Read again — should be identical, no side effects
        verdict2 = gov.check_stall_verdict()
        assert verdict2 is verdict1
        assert gov._turn == 2  # Not incremented

    def test_verdict_cleared_after_different_tool(self):
        """Verdict should be cleared when a new (different) tool call
        resets the streak below threshold."""
        gov = ConvergenceGovernor(max_same_tool_streak=3)

        # Build up a streak of 2
        gov.evaluate("web_search", {"status": "success", "content": "data"})
        gov.evaluate("web_search", {"status": "success", "content": "data"})
        assert gov.check_stall_verdict() is None  # Not yet at 3

        # Different tool resets streak
        gov.evaluate("analyze", {"status": "success", "content": "analysis"})
        assert gov.check_stall_verdict() is None


# ─────────────────────────────────────────────────────────────────────────────
# Fix 3: Strategic Pivot — one grace turn before escalation
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategicPivot:
    """Verify pivot mechanism at the state/cognition level."""

    def test_governor_streaks_reset(self):
        """After manually resetting streaks (as the pivot does), the
        governor should allow one more turn."""
        gov = ConvergenceGovernor(max_same_tool_streak=3)

        result = {"status": "success", "content": "data"}
        gov.evaluate("web_search", result)
        gov.evaluate("web_search", result)
        gov.evaluate("web_search", result)  # Streak = 3, stall triggered

        assert gov.check_stall_verdict() is not None

        # Simulate pivot: reset streaks
        gov._same_tool_streak = 0
        gov._equiv_streak = 0
        gov._last_verdict = None

        # One more call should NOT trigger stall (streak restarted)
        gov.evaluate("web_search", result)
        assert gov._same_tool_streak == 1
        assert gov.check_stall_verdict() is None

    def test_pivot_only_granted_once(self):
        """The pivot flag in internal_variables ensures at most one pivot."""
        from jarviscore.kernel.state import KernelState

        state = KernelState(task="test")

        # First pivot — should be allowed
        assert not state.internal_variables.get("_pivot_attempted")
        state.internal_variables["_pivot_attempted"] = True

        # Second check — should block
        assert state.internal_variables.get("_pivot_attempted") is True

    def test_stagnant_turns_respected_at_correct_threshold(self):
        """With the double-evaluation fix, stagnant_turns should count
        actual stagnant turns, not double-count them."""
        gov = ConvergenceGovernor(
            max_stagnant_turns=4,
            max_same_tool_streak=100,  # Disable
            max_equiv_streak=100,      # Disable
        )

        # 3 stagnant turns (error results, progress_score=0)
        for _ in range(3):
            gov.evaluate("different_tool_" + str(_), {"status": "error", "error": "fail"})

        assert gov.check_stall_verdict() is None  # Not yet at 4

        # 4th stagnant turn — should trigger
        gov.evaluate("yet_another", {"status": "error", "error": "fail"})
        verdict = gov.check_stall_verdict()
        assert verdict is not None
        assert "stagnant_turns" in verdict["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# Issue #58: content-true equivalence, param-aware streaks, novelty-as-progress
# ─────────────────────────────────────────────────────────────────────────────

class TestContentTrueEquivalence:
    """'Equivalent' must mean identical — never same-length or same-prefix."""

    def test_same_length_different_content_is_not_equivalent(self):
        """Paginated reads returning uniform page sizes are progress, not a stall."""
        gov = ConvergenceGovernor()
        for page in range(6):
            out = {"status": "success", "content": f"page-{page:04d}-" + "x" * 100}
            gov.evaluate("fetch_page", out, params={"page": page})
        assert gov._equiv_streak == 1
        assert gov.check_stall_verdict() is None

    def test_identical_outputs_are_equivalent_and_trip(self):
        gov = ConvergenceGovernor()
        out = {"status": "success", "content": "identical"}
        verdict = None
        for i in range(4):
            verdict = gov.evaluate("fetch_page", out, params={"page": i})
        assert verdict is not None
        assert "equivalent_outcome_streak" in verdict["reason"]

    def test_same_prefix_different_tail_is_not_equivalent(self):
        """Long strings sharing a 120+ char prefix are distinct outcomes."""
        gov = ConvergenceGovernor()
        prefix = "A" * 200
        for i in range(6):
            gov.evaluate("read", prefix + f"tail-{i}", params={"i": i})
        assert gov._equiv_streak == 1


class TestParamAwareStreak:
    """Same tool + different params is iteration; same tool + same params is spinning."""

    def test_same_tool_different_params_does_not_trip(self):
        gov = ConvergenceGovernor()
        verdict = None
        for i in range(8):
            verdict = gov.evaluate(
                "read_file",
                {"status": "success", "content": f"file {i} contents"},
                params={"path": f"/src/mod_{i}.py"},
            )
        assert verdict is None
        assert gov._same_tool_streak == 1

    def test_same_tool_same_params_still_trips(self):
        gov = ConvergenceGovernor()
        verdict = None
        for _ in range(5):
            verdict = gov.evaluate(
                "read_file",
                {"status": "success", "content": "same"},
                params={"path": "/src/one.py"},
            )
        assert verdict is not None
        assert "same_tool_streak" in verdict["reason"]

    def test_no_params_preserves_historical_name_only_streak(self):
        """Callers that don't pass params get exactly the old behavior."""
        gov = ConvergenceGovernor()
        verdict = None
        for i in range(5):
            verdict = gov.evaluate("web_search", {"status": "success", "content": f"r{i}"})
        assert verdict is not None
        assert "same_tool_streak" in verdict["reason"]


class TestNoveltyAsProgress:
    """Changing, non-error outputs count as progress even for unknown schemas."""

    def test_unknown_schema_changing_dicts_do_not_stagnate(self):
        """Domain dicts without status/content/results keys used to score 0.0."""
        gov = ConvergenceGovernor()
        verdict = None
        for i in range(8):
            verdict = gov.evaluate(
                "get_price", {"price": 100.0 + i, "zone": [99, 101]},
                params={"symbol": f"SYM{i}"},
            )
        assert verdict is None
        assert gov._stagnant_turns == 0

    def test_repeated_identical_unknown_dict_still_stalls(self):
        """No novelty, no recognized schema — that IS stagnation (and equivalence)."""
        gov = ConvergenceGovernor()
        verdict = None
        for i in range(6):
            verdict = gov.evaluate(
                "get_price", {"price": 100.0},
                params={"call": i},  # different params: isolate the outcome signals
            )
        assert verdict is not None

    def test_error_outputs_never_count_as_progress(self):
        gov = ConvergenceGovernor()
        for i in range(6):
            gov.evaluate(
                "flaky", {"status": "error", "error": f"boom {i}"},
                params={"attempt": i},
            )
        assert gov._stagnant_turns == 6


class TestResetStreaks:
    """Public reset replaces external pokes at private counters."""

    def test_reset_clears_streaks_and_verdict(self):
        gov = ConvergenceGovernor()
        out = {"status": "success", "content": "same"}
        for _ in range(5):
            gov.evaluate("tool_a", out)
        assert gov.check_stall_verdict() is not None

        gov.reset_streaks(reason="test pivot")
        assert gov._same_tool_streak == 0
        assert gov._equiv_streak == 0
        assert gov._stagnant_turns == 0
        assert gov.check_stall_verdict() is None
