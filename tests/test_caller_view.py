"""What application code receives: the answer, with the tool observations beside it."""

import pytest

from jarviscore import Mesh
from jarviscore.core.envelope import caller_view
from jarviscore.profiles import CustomAgent

OBSERVED = {"tool_name": "write_code", "tool_input": {"code": "x = 1"}, "tool_output": {"rows": 400}}


def _stored():
    output = {
        "tool_receipt_id": "tool:wf:s:1",
        "regions": {"South": 22127.22},
        "observed_tool_result": OBSERVED,
        "items": [{"tool_receipt_id": "tool:wf:s:2", "observed_tool_result": {"tool_name": "read"}}],
    }
    return {"status": "success", "output": output, "payload": output, "result_summary": "South grew most."}


def test_the_answer_is_what_the_agent_delivered_and_the_observations_move_whole():
    stored = _stored()

    view = caller_view(stored)

    assert view["output"] == {"tool_receipt_id": "tool:wf:s:1", "regions": {"South": 22127.22},
                              "items": [{"tool_receipt_id": "tool:wf:s:2"}]}
    assert view["payload"] == view["output"]
    assert view["evidence"] == [
        {"tool_receipt_id": "tool:wf:s:1", **OBSERVED},
        {"tool_receipt_id": "tool:wf:s:2", "tool_name": "read"},
    ]
    assert view["result_summary"] == "South grew most."
    assert stored["output"]["observed_tool_result"] == OBSERVED


def test_a_result_without_observations_has_empty_evidence():
    result = {"status": "failure", "output": None, "error": "no file"}

    assert caller_view(result) == {**result, "evidence": []}
    assert caller_view("plain") == "plain"


class Reporter(CustomAgent):
    role = "reporter"
    capabilities = ["report"]

    async def execute_task(self, task):
        return _stored()


@pytest.mark.asyncio
async def test_run_task_and_workflow_return_the_callers_view():
    mesh = Mesh(config={"p2p_enabled": False})
    mesh.add(Reporter)
    await mesh.start()
    try:
        single = await mesh.run_task(agent="reporter", task="report")
        steps = await mesh.workflow("wf-view", [{"agent": "reporter", "task": "report"}])
        raw = await mesh.delegate(to="reporter", task="report")
    finally:
        await mesh.stop()

    for result in (single, steps[0]):
        assert "observed_tool_result" not in str(result["output"])
        assert result["evidence"][0]["tool_input"] == {"code": "x = 1"}
    assert raw["output"]["observed_tool_result"] == OBSERVED
