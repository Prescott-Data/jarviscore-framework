"""An approval covers one exact operation, by an approver the policy accepts, and runs at most once."""
from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.atom_contract import read_contract
from jarviscore.kernel.defaults.coder import CoderSubAgent
from jarviscore.testing.mocks import MockRedisContextStore

PAY = '''
ATOM_POLICY = {
    "effect": "write",
    "approval": "required",
    "idempotency_fields": ["invoice_id"],
    "consequence": "Pays the supplier for the invoice.",
}
async def erp_pay_invoice(invoice_id: str, amount: float, iban: str) -> dict:
    """Pay one invoice."""
    return await nexus_call("POST", "https://erp.example.test/payments", json={
        "invoice": invoice_id, "amount": amount, "iban": iban,
    })
'''


class Registry:
    def get_function_code(self, name):
        return PAY

    def update_execution_stats(self, *args, **kwargs):
        pass


def payer():
    atom = read_contract(PAY, system="erp", expected_name="erp_pay_invoice").atom
    assert atom is not None
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry()
    agent.redis_store = MockRedisContextStore()
    agent._tool_execute_code = AsyncMock(return_value={"status": "success", "data": {"paid": True}})
    return agent, agent._atom_tool(atom.name)


@pytest.mark.asyncio
async def test_an_approval_does_not_cover_different_arguments_for_the_same_invoice():
    agent, pay = payer()

    waiting = await pay(invoice_id="INV-1", amount=10.0, iban="GB00 SAFE")
    agent.redis_store.resolve_hitl_request("wf", "step", "approve", action_id=waiting["action_id"])

    changed = await pay(invoice_id="INV-1", amount=10000.0, iban="GB00 ELSEWHERE")

    assert changed.get("typed_outcome") == "WAITING_FOR_APPROVAL"
    agent._tool_execute_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_approved_arguments_run_once():
    agent, pay = payer()

    waiting = await pay(invoice_id="INV-1", amount=10.0, iban="GB00 SAFE")
    agent.redis_store.resolve_hitl_request("wf", "step", "approve", action_id=waiting["action_id"])
    first = await pay(invoice_id="INV-1", amount=10.0, iban="GB00 SAFE")
    again = await pay(invoice_id="INV-1", amount=10.0, iban="GB00 SAFE")

    assert first["status"] == "success"
    assert "already ran" in again["note"]
    agent._tool_execute_code.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_operation_that_ran_is_not_run_again_with_other_arguments():
    agent, pay = payer()

    waiting = await pay(invoice_id="INV-1", amount=10.0, iban="GB00 SAFE")
    agent.redis_store.resolve_hitl_request("wf", "step", "approve", action_id=waiting["action_id"])
    await pay(invoice_id="INV-1", amount=10.0, iban="GB00 SAFE")

    # Paying the same invoice again, differently, would be a second payment.
    repeat = await pay(invoice_id="INV-1", amount=10000.0, iban="GB00 ELSEWHERE")

    assert "already ran" in repeat["note"]
    agent._tool_execute_code.assert_awaited_once()


@pytest.mark.asyncio
async def test_new_arguments_after_an_approval_ask_the_person_again_with_those_arguments():
    agent, pay = payer()

    waiting = await pay(invoice_id="INV-1", amount=10.0, iban="GB00 SAFE")
    agent.redis_store.resolve_hitl_request("wf", "step", "approve", action_id=waiting["action_id"])
    await pay(invoice_id="INV-1", amount=12.5, iban="GB00 SAFE")

    asked = agent.redis_store.get_hitl_request("wf", "step", waiting["action_id"])
    assert asked["status"] == "pending"
    assert asked["action"]["params"]["amount"] == 12.5


def test_the_first_decision_on_an_action_stands():
    agent, _ = payer()
    from jarviscore.contracts.hitl import HITLAction, HITLRequest

    action = HITLAction(action_id="a-1", tool="erp_pay_invoice", consequence="Pays.")
    agent.redis_store.create_hitl_request_typed(HITLRequest(workflow_id="wf", step_id="step", action=action))

    approved = agent.redis_store.resolve_hitl_action_once("wf", "step", "a-1", "approve", responder="ops")
    declined = agent.redis_store.resolve_hitl_action_once("wf", "step", "a-1", "reject", responder="other")

    assert (approved, declined) == (True, False)
    resolution = agent.redis_store.get_hitl_resolution("wf", "step", "a-1")
    assert resolution.is_approved and resolution.resolved_by == "ops"
    assert agent.redis_store.resolve_hitl_action_once("wf", "step", "missing", "approve") is None


def test_the_binding_ignores_rewording_but_not_arguments():
    from jarviscore.contracts.hitl import HITLAction

    base = HITLAction(action_id="a", tool="t", params={"x": 1}, consequence="Does it.")
    reworded = base.model_copy(update={"consequence": "Does the same thing.", "description": "again"})
    changed = base.model_copy(update={"params": {"x": 2}})

    assert base.binding_digest() == reworded.binding_digest()
    assert base.binding_digest() != changed.binding_digest()
