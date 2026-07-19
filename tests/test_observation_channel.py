"""
Tests for issue #57: observation channel integrity.

What these tests prove:
- Clipped observations carry an explicit marker with the retrieval call
- Unclipped observations are byte-identical to before (non-breaking)
- The full result of recent turns is retrievable via read_turn_result,
  in chunks, with honest offset/remaining accounting
- read_turn_result is auto-registered on every subagent and classified
  as a thinking tool (recall, not action)
"""

import pytest

from jarviscore.kernel.cognition import THINKING_TOOLS
from jarviscore.kernel.state import KernelState
from jarviscore.kernel.subagent import (
    BaseSubAgent,
    _OBSERVATION_LIMIT,
    _TURN_RESULT_WINDOW,
    _clip_observation,
)


class _MinimalSubAgent(BaseSubAgent):
    """Smallest concrete subagent — just enough to exercise the base class."""

    def get_system_prompt(self) -> str:
        return "You are a test agent."

    def setup_tools(self) -> None:
        pass


@pytest.fixture
def agent():
    return _MinimalSubAgent(agent_id="test-agent", role="tester", llm_client=None)


@pytest.fixture
def state_with_ring(agent):
    state = KernelState(
        workflow_id="wf", step_id="s1", agent_id="test-agent", task="t",
    )
    state.internal_variables["_turn_results"] = {
        "3": "R" * 5000,
        "4": "short result",
    }
    agent._current_state = state
    return state


class TestClipObservation:

    def test_short_results_pass_through_unchanged(self):
        assert _clip_observation("small", turn=2) == "small"

    def test_exactly_at_limit_passes_through(self):
        text = "x" * _OBSERVATION_LIMIT
        assert _clip_observation(text, turn=2) == text

    def test_clipped_result_carries_marker_with_retrieval_call(self):
        text = "y" * (_OBSERVATION_LIMIT + 500)
        out = _clip_observation(text, turn=7)
        assert out.startswith("y" * _OBSERVATION_LIMIT)
        assert f"showing {_OBSERVATION_LIMIT} of {len(text)} chars" in out
        assert "read_turn_result" in out
        assert '"turn": 7' in out
        assert f'"offset": {_OBSERVATION_LIMIT}' in out


class TestReadTurnResult:

    def test_reads_retained_result_in_chunks(self, agent, state_with_ring):
        first = agent._tool_read_turn_result(turn=3, offset=0, length=2000)
        assert first["status"] == "success"
        assert first["output"] == "R" * 2000
        assert first["total_chars"] == 5000
        assert first["remaining_chars"] == 3000
        assert '"offset": 2000' in first["note"]

        rest = agent._tool_read_turn_result(turn=3, offset=2000, length=3000)
        assert rest["output"] == "R" * 3000
        assert rest["remaining_chars"] == 0
        assert "note" not in rest

    def test_full_read_of_short_result(self, agent, state_with_ring):
        out = agent._tool_read_turn_result(turn=4)
        assert out["status"] == "success"
        assert out["output"] == "short result"
        assert out["remaining_chars"] == 0

    def test_unknown_turn_is_an_honest_error(self, agent, state_with_ring):
        out = agent._tool_read_turn_result(turn=99)
        assert out["status"] == "error"
        assert "No retained result for turn 99" in out["error"]
        assert "'3'" in out["error"] and "'4'" in out["error"]

    def test_no_state_is_an_honest_error(self, agent):
        agent._current_state = None
        out = agent._tool_read_turn_result(turn=1)
        assert out["status"] == "error"

    def test_window_constant_is_positive(self):
        assert _TURN_RESULT_WINDOW >= 1


class TestToolRegistration:

    def test_read_turn_result_is_auto_registered(self, agent):
        assert "read_turn_result" in agent.tool_names

    def test_read_turn_result_is_a_thinking_tool(self):
        assert "read_turn_result" in THINKING_TOOLS
