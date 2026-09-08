"""A human wait resumes the same OODA state without replaying earlier actions."""

import json

import pytest

from jarviscore.kernel.state import KernelState
from jarviscore.kernel.subagent import BaseSubAgent


class QueueLLM:
    def __init__(self, responses):
        self.responses = list(responses)

    async def generate(self, **kwargs):
        return {
            "content": self.responses.pop(0),
            "tokens": {"input": 10, "output": 10, "total": 20},
            "cost_usd": 0.0,
        }


class CheckpointMemory:
    def __init__(self):
        self.checkpoint = None

    async def save_checkpoint(self, state_json):
        self.checkpoint = state_json

    async def load_checkpoint(self):
        return self.checkpoint

    async def log_turn(self, **kwargs):
        pass


class WaitingAgent(BaseSubAgent):
    calls = 0

    def setup_tools(self):
        pass

    def get_system_prompt(self):
        return "Wait for access when needed."

    async def _tool_request_access(self, system: str):
        type(self).calls += 1
        return {
            "status": "waiting", "hitl_required": True, "hitl_type": "auth",
            "typed_outcome": "WAITING_FOR_CONSENT", "system": system,
            "connection_id": "conn-1", "workflow_id": "wf-1", "step_id": "step-1",
            "detail": "Waiting for Gmail access.",
        }


@pytest.mark.asyncio
async def test_resume_starts_after_the_waiting_turn():
    WaitingAgent.calls = 0
    memory = CheckpointMemory()
    first = WaitingAgent(
        agent_id="mail-agent", role="coder",
        llm_client=QueueLLM([
            'THOUGHT: Need Gmail\nTOOL: request_access\nPARAMS: {"system": "gmail"}',
        ]),
    )
    context = {"workflow_id": "wf-1", "step_id": "step-1"}
    yielded = await first.run("process my mailbox", context=context, memory=memory)

    assert yielded.status == "yield"
    assert yielded.metadata["typed_outcome"] == "WAITING_FOR_CONSENT"
    saved = KernelState.model_validate_json(memory.checkpoint)
    assert saved.status == "waiting"
    assert saved.turn == 1
    assert saved.tool_history[-1].tool_name == "request_access"
    assert WaitingAgent.calls == 1

    second = WaitingAgent(
        agent_id="mail-agent", role="coder",
        llm_client=QueueLLM([
            'THOUGHT: Access is approved; continue\nDONE: Mailbox processed.\n'
            'RESULT: {"processed": true}',
        ]),
    )
    resumed = await second.run(
        "process my mailbox",
        context=context | {"_resume": True, "system": "gmail"},
        memory=memory,
    )

    assert resumed.status == "success"
    assert resumed.payload == {"processed": True}
    assert resumed.trajectory[0]["turn"] == 1
    assert WaitingAgent.calls == 1, "the consent tool must not replay"
