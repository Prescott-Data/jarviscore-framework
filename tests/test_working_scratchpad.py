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


def test_a_note_goes_to_the_step_scratchpad_and_the_agents_view():
    agent = _Agent()
    agent._current_state = _state(turn=7)
    pad = _Pad()
    agent._current_memory = type("Memory", (), {"working": pad})()

    result = asyncio.run(agent._tool_note("Sweet chilli sauce 350g: £1.20, no peanuts (product page)"))

    assert result["status"] == "success"
    assert pad.writes == [("note", {"content": "Sweet chilli sauce 350g: £1.20, no peanuts (product page)", "turn": 7}, "step")]
    assert agent._current_state.working_notes == [{"turn": 7, "note": "Sweet chilli sauce 350g: £1.20, no peanuts (product page)"}]


def test_notes_work_without_a_blob_store_and_refuse_nothing_written():
    agent = _Agent()
    agent._current_state = _state()
    agent._current_memory = None

    assert asyncio.run(agent._tool_note("Basket holds 4 items"))["status"] == "success"
    assert asyncio.run(agent._tool_note("   "))["status"] == "error"
    assert len(agent._current_state.working_notes) == 1


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
