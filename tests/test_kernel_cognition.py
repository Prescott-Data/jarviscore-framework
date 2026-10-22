"""
Tests for 6B: AgentCognitionManager + AgentPhase.

What these tests prove:
- Tool classification separates thinking from action tools
- Budget tracking charges the correct phase bucket
- Phase transitions follow discovery → analysis → implementation → completion
- Cognition records and reports facts; it never steers the agent
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

    def test_a_declared_phase_wins_over_the_name_sets(self, cognition):
        from jarviscore.kernel.cognition import AgentPhase

        assert cognition.classify_tool("read_web_content", AgentPhase.DISCOVERY) == "thinking"
        assert cognition.classify_tool("search_internet_batch", "thinking") == "thinking"
        assert cognition.classify_tool("web_search", "action") == "action"
        assert cognition.classify_tool("publish_research_findings", AgentPhase.COMPLETION) == "action"

    def test_researcher_reads_draw_on_the_research_budget(self):
        from jarviscore.kernel.cognition import AgentPhase

        cognition = AgentCognitionManager(ExecutionLease.for_role("researcher"))
        cognition.track_usage("read_web_content", tokens=50_000, declared_phase=AgentPhase.DISCOVERY)

        assert cognition.lease.thinking_used == 50_000
        assert cognition.lease.action_used == 0

    def test_every_default_researcher_reader_is_declared_as_discovery(self):
        from jarviscore.kernel.cognition import AgentPhase
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent

        tools = ResearcherSubAgent(agent_id="r", llm_client=None)._tools
        readers = ("search_internet", "search_internet_batch", "read_web_content", "rag_query")
        # rag_query is offered only with the [rag] extra installed.
        for name in (n for n in readers if n in tools or n != "rag_query"):
            assert getattr(tools[name].phase, "value", tools[name].phase) == AgentPhase.DISCOVERY.value


class TestRegisteredPhaseThroughRun:
    """BaseSubAgent.run hands the registered phase to the lease."""

    @staticmethod
    def _run_one_tool_call(tool_name, phase=None):
        import asyncio
        import json

        from jarviscore.kernel.subagent import BaseSubAgent

        replies = [
            f"THOUGHT: look\nTOOL: {tool_name}\nPARAMS: {json.dumps({})}",
            "THOUGHT: done\nDONE: done\nRESULT: {}",
        ]

        class _LLM:
            async def generate(self, messages=None, **kwargs):
                reply = replies.pop(0) if replies else replies_last
                return {"content": reply, "tokens": {"input": 100, "output": 100, "total": 200}, "cost_usd": 0.0}

        replies_last = "THOUGHT: done\nDONE: done\nRESULT: {}"

        class _Agent(BaseSubAgent):
            def get_system_prompt(self, *args, **kwargs):
                return "system"

            def setup_tools(self):
                declared = {"phase": phase} if phase else {}
                self.register_tool(
                    tool_name, lambda: {"status": "success", "content": "page"}, "read", **declared
                )

        agent = _Agent(agent_id="phase", role="researcher", llm_client=_LLM())
        asyncio.run(agent.run(task="t", max_turns=3))
        return agent._cognition.lease

    # Each turn bills 200 tokens; the closing DONE turn is always action.
    def test_a_declared_discovery_tool_draws_on_the_thinking_budget(self):
        lease = self._run_one_tool_call("fetch_page", phase="discovery")
        assert (lease.thinking_used, lease.action_used) == (200, 200)

    def test_an_undeclared_tool_keeps_its_name_classification(self):
        thinking = self._run_one_tool_call("read_turn_result")
        assert (thinking.thinking_used, thinking.action_used) == (200, 200)

        action = self._run_one_tool_call("fetch_page")
        assert (action.thinking_used, action.action_used) == (0, 400)


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


class TestActedRecord:

    def test_has_acted_flag(self, cognition):
        assert cognition.has_acted is False
        cognition.track_usage("generate_code", tokens=100)
        assert cognition.has_acted is True

    def test_done_does_not_set_has_acted(self, cognition):
        """The 'done' tool itself is not an action."""
        cognition.track_usage("done", tokens=0)
        assert cognition.has_acted is False


class TestRecordsWithoutSteering:
    """Cognition reports what happened; it never decides the agent's next move."""

    def test_no_steering_methods_remain(self, cognition):
        for name in (
            "detect_spinning", "detect_premature_done", "get_intervention",
            "is_repeat_failure", "failure_memory_block", "evaluate_convergence",
            "check_stall_verdict", "convergence",
        ):
            assert not hasattr(cognition, name), name

    def test_repeated_identical_tool_keeps_running(self, cognition):
        for _ in range(20):
            cognition.track_usage("web_search", tokens=10)
        assert cognition.should_continue() is True

    def test_budget_facts_state_remaining_resources(self):
        lease = ExecutionLease(
            max_total_tokens=1000, thinking_budget=1000, action_budget=1000,
            wall_clock_ms=60_000,
        )
        cognition = AgentCognitionManager(lease)
        cognition.track_usage("generate_code", tokens=950)
        facts = cognition.budget_facts()
        assert facts.startswith("Remaining: 50 of 1000 tokens")
        assert "of 60s wall clock" in facts
        for steer in ("stop", "call done", "wrap up", "should", "must"):
            assert steer not in facts.lower()


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
