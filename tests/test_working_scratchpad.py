"""The working scratchpad is the agent's: it writes what it established and reads it every turn."""

import asyncio

from jarviscore.context.context_manager import BudgetConfig, ContextManager
from jarviscore.kernel.state import KernelState
from jarviscore.kernel.subagent import BaseSubAgent


class _Agent(BaseSubAgent):
    def __init__(self):
        super().__init__(agent_id="a1", role="browser", llm_client=None)

    def setup_tools(self):
        pass

    def get_system_prompt(self):
        return ""


class _Pad:
    def __init__(self):
        self.writes = []

    async def write(self, entry_type, data, scope="step"):
        self.writes.append((entry_type, data, scope))


def _state(**kwargs):
    return KernelState(workflow_id="wf", step_id="s1", agent_id="a1", task="order groceries", **kwargs)


def test_a_note_rides_along_with_an_action_and_reaches_the_scratchpad_and_view():
    reply = (
        "THOUGHT: Sauce checked, now rice\n"
        "NOTE: Sweet chilli sauce 350g: £1.20, no peanuts (product page)\n"
        "NOTE: Basmati 1kg is out of stock\n"
        "TOOL: navigate\nPARAMS: {\"url\": \"http://shop/search?q=rice\"}"
    )
    parsed = BaseSubAgent._parse_response(reply)
    assert parsed["type"] == "tool" and parsed["tool"] == "navigate"
    assert parsed["thought"] == "Sauce checked, now rice"
    assert parsed["notes"] == ["Sweet chilli sauce 350g: £1.20, no peanuts (product page)", "Basmati 1kg is out of stock"]

    agent = _Agent()
    agent._current_state = _state(turn=7)
    pad = _Pad()
    agent._current_memory = type("Memory", (), {"working": pad})()
    asyncio.run(agent._keep_notes(agent._current_state, parsed["notes"]))

    assert pad.writes[0] == ("note", {"content": "Sweet chilli sauce 350g: £1.20, no peanuts (product page)", "turn": 7}, "step")
    assert [n["note"] for n in agent._current_state.working_notes] == parsed["notes"]


def test_a_tools_own_notes_field_is_not_mistaken_for_the_agents():
    reply = 'THOUGHT: fill it\nTOOL: fill_form\nPARAMS: {"fields": [], "notes": "leave at door"}'
    assert "notes" not in BaseSubAgent._parse_response(reply)
    json_reply = '{"thought": "t", "notes": ["Promo needs a weekday"], "tool": "snapshot", "params": {}}'
    assert BaseSubAgent._parse_response(json_reply)["notes"] == ["Promo needs a weekday"]


def test_notes_work_without_a_blob_store():
    agent = _Agent()
    agent._current_state = _state()
    agent._current_memory = None

    asyncio.run(agent._keep_notes(agent._current_state, ["Basket holds 4 items"]))

    assert agent._current_state.working_notes == [{"turn": 0, "note": "Basket holds 4 items"}]


def test_notes_are_shown_every_turn_even_under_the_heaviest_pressure():
    state = _state(working_notes=[{"turn": 3, "note": "Brown basmati 1kg £2.30 is in stock"}])
    state.context = {"previous_step_results": {"big": "x " * 400_000}}
    view = ContextManager(BudgetConfig(total_tokens=20_000)).build_context(state)

    assert "## MY WORKING NOTES" in view
    assert "- [3] Brown basmati 1kg £2.30 is in stock" in view
    assert state.internal_variables["context_pressure"]["tier"] != "normal"
    from jarviscore.context.pressure import PressureTier, should_render_block

    assert should_render_block("working_notes", PressureTier.RECOVERY)


def test_notes_survive_a_checkpoint_into_the_next_epoch():
    state = _state(working_notes=[{"turn": 12, "note": "Promo WEEKDAY10 needs a weekday slot"}])

    restored = KernelState.model_validate_json(state.model_dump_json())

    assert restored.working_notes == state.working_notes


def test_the_agent_is_told_what_it_forgets_and_how_to_keep_it():
    # Registered but unexplained, the tool went unused in 15 live runs.
    prompt = _Agent()._build_system_prompt()

    assert "Your memory:" in prompt and "last 10 exchanges" in prompt
    assert "NOTE: line" in prompt and "costs no turn" in prompt


def test_every_turns_decision_contract_asks_for_notes_not_a_thought_that_scrolls_away():
    # The contract had the agent restate KNOWN in its THOUGHT each turn and never
    # mentioned notes; with notes available it still wrote none in a live run.
    turn = _Agent()._build_user_prompt(_state(turn=3), "## MISSION")

    assert "Write anything newly established on NOTE: lines" in turn
    assert "my working notes and findings above" in turn
