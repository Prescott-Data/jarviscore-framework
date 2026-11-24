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
    _RESULT_INLINE_LIMIT,
    _RESULT_PREVIEW,
    _as_it_arrives,
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


class TestSearchTurnResult:

    @pytest.fixture
    def minutes(self, agent, state_with_ring):
        lines = [f"line {n}: nothing to report" for n in range(200)]
        lines[50] = "line 50: the Board approved the budget"
        lines[120] = "line 120: the BOARD deferred the hire"
        text = "\n".join(lines)
        _retain_turn_result(state_with_ring.internal_variables, 5, text)
        return text

    def test_a_match_comes_with_its_offset_and_two_lines_either_side(self, agent, minutes):
        out = agent._tool_search_turn_result(turn=5, query="board")

        assert out["status"] == "success"
        assert out["total_matches"] == 2 and out["total_chars"] == len(minutes)
        first, second = out["matches"]
        assert minutes[first["offset"]:first["offset"] + 5] == "Board"
        assert minutes[second["offset"]:second["offset"] + 5] == "BOARD"
        assert first["context"].split("\n") == [
            "line 48: nothing to report", "line 49: nothing to report",
            "line 50: the Board approved the budget",
            "line 51: nothing to report", "line 52: nothing to report",
        ]
        # The offset is one read_turn_result reads on from.
        page = agent._tool_read_turn_result(turn=5, offset=second["offset"], length=14)
        assert page["output"] == "BOARD deferred"

    def test_matches_at_either_end_have_the_lines_there_are(self, agent, minutes):
        assert agent._tool_search_turn_result(turn=5, query="line 0:")["matches"][0]["context"] == (
            "line 0: nothing to report\nline 1: nothing to report\nline 2: nothing to report"
        )
        last = agent._tool_search_turn_result(turn=5, query="LINE 199")["matches"][0]["context"]
        assert last.split("\n")[-1] == "line 199: nothing to report" and last.count("\n") == 2

    def test_at_most_twenty_matches_and_the_whole_count(self, agent, minutes):
        out = agent._tool_search_turn_result(turn=5, query="nothing to report")

        assert out["total_matches"] == 198
        assert len(out["matches"]) == 20
        assert "the first 20 of 198 matches" in out["note"]

    def test_the_query_is_plain_text_not_a_pattern(self, agent, state_with_ring):
        _retain_turn_result(state_with_ring.internal_variables, 5, "cost (net): 4.5\ncost gross: 495")

        out = agent._tool_search_turn_result(turn=5, query="(net): 4.5")

        assert out["total_matches"] == 1 and out["matches"][0]["offset"] == 5
        assert agent._tool_search_turn_result(turn=5, query="4.5|495")["total_matches"] == 0

    def test_a_result_without_line_breaks_gives_bounded_context(self, agent, state_with_ring):
        _retain_turn_result(state_with_ring.internal_variables, 5, "a" * 30_000 + "needle" + "b" * 30_000)

        match = agent._tool_search_turn_result(turn=5, query="needle")["matches"][0]

        assert match["offset"] == 30_000
        assert "needle" in match["context"] and len(match["context"]) < 1000

    def test_a_turn_not_retained_is_answered_as_read_turn_result_answers(self, agent, state_with_ring):
        state_with_ring.internal_variables["_released_turn_results"] = {"1": "it was old"}
        for turn in (1, 99):
            assert agent._tool_search_turn_result(turn=turn, query="x") == (
                agent._tool_read_turn_result(turn=turn)
            )
        assert "Retained turns: ['3', '4']" in agent._tool_search_turn_result(turn=99, query="x")["error"]

    def test_an_empty_query_is_an_error(self, agent, state_with_ring):
        assert agent._tool_search_turn_result(turn=3, query=" ")["status"] == "error"

    def test_a_search_fits_the_view(self, agent, state_with_ring):
        _retain_turn_result(state_with_ring.internal_variables, 5, "needle " * 100_000)

        out = agent._tool_search_turn_result(turn=5, query="needle")

        assert len(str(out)) < _READ_PAGE_LIMIT


class TestALongResultArrivesAsAPreview:

    def test_a_result_within_the_limit_is_untouched(self):
        text = "y" * _RESULT_INLINE_LIMIT
        assert _as_it_arrives(text, text, 7) is text

    def test_a_longer_result_is_previewed_with_its_size_and_how_to_read_on(self):
        text = "".join(f"row {n}\n" for n in range(5000))

        shown = _as_it_arrives(text, text, 7)

        assert shown.startswith(text[:_RESULT_PREVIEW] + "\n\n[PARTIAL RESULT: ")
        assert f"the first {_RESULT_PREVIEW} characters are shown above" in shown
        assert f"The whole result is {len(text)} characters" in shown
        assert f'read_turn_result with {{"turn": 7, "offset": {_RESULT_PREVIEW}}}' in shown
        assert 'search_turn_result with {"turn": 7, "query": "<text to find>"}' in shown

    def test_a_result_retained_in_another_form_is_read_from_its_start(self):
        text = "z" * 50_000

        shown = _as_it_arrives(text, "something else entirely", 7)

        assert 'read_turn_result with {"turn": 7}, which reads the retained copy from its start' in shown

    def test_no_limit_shows_every_result_whole(self):
        text = "y" * 50_000
        assert _as_it_arrives(text, text, 7, inline_limit=0) is text

    def test_the_defaults_are_the_settings(self):
        from jarviscore.config.settings import Settings

        assert Settings.model_fields["kernel_result_inline_limit"].default == 20000
        assert Settings.model_fields["kernel_result_preview"].default == 4000

    def test_the_kernel_hands_its_configured_limits_to_its_subagents(self):
        from unittest.mock import MagicMock

        from jarviscore.kernel.kernel import Kernel

        kernel = Kernel(
            llm_client=MagicMock(),
            config={"kernel_result_inline_limit": 9000, "kernel_result_preview": 500},
        )
        subagent = kernel._create_subagent("researcher", "a1")
        assert (subagent.result_inline_limit, subagent.result_preview) == (9000, 500)

        plain = Kernel(llm_client=MagicMock(), config={})._create_subagent("researcher", "a1")
        assert (plain.result_inline_limit, plain.result_preview) == (None, None)


class TestToolRegistration:

    def test_search_turn_result_is_registered_and_is_recall_not_action(self, agent):
        assert "search_turn_result" in agent.tool_names
        assert "search_turn_result" in THINKING_TOOLS

    def test_read_turn_result_is_auto_registered(self, agent):
        assert "read_turn_result" in agent.tool_names

    def test_read_turn_result_is_a_thinking_tool(self):
        assert "read_turn_result" in THINKING_TOOLS
