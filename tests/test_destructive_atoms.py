from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.atom_contract import read_contract
from jarviscore.kernel.defaults.coder import CoderSubAgent


SOURCE = '''
ATOM_POLICY = {
    "effect": "destructive",
    "approval": "required",
    "idempotency_fields": ["message_id"],
    "consequence": "Permanently deletes the message.",
}
async def gmail_delete_message(message_id: str) -> dict:
    """Delete one message."""
    return await nexus_call("DELETE", f"https://example.test/messages/{message_id}")
'''


class Registry:
    def get_function_code(self, name):
        return SOURCE

    def update_execution_stats(self, *args, **kwargs):
        pass


class ExecutionStore:
    def __init__(self):
        self.results = {}

    def get_atom_execution(self, action_id):
        return self.results.get(action_id)

    def save_atom_execution(self, action_id, result):
        self.results[action_id] = result


def test_http_delete_without_policy_is_rejected():
    source = '''
async def demo_delete_item(item_id: str) -> dict:
    """Delete one item."""
    return await nexus_call("DELETE", f"https://example.test/{item_id}")
'''
    contract = read_contract(source, system="demo", expected_name="demo_delete_item")
    assert not contract.ok
    assert "require a destructive ATOM_POLICY" in contract.report()


def test_idempotency_fields_must_name_parameters():
    invalid = SOURCE.replace('["message_id"]', '["missing_id"]')
    contract = read_contract(invalid, system="gmail", expected_name="gmail_delete_message")
    assert not contract.ok
    assert "must name parameters" in contract.report()


@pytest.mark.asyncio
async def test_approval_precedes_execution_and_retry_is_idempotent():
    atom = read_contract(
        SOURCE, system="gmail", expected_name="gmail_delete_message"
    ).atom
    assert atom is not None
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry()
    agent.redis_store = ExecutionStore()
    agent._tool_execute_code = AsyncMock(
        return_value={"status": "success", "data": {"deleted": True}}
    )
    call = agent._atom_tool(atom.name)

    waiting = await call(message_id="m-1")
    assert waiting["typed_outcome"] == "WAITING_FOR_APPROVAL"
    assert waiting["consequence"] == "Permanently deletes the message."
    agent._tool_execute_code.assert_not_awaited()

    agent._run_context["_approved_actions"] = [waiting["action_id"]]
    first = await call(message_id="m-1")
    retry = await call(message_id="m-1")

    assert first == retry
    agent._tool_execute_code.assert_awaited_once()
