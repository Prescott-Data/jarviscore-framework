"""
Tests for 6B: AgentCognitionManager + AgentPhase.

What these tests prove:
- Tool classification separates thinking from action tools
- Budget tracking charges the correct phase bucket
- Phase transitions follow discovery → analysis → implementation → completion
- Spinning detection catches 3+ consecutive identical tool calls
- Cognitive gate prevents premature done() calls
- Interventions fire on spinning and low budget
- Budget summary provides accurate snapshot
"""

import pytest

from jarviscore.kernel.lease import ExecutionLease
from jarviscore.kernel.cognition import (
    AgentCognitionManager,
    AgentPhase,
    THINKING_TOOLS,
    ACTION_TOOLS,
)


@pytest.fixture
def cognition():
    """Cognition manager with default lease."""
    return AgentCognitionManager(ExecutionLease())


@pytest.fixture
def coder_cognition():
    """Cognition manager with coder lease (larger budgets)."""
    return AgentCognitionManager(ExecutionLease.for_role("coder"))


class TestToolClassification:

    def test_thinking_tools(self, cognition):
        for tool in THINKING_TOOLS:
            assert cognition.classify_tool(tool) == "thinking"

    def test_action_tools(self, cognition):
        for tool in ACTION_TOOLS:
            assert cognition.classify_tool(tool) == "action"

    def test_unknown_tool_defaults_to_action(self, cognition):
        assert cognition.classify_tool("unknown_tool") == "action"


class TestBudgetTracking:

    def test_thinking_tool_charges_thinking(self, cognition):
        cognition.track_usage("web_search", tokens=500)
        assert cognition.lease.thinking_used == 500
        assert cognition.lease.action_used == 0

    def test_action_tool_charges_action(self, cognition):
        cognition.track_usage("generate_code", tokens=1000)
        assert cognition.lease.action_used == 1000
        assert cognition.lease.thinking_used == 0

    def test_zero_token_tracking(self, cognition):
        """Tool invocation with 0 tokens still records the tool."""
        cognition.track_usage("web_search", tokens=0)
        assert cognition.tool_history == ["web_search"]
        assert cognition.lease.thinking_used == 0

    def test_multiple_tools_accumulate(self, cognition):
        cognition.track_usage("web_search", tokens=300)
        cognition.track_usage("analyze", tokens=200)
        cognition.track_usage("generate_code", tokens=1000)
        assert cognition.lease.thinking_used == 500
        assert cognition.lease.action_used == 1000
        assert len(cognition.tool_history) == 3


class TestPhaseTransitions:

    def test_starts_in_discovery(self, cognition):
        assert cognition.phase == AgentPhase.DISCOVERY

    def test_stays_discovery_under_30_pct(self, coder_cognition):
        # 29% of 132_000 = 38_280
        coder_cognition.track_usage("web_search", tokens=38_000)
        assert coder_cognition.phase == AgentPhase.DISCOVERY

    def test_transitions_to_analysis_at_30_pct(self, coder_cognition):
        # 30% of 132_000 = 39_600
        coder_cognition.track_usage("web_search", tokens=40_000)
        assert coder_cognition.phase == AgentPhase.ANALYSIS

    def test_transitions_to_implementation_at_60_pct(self, coder_cognition):
        # 60% of 132_000 = 79_200
        coder_cognition.track_usage("web_search", tokens=80_000)
        assert coder_cognition.phase == AgentPhase.IMPLEMENTATION

    def test_transitions_to_implementation_on_action(self, cognition):
        cognition.track_usage("generate_code", tokens=100)
        assert cognition.phase == AgentPhase.IMPLEMENTATION

    def test_transitions_to_completion_on_done(self, cognition):
        cognition.track_usage("generate_code", tokens=100)
        cognition.track_usage("done", tokens=0)
        assert cognition.phase == AgentPhase.COMPLETION

    def test_done_overrides_discovery_phase(self, cognition):
        """done() transitions to COMPLETION even from early phase."""
        cognition.track_usage("done", tokens=0)
        assert cognition.phase == AgentPhase.COMPLETION


class TestShouldContinue:

    def test_continues_when_budget_available(self, cognition):
        assert cognition.should_continue() is True

    def test_stops_on_done(self, cognition):
        cognition.track_usage("done", tokens=0)
        assert cognition.should_continue() is False

    def test_stops_on_budget_exhaustion(self):
        lease = ExecutionLease(thinking_budget=100)
        cognition = AgentCognitionManager(lease)
        cognition.track_usage("web_search", tokens=100)
        assert cognition.should_continue() is False


class TestSpinningDetection:

    def test_no_spinning_with_varied_tools(self, cognition):
        cognition.track_usage("web_search", tokens=100)
        cognition.track_usage("analyze", tokens=100)
        cognition.track_usage("web_search", tokens=100)
        assert not cognition.detect_spinning("web_search")

    def test_detects_spinning_at_threshold(self, cognition):
        for _ in range(3):
            cognition.track_usage("web_search", tokens=100)
        assert cognition.detect_spinning("web_search")

    def test_no_spinning_below_threshold(self, cognition):
        cognition.track_usage("web_search", tokens=100)
        cognition.track_usage("web_search", tokens=100)
        assert not cognition.detect_spinning("web_search")

    def test_spinning_resets_on_different_tool(self, cognition):
        cognition.track_usage("web_search", tokens=100)
        cognition.track_usage("web_search", tokens=100)
        cognition.track_usage("analyze", tokens=100)
        assert not cognition.detect_spinning("analyze")


class TestCognitiveGate:

    def test_premature_done_in_discovery(self, cognition):
        """done() in discovery phase is premature."""
        assert cognition.detect_premature_done() is True

    def test_premature_done_without_action(self, cognition):
        """done() after only thinking is premature."""
        cognition.track_usage("web_search", tokens=50_000)
        # Now in ANALYSIS phase but no action taken
        assert cognition.detect_premature_done() is True

    def test_not_premature_after_action(self, cognition):
        cognition.track_usage("generate_code", tokens=1000)
        assert cognition.detect_premature_done() is False

    def test_has_acted_flag(self, cognition):
        assert cognition.has_acted is False
        cognition.track_usage("generate_code", tokens=100)
        assert cognition.has_acted is True

    def test_done_does_not_set_has_acted(self, cognition):
        """The 'done' tool itself is not an action."""
        cognition.track_usage("done", tokens=0)
        assert cognition.has_acted is False


class TestInterventions:

    def test_no_intervention_normally(self, cognition):
        cognition.track_usage("web_search", tokens=100)
        assert cognition.get_intervention() is None

    def test_spinning_intervention(self, cognition):
        for _ in range(3):
            cognition.track_usage("web_search", tokens=100)
        msg = cognition.get_intervention()
        assert msg is not None
        assert "web_search" in msg
        assert "3 times" in msg

    def test_low_budget_intervention(self):
        lease = ExecutionLease(max_total_tokens=1000, thinking_budget=1000, action_budget=1000)
        cognition = AgentCognitionManager(lease)
        cognition.track_usage("web_search", tokens=950)
        msg = cognition.get_intervention()
        assert msg is not None
        assert "remaining" in msg.lower()


class TestBudgetSummary:

    def test_summary_shape(self, cognition):
        cognition.track_usage("web_search", tokens=500)
        cognition.track_usage("generate_code", tokens=1000)

        s = cognition.get_budget_summary()
        assert s["phase"] == "implementation"
        assert s["has_acted"] is True
        assert s["tool_count"] == 2
        assert s["done_called"] is False
        assert "lease" in s
