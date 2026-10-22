"""A step does not ask the roles that run after it for the work they are about to do."""

from types import SimpleNamespace

import pytest

from jarviscore import Mesh
from jarviscore.orchestration.engine import WorkflowEngine
from jarviscore.orchestration.envelopes import downstream_peer_refusal, neutral_context
from jarviscore.profiles import CustomAgent


def _peers(*entries):
    return SimpleNamespace(list_peers=lambda: [
        {"role": role, "capabilities": caps} for role, caps in entries
    ])


def test_a_role_that_runs_later_is_refused_with_the_reason():
    refusal = downstream_peer_refusal({"downstream_roles": ["analyst", "writer"]}, "analyst")

    assert refusal["status"] == "error"
    assert refusal["semantic_error"] == "PEER_RUNS_AFTER_YOU"
    assert "analyst runs after you" in refusal["error"]


def test_other_roles_and_steps_outside_a_workflow_are_not_affected():
    assert downstream_peer_refusal({"downstream_roles": ["writer"]}, "legal") is None
    assert downstream_peer_refusal({}, "analyst") is None
    assert downstream_peer_refusal(None, "analyst") is None


def test_a_capability_is_refused_only_when_every_holder_runs_later():
    later = _peers(("analyst", ["analysis"]))
    shared = _peers(("analyst", ["analysis"]), ("auditor", ["analysis"]))
    context = {"downstream_roles": ["analyst"]}

    assert downstream_peer_refusal(context, "analysis", later, by_capability=True)
    assert downstream_peer_refusal(context, "analysis", shared, by_capability=True) is None


def test_the_boundary_does_not_travel_to_the_peer():
    assert "downstream_roles" not in neutral_context({"downstream_roles": ["writer"], "topic": "x"})


def test_each_step_knows_every_role_that_consumes_its_result():
    engine = WorkflowEngine.__new__(WorkflowEngine)
    steps = [
        {"id": "s0", "agent": "scout"},
        {"id": "s1", "agent": "analyst", "depends_on": ["s0"]},
        {"id": "s2", "agent": "writer", "depends_on": ["s1"]},
        {"id": "s3", "agent": "scout", "depends_on": ["s0"]},
    ]

    assert engine._roles_after(steps) == {
        "s0": ["analyst", "writer"], "s1": ["writer"], "s2": [], "s3": [],
    }


class Recorder(CustomAgent):
    role = "scout"
    capabilities = ["web_research"]
    seen = []

    async def execute_task(self, task):
        Recorder.seen.append(task["context"].get("downstream_roles"))
        return {"status": "success", "output": "facts"}


class Writer(CustomAgent):
    role = "writer"
    capabilities = ["writing"]

    async def execute_task(self, task):
        return {"status": "success", "output": "brief"}


@pytest.mark.asyncio
async def test_a_workflow_step_is_told_who_runs_after_it():
    Recorder.seen = []
    mesh = Mesh(config={"p2p_enabled": False})
    mesh.add(Recorder)
    mesh.add(Writer)
    await mesh.start()
    try:
        await mesh.workflow("wf-after", [
            {"agent": "scout", "task": "gather"},
            {"agent": "writer", "task": "write", "depends_on": [0]},
        ])
    finally:
        await mesh.stop()

    assert Recorder.seen == [["writer"]]


@pytest.mark.asyncio
async def test_a_communicator_does_not_message_the_step_that_receives_its_result():
    from jarviscore.kernel.defaults import CommunicatorSubAgent
    from jarviscore.testing import MockLLMClient

    sent = []

    class Peers:
        async def notify(self, role, payload):
            sent.append(role)
            return True

    agent = CommunicatorSubAgent(agent_id="analyst-1", llm_client=MockLLMClient())
    agent.peers = Peers()
    agent._current_state = SimpleNamespace(context={"downstream_roles": ["writer"]})

    refused = await agent._tool_send_to_peer(peer_role="writer", message="Here is my comparison")
    delivered = await agent._tool_send_to_peer(peer_role="legal", message="Licence question")

    assert refused["semantic_error"] == "PEER_RUNS_AFTER_YOU"
    assert delivered["status"] == "sent"
    assert sent == ["legal"]
