"""Custom scopes: an agent working for a person does only what that person may do in their organisation."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarviscore import OnBehalfOf, act_for
from jarviscore.auth import principal
from jarviscore.control import effects
from jarviscore.control import policy as policy_module
from jarviscore.control import scopes as s
from jarviscore.control.approvals import (
    ApprovalRule, Approver, check_approver, requirement_for, sign_assertion, verify_assertion,
)
from jarviscore.control.policy import PolicyDenied, check_policy
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import Journal, verify
from jarviscore.nexus import call_proxy as proxy_module
from jarviscore.nexus.call_proxy import NexusCallProxy
from jarviscore.nexus.models import DynamicStrategy
from test_delegated_authority import Client

ERP = "https://erp.example.test"
POLICY = {"scopes": {
    "require": [
        {"name": "claim-approval", "match": {"provider": "erp", "atom": "erp_approve_claim"},
         "requires": "claims.approve",
         "limits": [{"field": "json.amount", "kind": "money", "at_most": "amount"}]},
        {"name": "claim-payment", "match": {"provider": "erp", "atom": "erp_pay_claim"},
         "requires": "claims.pay", "approved_by": "claims.approve",
         "limits": [{"field": "json.amount", "kind": "money", "at_most": "amount"}]},
        {"name": "sar-recipients", "match": {"provider": "erp", "atom": "erp_send_sar"},
         "requires": "fincrime.sar.send",
         "limits": [{"field": "json.to", "kind": "email", "one_of": "recipients"}]},
        {"name": "finance-reports", "match": {"provider": "erp", "method": "GET", "path": "/reports/financial/{id}"},
         "requires": "finance.reports.read"},
        {"name": "finance-portal", "match": {"sink": "browser", "target": "finance.acme.test/*"},
         "requires": "finance.reports.read"},
    ],
    "grants": {"acme/erin": {"finance.reports.read": {}}, "acme/carol": {"claims.approve": {"amount": "500"}}},
    "unattended": {"finance.reports.read": {}},
}}
CAROL = OnBehalfOf.of("acme", "carol", scopes={
    "claims.vet": {}, "claims.approve": {"amount": "10000"}, "claims.pay": {"amount": "*"},
    "fincrime.sar.send": {"recipients": ["mlro@acme.test"]},
})
DAVE = OnBehalfOf.of("acme", "dave", scopes=["claims.vet"])


def authority(atom, effect="write", **more):
    return {"workflow_id": "wf", "step_id": "s1", "atom": atom, "effect": effect,
            "code_origin": "shipped", "action_id": f"op-{atom}", **more}


@pytest.fixture
def broker(monkeypatch, tmp_path):
    def configure(mode="report", document=POLICY):
        path = tmp_path / "policy.json"
        path.write_text(json.dumps(document))
        monkeypatch.setenv("JARVISCORE_CONTROL_MODE", mode)
        monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(path))
        monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
        monkeypatch.setattr(policy_module, "_cached", None)
        monkeypatch.setattr(journal_module, "_journal", None)
        client = Client()
        Client.sent = []
        monkeypatch.setattr(proxy_module, "_pooled_client", lambda: client)
        auth = SimpleNamespace(
            _connections={"erp": "conn-erp"}, _strategy_cache={}, nexus_client=None,
            resolve_strategy=AsyncMock(return_value=DynamicStrategy(
                type="api_key", credentials={"api_key": "k"},
                config={"instance_url": ERP, "header_name": "X-Key"})),
        )
        return NexusCallProxy(auth), auth, str(tmp_path / "journal")
    return configure


def decisions(root):
    with open(Journal(root).run_path("wf/s1"), encoding="utf-8") as handle:
        return [json.loads(line)["data"] for line in handle if '"policy.decision"' in line]


async def approve(proxy, amount, **more):
    return await proxy.call("conn-erp", "POST", f"{ERP}/claims/7/approve", json={"amount": amount},
                            authority=authority("erp_approve_claim", **more))


# ── Grants and requirements ───────────────────────────────────────────────


def test_a_grant_is_scope_names_with_their_terms_and_a_bad_one_is_refused_where_it_is_written():
    assert s.parse_grant(["claims.vet"]) == {"claims.vet": {}}
    assert s.parse_grant({"claims.approve": {"amount": "10000"}, "x": None}) == {
        "claims.approve": {"amount": "10000"}, "x": {}}
    for bad in ("claims.vet", {"has space": {}}, {"claims.approve": 10000}, {"": {}}):
        with pytest.raises(s.ScopeError):
            s.parse_grant(bad)
    with pytest.raises(s.ScopeError):
        OnBehalfOf.of("acme", "carol", scopes={"claims.approve": "10000"})
    assert CAROL.scopes["claims.approve"] == {"amount": "10000"}


@pytest.mark.parametrize("entry, problem", [
    ({"requires": "x"}, "match is a non-empty mapping"),
    ({"match": {"atom": "a", "sink": "browser"}, "requires": "x"}, "not both"),
    ({"match": {"colour": "red"}, "requires": "x"}, "match takes"),
    ({"match": {"atom": "a"}}, "requires, approved_by or both"),
    ({"match": {"sink": "browser"}, "approved_by": "x"}, "approved_by applies to provider calls"),
    ({"match": {"atom": "a"}, "requires": "x", "limits": [{"field": "json.to", "kind": "text", "at_most": "n"}]},
     "at_most compares money or number"),
    ({"match": {"atom": "a"}, "requires": "x", "limits": [{"field": "json.a", "one_of": "r", "equals": "q"}]},
     "a limit is"),
    ({"match": {"atom": "a"}, "requires": "has space"}, "requires is a scope name"),
])
def test_a_requirement_that_cannot_be_read_says_why(entry, problem):
    assert problem in s.parse_requirement(entry, 0).invalid


def test_policy_check_names_every_scope_problem_before_deployment(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"scopes": {"require": [
        {"name": "ok", "match": {"atom": "a"}, "requires": "x"},
        {"name": "broken", "match": {"atom": "b"}},
        {"name": "everything"},
    ], "grants": {"acme/x": {"bad name": {}}}}}))
    problems, summary = check_policy(str(path))
    text = " | ".join(problems)
    assert "'broken' cannot be read" in text and "the calls it matches" in text
    assert "'everything' cannot be read" in text and "every call and effect" in text
    assert "scopes.grants['acme/x']" in text
    assert summary["scopes"] == 3
    path.write_text(json.dumps(POLICY))
    assert check_policy(str(path))[0] == []


# ── At the broker ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_person_does_what_their_scope_allows_and_is_refused_beyond_it_even_in_report_mode(broker):
    proxy, auth, root = broker("report")

    with act_for(CAROL):
        assert (await approve(proxy, "4000"))["ok"]
        with pytest.raises(PolicyDenied, match="beyond what acme/carol may do under claims.approve") as over:
            await approve(proxy, "40000")
    with act_for(DAVE):
        with pytest.raises(PolicyDenied, match="acme/dave does not hold claims.approve") as missing:
            await approve(proxy, "10")

    assert (over.value.decision.rule, missing.value.decision.rule) == ("over-scope-limit", "scope-missing")
    assert len(Client.sent) == 1 and Client.sent[0]["json"] == {"amount": "4000"}
    assert auth.resolve_strategy.await_count == 1  # refused calls never reached for a credential
    allowed, beyond, absent = decisions(root)
    assert allowed["scope"]["allowed"] and allowed["scope"]["requirements"] == ["claim-approval"]
    assert allowed["scope"]["checks"][0]["limits"][0]["outcome"] == "within"
    assert beyond["outcome"] == "deny" and beyond["enforced"] and beyond["rule"] == "over-scope-limit"
    assert "40000" not in json.dumps(beyond)  # the record names the limit, never the value
    assert absent["acting_for"] == "acme/dave" and absent["scope"]["checks"][0]["held"] is False
    assert verify(root).ok


@pytest.mark.asyncio
async def test_a_limit_the_grant_does_not_state_is_refused_and_star_means_no_limit(broker):
    proxy, _, _ = broker("report")
    with act_for(OnBehalfOf("acme/eve", scopes={"claims.approve": {}})):
        with pytest.raises(PolicyDenied, match="without stating its 'amount'"):
            await approve(proxy, "1")
    with act_for(OnBehalfOf("acme/fay", scopes={"claims.approve": {"amount": "*"}})):
        assert (await approve(proxy, "99999999"))["ok"]


@pytest.mark.asyncio
async def test_a_value_the_request_does_not_carry_or_that_cannot_be_read_is_refused(broker):
    proxy, _, _ = broker("report")
    with act_for(CAROL):
        with pytest.raises(PolicyDenied, match="does not carry json.amount"):
            await proxy.call("conn-erp", "POST", f"{ERP}/claims/7/approve", json={"total": "1"},
                             authority=authority("erp_approve_claim"))
        with pytest.raises(PolicyDenied, match="body cannot be read"):
            await proxy.call("conn-erp", "POST", f"{ERP}/claims/7/approve", content=b'{"amount": 1}',
                             authority=authority("erp_approve_claim"))
        with pytest.raises(PolicyDenied, match="is not a number"):
            await approve(proxy, "ten thousand")


@pytest.mark.asyncio
async def test_a_report_goes_only_to_the_people_the_scope_names_every_one_of_them(broker):
    proxy, _, _ = broker("report")

    async def send(to):
        return await proxy.call("conn-erp", "POST", f"{ERP}/sar", json={"to": to},
                                authority=authority("erp_send_sar", effect="notify"))

    with act_for(CAROL):
        assert (await send("mlro@ACME.TEST"))["ok"]  # domains compare case-insensitively, local parts exactly
        with pytest.raises(PolicyDenied):
            await send("MLRO@acme.test")
        with pytest.raises(PolicyDenied, match="erp_send_sar|json.to"):
            await send("journalist@news.test")
        with pytest.raises(PolicyDenied):
            await send(["mlro@acme.test", "journalist@news.test"])
    with act_for(DAVE):
        with pytest.raises(PolicyDenied, match="does not hold fincrime.sar.send"):
            await send("mlro@acme.test")


@pytest.mark.asyncio
async def test_reads_need_their_scope_too_and_work_for_no_one_holds_only_unattended(broker):
    proxy, _, _ = broker("report")

    async def report():
        return await proxy.call("conn-erp", "GET", f"{ERP}/reports/financial/q3",
                                authority=authority("erp_get_report", effect="read"))

    with act_for(DAVE):
        with pytest.raises(PolicyDenied, match="does not hold finance.reports.read"):
            await report()
    with act_for("acme/erin"):  # no grant from the application: the policy's grants hold
        assert (await report())["ok"]
    assert (await report())["ok"]  # work for no one: scopes.unattended
    with act_for(DAVE):  # calls no requirement matches are as before
        assert (await proxy.call("conn-erp", "GET", f"{ERP}/claims/7",
                                 authority=authority("erp_get_claim", effect="read")))["ok"]


@pytest.mark.asyncio
async def test_the_application_is_authoritative_for_every_scope_it_names(broker):
    proxy, _, _ = broker("report")
    # The policy file grants acme/carol claims.approve up to 500; the application says 10000.
    with act_for(CAROL):
        assert (await approve(proxy, "4000"))["ok"]
    with act_for("acme/carol"):  # without the application's grant, the policy's limit holds
        with pytest.raises(PolicyDenied, match="beyond"):
            await approve(proxy, "4000")


@pytest.mark.asyncio
async def test_a_mandate_narrows_the_persons_scopes_for_one_piece_of_work_and_never_widens_them(broker):
    proxy, _, _ = broker("report")
    with act_for(CAROL, {"scopes": ["claims.vet"]}):
        with pytest.raises(PolicyDenied, match="the mandate does not include it"):
            await approve(proxy, "10")
    with act_for(DAVE, {"scopes": ["claims.approve"]}):
        with pytest.raises(PolicyDenied, match="does not hold claims.approve"):
            await approve(proxy, "10")


@pytest.mark.asyncio
async def test_no_deployment_rule_gives_a_person_a_scope(broker):
    document = {**POLICY, "rules": [{"name": "anything", "decision": "allow", "match": {"provider": "erp"}}]}
    proxy, _, _ = broker("strict", document)
    with act_for(DAVE):
        with pytest.raises(PolicyDenied) as refused:
            await approve(proxy, "10")
    assert refused.value.decision.rule == "scope-missing"


@pytest.mark.asyncio
async def test_without_a_scopes_section_nothing_changes(broker):
    proxy, _, root = broker("report", {})
    with act_for(DAVE):
        assert (await approve(proxy, "40000"))["ok"]
    assert "scope" not in decisions(root)[0]


@pytest.mark.asyncio
async def test_off_means_off(broker):
    proxy, _, _ = broker("off")
    with act_for(DAVE):
        assert (await approve(proxy, "40000"))["ok"]


@pytest.mark.asyncio
async def test_scopes_that_cannot_be_read_refuse_rather_than_allow(broker):
    proxy, _, _ = broker("report", {"scopes": {"require": [{"name": "everything"}]}})
    with act_for(CAROL):
        with pytest.raises(PolicyDenied, match="cannot be read"):
            await proxy.call("conn-erp", "GET", f"{ERP}/claims/7", authority=authority("erp_get_claim", effect="read"))
    proxy, _, _ = broker("report", {"scopes": "everyone may do anything"})
    with pytest.raises(PolicyDenied, match="cannot be read"):
        await proxy.call("conn-erp", "GET", f"{ERP}/claims/7", authority=authority("erp_get_claim", effect="read"))


# ── Doing and authorising ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_payment_needs_an_approver_who_holds_the_scope_within_its_limit(broker):
    proxy, _, root = broker("report")

    async def pay(amount, approver=None, preview=None):
        return await proxy.call("conn-erp", "POST", f"{ERP}/claims/7/pay", json={"amount": amount},
                                authority=authority("erp_pay_claim", approval="b1", approval_required=True,
                                                    approver=approver, **({"preview": preview} if preview is not None else {})))

    carol = Approver("acme/carol", scopes=CAROL.scopes).holder()
    with act_for(DAVE.person, held={"claims.pay": {"amount": "*"}}):
        with pytest.raises(PolicyDenied, match="needs the approval of someone who holds claims.approve"):
            await pay("100")
        assert (await pay("4000", carol))["ok"]
        with pytest.raises(PolicyDenied, match=r"the approver \(acme/carol\)"):
            await pay("40000", carol)
        with pytest.raises(PolicyDenied, match=r"approver \(acme/zed\) does not hold claims.approve"):
            await pay("1", {"subject": "acme/zed", "scopes": {}})
        # A preview is decided as it will be once approved: who approves is what is being asked.
        noted = []
        with pytest.raises(policy_module.PreviewHeld):
            await pay("4000", preview=noted)
        assert noted[0]["outcome"] == "allow"
    with act_for(DAVE):  # Dave may not pay at all, whoever approves
        with pytest.raises(PolicyDenied, match="does not hold claims.pay"):
            await pay("1", carol)
    refused = [d for d in decisions(root) if d["outcome"] == "deny"]
    assert [d["rule"] for d in refused] == ["scope-missing", "over-scope-limit", "scope-missing", "scope-missing"]


def test_an_approved_by_scope_requires_an_approval_from_someone_known_to_hold_it():
    section = s.parse_section(POLICY["scopes"])
    waived = [ApprovalRule(name="waive", match={"atom": "erp_pay_claim"}, require="none")]
    needed = requirement_for(provider="erp", atom="erp_pay_claim", effect="write",
                             integration_requires=False, rules=waived, scopes=section)
    assert needed.required and needed.scopes == ("claims.approve",) and needed.assurance == "asserted"
    plain = requirement_for(provider="erp", atom="erp_get_claim", effect="read",
                            integration_requires=False, scopes=section)
    assert not plain.required and plain.scopes == ()

    grants = section.grants
    assert check_approver(needed, Approver("acme/carol", assurance="asserted"), grants=grants) is None
    assert "does not" in check_approver(needed, Approver("acme/zed", assurance="asserted"), grants=grants)
    assert check_approver(needed, Approver("acme/zed", assurance="asserted",
                                           scopes={"claims.approve": {"amount": "1"}}), grants=grants) is None
    # A bare name proves nothing about what someone holds.
    assert "asserted approver" in check_approver(needed, Approver("acme/carol"), grants=grants)


def test_a_signed_approval_carries_the_approvers_scopes():
    token = sign_assertion("key", subject="acme/carol", decision="approved", workflow_id="wf",
                           action_id="a1", binding="b1", scopes={"claims.approve": {"amount": "10000"}})
    who = verify_assertion(token, {"default": "key"}, workflow_id="wf", action_id="a1",
                           binding="b1", decision="approved")
    assert who.scopes == {"claims.approve": {"amount": "10000"}} and who.assurance == "verified"
    assert Approver.from_record(who.as_record()).scopes == who.scopes
    assert "approver_scopes" not in Approver("x").as_record()  # records without scopes are as before


# ── Every other effect ────────────────────────────────────────────────────


def test_a_browser_page_the_person_may_not_open_is_refused_even_in_report_mode(broker):
    broker("report")
    page = effects.Effect("browser", "navigate", target="finance.acme.test/reports/q3", origin="page")
    with act_for(DAVE):
        decision = effects.decide(page)
        assert not decision.allowed and decision.enforced and decision.rule == "scope-missing"
        with pytest.raises(effects.EffectDenied):
            with effects.mediated(page, workflow_id="wf", step_id="s1"):
                pass
    with act_for("acme/erin"):
        assert effects.decide(page).allowed
    with act_for(DAVE):
        assert effects.decide(effects.Effect("browser", "navigate", target="news.test/", origin="page")).allowed


def test_the_browser_is_intercepted_wherever_a_scope_may_need_to_refuse(broker):
    from jarviscore.control.browser_requests import _scoped

    broker("report")
    assert _scoped(policy_module.current_policy())
    broker("report", {"scopes": {"require": [POLICY["scopes"]["require"][0]]}})
    assert not _scoped(policy_module.current_policy())  # provider-call scopes only: observed, as before


# ── Whom it is for, wherever the work goes ────────────────────────────────


def test_work_for_bob_inside_work_for_ada_never_keeps_adas_mandate_or_scopes():
    with act_for(OnBehalfOf("ada", {"systems": ["erp"]}, {"claims.approve": {"amount": "*"}})):
        with act_for("bob"):
            assert principal.acting_for.get() == "bob"
            assert principal.mandate.get() is None and principal.scopes.get() is None
        assert principal.scopes.get() == {"claims.approve": {"amount": "*"}}
        with act_for(None, {"systems": []}):  # narrowing the current work keeps its person
            assert principal.acting_for.get() == "ada" and principal.scopes.get() is not None
    assert principal.registered() is None


def test_scopes_travel_with_the_work_and_only_from_the_application():
    from jarviscore.core.mesh import Mesh, _with_principal

    with act_for(CAROL):
        assert principal.registered()["scopes"] == CAROL.scopes
    merged = _with_principal({"region": "eu"}, CAROL)
    assert merged["scopes"] == CAROL.scopes and Mesh._scopes({"context": merged}) == CAROL.scopes
    with pytest.raises(ValueError, match="disagree"):
        _with_principal({"scopes": {"claims.approve": {"amount": "*"}}}, CAROL)


def test_what_a_person_can_never_do_is_not_offered_to_the_agent():
    section = s.parse_section(POLICY["scopes"])
    dave = s.person_holder(section, DAVE.person, DAVE.scopes)
    carol = s.person_holder(section, CAROL.person, CAROL.scopes)
    assert s.out_of_reach(section, dave, "erp", "erp_approve_claim", "write") == "claims.approve"
    assert s.out_of_reach(section, carol, "erp", "erp_approve_claim", "write") is None
    # Whether a report read needs its scope depends on the path, so the read stays offered.
    assert s.out_of_reach(section, dave, "erp", "erp_get_report", "read") is None
    assert s.out_of_reach(s.Scopes(), dave, "erp", "erp_approve_claim", "write") is None


def test_the_coder_offers_only_what_the_person_may_do(broker):
    from jarviscore.kernel.defaults.coder import CoderSubAgent

    broker("report")
    atom = SimpleNamespace(system="erp", name="erp_approve_claim", policy=SimpleNamespace(effect="write"))
    with act_for(DAVE):
        assert CoderSubAgent._scope_out_of_reach(atom) == "claims.approve"
    with act_for(CAROL):
        assert CoderSubAgent._scope_out_of_reach(atom) is None


def test_the_cli_shows_who_may_do_what(tmp_path):
    import subprocess
    import sys
    import os

    path = tmp_path / "policy.json"
    path.write_text(json.dumps(POLICY))
    shown = subprocess.run([sys.executable, "-m", "jarviscore.cli", "policy", "scopes", str(path)],
                           capture_output=True, text=True, env={**os.environ, "PYTHONPATH": os.getcwd()})
    assert shown.returncode == 0, shown.stderr
    assert "the person needs claims.pay; an approver needs claims.approve" in shown.stdout
    assert "json.amount (money) at most the grant's 'amount'" in shown.stdout
    assert "acme/erin: finance.reports.read" in shown.stdout


@pytest.mark.asyncio
async def test_a_requirement_on_the_operation_holds_whatever_code_reaches_it(broker):
    document = {"scopes": {"require": [{
        "name": "claim-approval", "match": {"provider": "erp", "method": "POST", "path": "/claims/{id}/approve"},
        "requires": "claims.approve", "limits": [{"field": "json.amount", "kind": "money", "at_most": "amount"}],
    }]}}
    proxy, _, _ = broker("report", document)
    with act_for(DAVE):
        for origin in ({"atom": "erp_approve_claim", "code_origin": "shipped"},
                       {"atom": "my_own_approver", "code_origin": "model"},
                       {"atom": None, "code_origin": "direct"}):
            with pytest.raises(PolicyDenied, match="does not hold claims.approve"):
                await proxy.call("conn-erp", "POST", f"{ERP}/claims/7/approve", json={"amount": "1"},
                                 authority={**authority("x"), **origin})
    with act_for(CAROL):
        assert (await proxy.call("conn-erp", "POST", f"{ERP}/claims/7/approve", json={"amount": "1"},
                                 authority={**authority("x"), "atom": None, "code_origin": "direct"}))["ok"]


def test_scopes_view_warns_where_a_requirement_holds_only_one_integration(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / "policy.json"
    path.write_text(json.dumps(POLICY))
    shown = subprocess.run([sys.executable, "-m", "jarviscore.cli", "policy", "scopes", str(path)],
                           capture_output=True, text=True, env={**os.environ, "PYTHONPATH": os.getcwd()})
    assert "claim-approval" in shown.stdout and "only calls from that integration" in shown.stdout


def test_an_integration_whose_every_operation_needs_a_scope_is_not_offered(broker):
    from jarviscore.execution.atom_contract import read_contract
    from jarviscore.kernel.defaults.coder import CoderSubAgent
    from test_approval_authority import PAY

    broker("report", {"scopes": {"require": [{
        "name": "payments", "match": {"provider": "erp", "method": "POST", "path": "/payments"},
        "requires": "payments.make"}]}})
    atom = read_contract(PAY, system="erp", expected_name="erp_pay_invoice").atom
    with act_for(DAVE):
        assert CoderSubAgent._scope_out_of_reach(atom, PAY) == "payments.make"
        assert CoderSubAgent._scope_out_of_reach(atom) is None  # operations unknown: offered, the broker decides
    with act_for(OnBehalfOf("acme/payer", scopes=["payments.make"])):
        assert CoderSubAgent._scope_out_of_reach(atom, PAY) is None


def test_only_the_actions_whose_operations_match_wait_for_an_approved_by_approver():
    from jarviscore.control.operations import read_operations
    from test_approval_authority import PAY

    section = s.parse_section({"require": [{
        "name": "payments", "match": {"provider": "erp", "method": "POST", "path": "/payments"},
        "requires": "payments.make", "approved_by": "payments.approve"}]})
    read = read_operations('async def erp_get(i: str) -> dict:\n'
                           '    """Get."""\n'
                           '    return await nexus_call("GET", f"https://erp.example.test/invoices/{i}")\n', "erp_get")
    pay = read_operations(PAY, "erp_pay_invoice")
    assert read.verified and pay.verified
    assert section.for_approval("erp", "erp_get", "read", read.operations) == ()
    assert section.for_approval("erp", "erp_pay_invoice", "write", pay.operations) == ("payments.approve",)
    # Operations unknown: it waits for an approver, rather than being refused when it runs.
    assert section.for_approval("erp", "erp_unknown", "write") == ("payments.approve",)
    plain = requirement_for(provider="erp", atom="erp_get", effect="read", integration_requires=False,
                            scopes=section, operations=read.operations)
    assert not plain.required


@pytest.mark.asyncio
async def test_a_capability_the_person_may_not_use_is_shown_as_refused_and_never_run(broker):
    from jarviscore.execution.atom_contract import read_contract
    from jarviscore.kernel.defaults.coder import CoderSubAgent
    from test_approval_authority import PAY

    _, _, root = broker("report", {"scopes": {"require": [{
        "name": "payments", "match": {"provider": "erp", "method": "POST", "path": "/payments"},
        "requires": "payments.make"}]}})
    atom = read_contract(PAY, system="erp", expected_name="erp_pay_invoice").atom
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._tools, agent._run_context = {}, {"workflow_id": "wf", "step_id": "s1"}
    agent.code_registry = SimpleNamespace(get_function_code=lambda name: PAY)
    agent._valid_atoms = lambda system: {atom.name: atom}
    agent._log = SimpleNamespace(info=lambda *a, **k: None)
    registered = {}
    agent.register_tool = lambda name, fn, description, **kw: registered.__setitem__(name, (fn, description))

    with act_for(DAVE):
        agent._offer_system_capabilities_for(["erp"])
        fn, description = registered["erp_pay_invoice"]
        assert atom.name not in agent._atoms  # nothing can run it
        assert description.startswith("OUT OF REACH for this person (needs the scope payments.make)")
        result = await fn(invoice_id="INV-1", amount=10.0)
    assert result["semantic_error"] == "SCOPE_MISSING" and result["performed"] is False
    assert "Do not do anything else in its place" in result["error"]
    refused = decisions(root)[0]
    assert (refused["rule"], refused["outcome"], refused["enforced"], refused["acting_for"]) == (
        "scope-missing", "deny", True, "acme/dave")
    assert verify(root).ok

    registered.clear()
    with act_for(OnBehalfOf("acme/payer", scopes=["payments.make"])):
        agent._offer_system_capabilities_for(["erp"])
    assert atom.name in agent._atoms and not registered["erp_pay_invoice"][1].startswith("OUT OF REACH")


@pytest.mark.asyncio
async def test_a_deployment_deny_rule_never_softens_a_persons_refusal_in_report_mode(broker):
    document = {**POLICY, "rules": [{"name": "preview-no-writes", "decision": "deny",
                                     "match": {"provider": "erp", "effect": "write"}}],
                "effects": [{"name": "preview-no-browser", "decision": "deny", "match": {"sink": "browser"}}]}
    proxy, _, _ = broker("report", document)
    with act_for(DAVE):
        with pytest.raises(PolicyDenied) as refused:
            await approve(proxy, "10")
        page = effects.Effect("browser", "navigate", target="finance.acme.test/q3", origin="page")
        decision = effects.decide(page)
    assert refused.value.decision.rule == "scope-missing" and refused.value.decision.enforced
    assert decision.rule == "scope-missing" and decision.enforced
    assert not Client.sent
    with act_for(CAROL):  # within her scope, the deployment's rule is report-only as before
        assert (await approve(proxy, "10"))["ok"]


@pytest.mark.parametrize("path", [
    "/claims/7/approve", "//claims/7/approve", "/claims/7/./approve", "/claims/x/../7/approve",
    "/claims/7/%61pprove", "/claims/7/approve;jsessionid=1", "/claims%2F7/approve", "/CLAIMS/7/APPROVE",
    "/claims/7/approve/",
])
@pytest.mark.asyncio
async def test_a_path_a_server_reads_as_the_operation_is_held_to_its_scope(broker, path):
    document = {"scopes": {"require": [{
        "name": "claim-approval", "match": {"provider": "erp", "method": "POST", "path": "/claims/{id}/approve"},
        "requires": "claims.approve"}]}}
    proxy, _, _ = broker("report", document)
    with act_for(DAVE):
        with pytest.raises(PolicyDenied, match="does not hold claims.approve"):
            await proxy.call("conn-erp", "POST", f"{ERP}{path}", json={"amount": "1"},
                             authority={**authority("x"), "atom": "my_own", "code_origin": "registry"})


def test_grounding_matches_the_same_readings():
    from jarviscore.control.grounding import normalized_path, parse_rule, request_from

    rule = parse_rule({"name": "pay", "match": {"provider": "erp", "method": "POST", "path": "/payments"},
                       "bind": [], "require": []}, 0)
    for path in ("/payments", "//payments", "/./payments", "/%70ayments", "/payments;x=1"):
        assert rule.applies("erp", None, request_from("POST", f"{ERP}{path}", {})), path
    assert normalized_path("/a//b/./c/../d;m=1/%7Ee") == "/a/b/d/~e"


def test_a_policy_refusal_names_the_system_that_never_saw_it():
    from jarviscore.control.policy import Decision, PolicyDenied

    decision = Decision(allowed=False, rule="over-scope-limit", reason="amount is beyond the limit", enforced=True)
    message = str(PolicyDenied(decision, "claims_hub"))
    assert message.startswith("Your organisation's policy refused this call, so nothing was sent")
    assert "Claims Hub never received it" in message and "not Claims Hub, that refused" in message
