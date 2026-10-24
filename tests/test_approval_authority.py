"""Who may approve: the institution's policy decides, the approver is checked, and execution is claimed once."""
import json
import time
from unittest.mock import AsyncMock

import pytest

from jarviscore.auth.principal import act_for
from jarviscore.control import policy as policy_module
from jarviscore.control.approvals import (
    ApprovalRefused,
    ApprovalRequirement,
    ApprovalRule,
    Approver,
    check_approver,
    requirement_for,
    sign_assertion,
    verify_assertion,
)
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import verify
from jarviscore.execution.atom_contract import read_contract
from jarviscore.kernel import approval
from jarviscore.kernel.defaults.coder import CoderSubAgent
from jarviscore.testing.mocks import MockRedisContextStore

KEY = "a-long-random-assertion-key"

PAY = '''
ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["invoice_id"],
    "consequence": "Pays the supplier for the invoice.",
}
async def erp_pay_invoice(invoice_id: str, amount: float) -> dict:
    """Pay one invoice."""
    return await nexus_call("POST", "https://erp.example.test/payments", json={"invoice": invoice_id, "amount": amount})
'''

POLICY = {
    "approvals": [{
        "name": "payments-need-finance",
        "match": {"provider": "erp", "effect": "write"},
        "roles": ["finance_approver"],
        "distinct_from": ["requester"],
        "assurance": "verified",
    }],
    "principals": {"carol@bank.example": ["finance_approver"]},
}


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    def configure(policy=POLICY):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(policy))
        monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(path))
        monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
        monkeypatch.setenv("APPROVAL_ASSERTION_KEY", KEY)
        monkeypatch.setattr(policy_module, "_cached", None)
        monkeypatch.setattr(journal_module, "_journal", None)
        monkeypatch.setattr(approval, "assertion_keys", lambda: {"default": KEY})
        return str(tmp_path / "journal")
    return configure


class Registry:
    def get_function_code(self, name):
        return PAY

    def update_execution_stats(self, *args, **kwargs):
        pass


def payer():
    atom = read_contract(PAY, system="erp", expected_name="erp_pay_invoice").atom
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry()
    agent.redis_store = MockRedisContextStore()
    agent._tool_execute_code = AsyncMock(return_value={"status": "success", "data": {"paid": True}})
    return agent, agent._atom_tool(atom.name)


async def ask(pay, requester="alice@bank.example", **args):
    with act_for(requester):
        return await pay(invoice_id="INV-1", amount=10.0, **args)


def assertion(waiting, subject, decision="approve", roles=("finance_approver",), **extra):
    return sign_assertion(
        KEY, subject=subject, decision=decision, workflow_id="wf",
        action_id=waiting["action_id"], binding=waiting["binding"], roles=roles, **extra,
    )


# ── Requirements: the institution decides ─────────────────────────────────


def test_a_deployment_requires_approval_where_the_integration_does_not():
    rule = ApprovalRule(name="crm", match={"provider": "hubspot"}, roles=("sales_lead",))

    required = requirement_for(provider="hubspot", atom="hubspot_create_deal", effect="write",
                               integration_requires=False, rules=[rule])

    assert required.required and required.roles == ("sales_lead",) and required.rule == "deployment:crm"


def test_a_deployment_may_waive_approval_except_for_a_destructive_action():
    waive = ApprovalRule(name="trusted", match={"provider": "gmail"}, require="none")

    write = requirement_for(provider="gmail", atom="gmail_send", effect="notify", integration_requires=True, rules=[waive])
    delete = requirement_for(provider="gmail", atom="gmail_delete", effect="destructive", integration_requires=True, rules=[waive])

    assert not write.required
    assert delete.required


def test_without_a_rule_the_integration_decides():
    assert requirement_for(provider="x", atom="a", effect="write", integration_requires=True).required
    assert not requirement_for(provider="x", atom="a", effect="write", integration_requires=False).required


# ── Who may approve ───────────────────────────────────────────────────────


REQUIREMENT = ApprovalRequirement(required=True, roles=("finance_approver",), distinct_from=("requester",), assurance="verified")


def test_an_approver_needs_the_role_the_assurance_and_not_to_be_the_requester():
    carol = Approver("carol@bank.example", frozenset({"finance_approver"}), "verified", "assertion:default")

    assert check_approver(REQUIREMENT, carol, requester="alice@bank.example") is None
    assert "roles" in check_approver(REQUIREMENT, Approver("bob", frozenset(), "verified"), requester="alice")
    assert "verified" in check_approver(REQUIREMENT, Approver("carol@bank.example", frozenset({"finance_approver"}), "asserted"))
    assert "may not also approve" in check_approver(REQUIREMENT, carol, requester="carol@bank.example")


def test_roles_can_come_from_the_deployment_directory():
    carol = Approver("carol@bank.example", frozenset(), "verified")

    assert check_approver(REQUIREMENT, carol, directory={"carol@bank.example": ["finance_approver"]}) is None


def test_with_nothing_required_of_the_approver_any_decision_stands():
    assert check_approver(ApprovalRequirement(required=True), None) is None


# ── Assertions ────────────────────────────────────────────────────────────


def signed(**changes):
    fields = dict(subject="carol@bank.example", decision="approve", workflow_id="wf",
                  action_id="a1", binding="b" * 64, roles=["finance_approver"])
    fields.update(changes)
    return sign_assertion(KEY, **fields)


def check(token, **expected):
    fields = dict(workflow_id="wf", action_id="a1", binding="b" * 64, decision="approve")
    fields.update(expected)
    return verify_assertion(token, {"default": KEY}, **fields)


def test_an_assertion_proves_the_approver_for_that_exact_action():
    approver = check(signed())

    assert approver.subject == "carol@bank.example"
    assert approver.assurance == "verified" and "finance_approver" in approver.roles


@pytest.mark.parametrize("token, expected, reason", [
    (lambda: sign_assertion("another-key", subject="c", decision="approve", workflow_id="wf",
                            action_id="a1", binding="b" * 64), {}, "signature"),
    (lambda: signed(), {"binding": "c" * 64}, "another action"),
    (lambda: signed(), {"action_id": "a2"}, "another action"),
    (lambda: signed(decision="reject"), {}, "different decision"),
    (lambda: signed(issued_at=time.time() - 3600), {}, "stale"),
    (lambda: signed(key_id="old"), {}, "does not hold"),
])
def test_an_assertion_proves_nothing_when(token, expected, reason):
    with pytest.raises(ApprovalRefused, match=reason):
        check(token(), **expected)


def test_a_tampered_assertion_proves_nothing():
    version, body, signature = signed().split(".")
    import base64

    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["sub"] = "mallory"
    forged_body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()

    with pytest.raises(ApprovalRefused, match="signature"):
        check(f"{version}.{forged_body}.{signature}")


# ── End to end through the gate ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_institution_requires_approval_for_a_write_the_integration_allows(deployment):
    deployment()
    agent, pay = payer()

    waiting = await ask(pay)

    assert waiting["typed_outcome"] == "WAITING_FOR_APPROVAL"
    agent._tool_execute_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unauthenticated_or_self_approval_is_refused_and_recorded(deployment):
    root = deployment()
    agent, pay = payer()
    waiting = await ask(pay)

    with pytest.raises(ApprovalRefused, match="verified"):
        approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "approve",
                                 resolved_by="carol@bank.example")
    with pytest.raises(ApprovalRefused, match="may not also approve"):
        approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "approve",
                                 assertion=assertion(waiting, "alice@bank.example"))

    assert (await ask(pay))["typed_outcome"] == "WAITING_FOR_APPROVAL"
    agent._tool_execute_code.assert_not_awaited()
    kinds = [json.loads(line)["kind"] for line in open(f"{root}/runs/wf_step.jsonl")]
    assert kinds.count("approval.refused") == 2


@pytest.mark.asyncio
async def test_a_verified_finance_approver_lets_it_run_once(deployment):
    root = deployment()
    agent, pay = payer()
    waiting = await ask(pay)

    approver = approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "approve",
                                        assertion=assertion(waiting, "carol@bank.example", roles=()))
    first = await ask(pay)
    again = await ask(pay)

    assert approver.assurance == "verified" and approver.subject == "carol@bank.example"
    assert first["status"] == "success" and "already ran" in again["note"]
    agent._tool_execute_code.assert_awaited_once()
    events = [json.loads(line) for line in open(f"{root}/runs/wf_step.jsonl")]
    assert [e["kind"] for e in events] == [
        "approval.request", "approval.decision", "approval.claim", "approval.settle",
    ]
    assert events[1]["data"]["approver"] == "carol@bank.example"
    assert verify(root).ok


@pytest.mark.asyncio
async def test_anyone_may_decline(deployment):
    deployment()
    agent, pay = payer()
    waiting = await ask(pay)

    approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "reject", resolved_by="intern")

    assert (await ask(pay))["semantic_error"] == "ACTION_DECLINED"


@pytest.mark.asyncio
async def test_a_tightened_policy_reopens_an_approval_that_no_longer_qualifies(deployment):
    deployment({"approvals": [{"name": "pay", "match": {"provider": "erp"}}]})
    agent, pay = payer()
    waiting = await ask(pay)
    approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "approve", resolved_by="bob")

    deployment()  # now finance approvers only, verified
    again = await ask(pay)

    assert again["typed_outcome"] == "WAITING_FOR_APPROVAL"
    assert "verified" in again["detail"]
    agent._tool_execute_code.assert_not_awaited()
    assert agent.redis_store.get_hitl_request("wf", "step", waiting["action_id"])["status"] == "pending"


# ── Claimed once; an interrupted run is reconciled, never retried blindly ──


@pytest.mark.asyncio
async def test_an_action_interrupted_while_running_is_not_run_again(deployment):
    deployment({"approvals": [{"name": "pay", "match": {"provider": "erp"}}]})
    agent, pay = payer()
    waiting = await ask(pay)
    approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "approve", resolved_by="bob")
    agent._tool_execute_code.side_effect = RuntimeError("the worker died mid-call")

    with pytest.raises(RuntimeError):
        await ask(pay)
    agent._tool_execute_code.side_effect = None

    unknown = await ask(pay)

    assert unknown["semantic_error"] == "OUTCOME_UNKNOWN"
    assert agent._tool_execute_code.await_count == 1


@pytest.mark.asyncio
async def test_reconciling_as_not_performed_lets_it_run_once_more(deployment):
    deployment({"approvals": [{"name": "pay", "match": {"provider": "erp"}}]})
    agent, pay = payer()
    waiting = await ask(pay)
    approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "approve", resolved_by="bob")
    agent._tool_execute_code.side_effect = RuntimeError("timeout")
    with pytest.raises(RuntimeError):
        await ask(pay)
    agent._tool_execute_code.side_effect = None

    approval.reconcile(agent.redis_store, "wf", "step", waiting["action_id"], performed=False, resolved_by="ops")
    ran = await ask(pay)

    assert ran["status"] == "success"
    assert agent._tool_execute_code.await_count == 2


@pytest.mark.asyncio
async def test_reconciling_as_performed_records_what_happened(deployment):
    deployment({"approvals": [{"name": "pay", "match": {"provider": "erp"}}]})
    agent, pay = payer()
    waiting = await ask(pay)
    approval.record_decision(agent.redis_store, "wf", "step", waiting["action_id"], "approve", resolved_by="bob")
    agent._tool_execute_code.side_effect = RuntimeError("timeout")
    with pytest.raises(RuntimeError):
        await ask(pay)
    agent._tool_execute_code.side_effect = None

    approval.reconcile(agent.redis_store, "wf", "step", waiting["action_id"], performed=True,
                       outcome={"status": "success", "data": {"paid": True, "ref": "PAY-9"}}, resolved_by="ops")
    after = await ask(pay)

    assert "already ran" in after["note"] and after["data"]["ref"] == "PAY-9"
    assert agent._tool_execute_code.await_count == 1


def test_only_an_unknown_outcome_can_be_reconciled():
    store = MockRedisContextStore()
    from jarviscore.contracts.hitl import HITLAction, HITLRequest

    store.create_hitl_request_typed(HITLRequest(workflow_id="wf", step_id="s", action=HITLAction(
        action_id="a", tool="t", consequence="c")))

    with pytest.raises(ValueError, match="unknown"):
        approval.reconcile(store, "wf", "s", "a", performed=True)


# ── The broker holds a call that needs approval to carrying one ─────────────


def test_the_broker_refuses_a_call_that_needs_approval_and_carries_none():
    from jarviscore.control.policy import ControlPolicy, ProviderCall

    call = ProviderCall(provider="erp", method="POST", url="https://erp.example.test/payments",
                        atom="erp_pay_invoice", declared_effect="write", code_origin="shipped",
                        approval_required=True)

    decision = ControlPolicy(mode="strict").decide(call)

    assert decision.rule == "approval-missing" and not decision.allowed


def test_verify_flags_a_call_whose_approval_is_not_in_the_record(tmp_path):
    from jarviscore.evidence.journal import Journal

    journal = Journal(str(tmp_path))
    journal.append("wf/step", "policy.decision", {"call_id": "c", "outcome": "allow", "approval": "d" * 64})
    journal.append("wf/step", "effect.attempt", {"call_id": "c"})

    assert any("no approval of that exact action" in p for p in verify(str(tmp_path)).problems)
