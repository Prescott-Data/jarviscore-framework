"""
Tests for issue #57: observation channel integrity.

What these tests prove:
- Tool results are observed whole: nothing is clipped
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
    _TURN_RESULT_WINDOW,
    _observe,
    _READ_PAGE_LIMIT,
    _retain_turn_result,
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


class TestObservedWhole:

    def test_a_long_result_is_observed_whole(self):
        text = "y" * 50_000
        assert _observe("gmail_list_messages", text, turn=7) == text


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

    def test_a_large_listing_is_retained_whole_up_to_its_page_token(self, agent, state_with_ring):
        listing = str({"messages": [{"id": f"m{i}", "snippet": "s" * 400} for i in range(100)],
                       "next_page_token": "PAGE-2"})
        assert len(listing) > 40_000
        _retain_turn_result(state_with_ring.internal_variables, 5, listing)

        out = agent._tool_read_turn_result(turn=5, offset=0)
        pages = [out["output"]]
        while out["remaining_chars"]:
            out = agent._tool_read_turn_result(turn=5, offset=out["offset"] + len(out["output"]))
            pages.append(out["output"])

        assert out["total_chars"] == len(listing)
        assert "".join(pages) == listing
        assert listing.endswith("'next_page_token': 'PAGE-2'}")

    def test_an_old_turn_is_released_whole_and_the_agent_is_told_why(self, agent, state_with_ring):
        for turn in range(5, 5 + _TURN_RESULT_WINDOW):
            _retain_turn_result(state_with_ring.internal_variables, turn, f"result {turn}")

        out = agent._tool_read_turn_result(turn=3)

        assert out["status"] == "error"
        assert "was released because only the last" in out["error"]
        assert "repeat that call" in out["error"]

    def test_the_size_budget_releases_whole_older_turns_never_part_of_one(self, agent, monkeypatch):
        import jarviscore.kernel.subagent as subagent

        monkeypatch.setattr(subagent, "_TURN_RESULT_BUDGET", 1000)
        variables = {}
        _retain_turn_result(variables, 1, "a" * 600)
        _retain_turn_result(variables, 2, "b" * 600)
        _retain_turn_result(variables, 3, "c" * 5000)

        assert variables["_turn_results"] == {"3": "c" * 5000}
        assert "later results needed the room" in variables["_released_turn_results"]["1"]

    def test_a_read_page_is_shown_whole_and_sized_to_fit(self, agent, state_with_ring):
        _retain_turn_result(state_with_ring.internal_variables, 5, "L" * (_READ_PAGE_LIMIT * 3))

        page = agent._tool_read_turn_result(turn=5, offset=0, length=10**9)

        assert len(page["output"]) == _READ_PAGE_LIMIT
        assert page["remaining_chars"] == _READ_PAGE_LIMIT * 2
        assert _observe("read_turn_result", page, turn=6) == str(page)


class TestToolRegistration:

    def test_read_turn_result_is_auto_registered(self, agent):
        assert "read_turn_result" in agent.tool_names

    def test_read_turn_result_is_a_thinking_tool(self):
        assert "read_turn_result" in THINKING_TOOLS
