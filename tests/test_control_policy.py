"""The decision on a provider call: what is refused, by which rule, and only when enforced."""
import json

import pytest

from jarviscore.control.operations import read_operations
from jarviscore.control.policy import ControlPolicy, ProviderCall, Rule, _load_rules

ISSUES = '''
async def github_create_issue(owner: str, repo: str, title: str) -> dict:
    return await nexus_call("POST", f"https://api.github.com/repos/{owner}/{repo}/issues", json={"title": title})
'''


def call(method="GET", url="https://api.github.com/repos/a/b/issues", **authority):
    return ProviderCall(provider="github", method=method, url=url, **authority)


def strict(*rules):
    return ControlPolicy(mode="strict", rules=tuple(rules))


def test_a_mutation_without_an_atom_is_refused():
    decision = strict().decide(call("POST"))

    assert not decision.allowed and decision.rule == "mutation-without-atom" and decision.enforced


def test_a_read_without_an_atom_is_allowed():
    assert strict().decide(call("GET")).allowed


def test_report_mode_decides_the_same_but_does_not_enforce():
    decision = ControlPolicy(mode="report").decide(call("POST"))

    assert not decision.allowed and not decision.enforced


def test_a_write_atom_may_not_delete():
    decision = strict().decide(call("DELETE", atom="github_create_issue", declared_effect="write",
                                    code_origin="shipped"))

    assert decision.rule == "beyond-declared-effect"


def test_a_shipped_read_may_post_but_model_written_code_may_not_without_a_verified_contract():
    shipped = strict().decide(call("POST", atom="lacrm_get_account", declared_effect="read", code_origin="shipped"))
    model = strict().decide(call("POST", atom="lacrm_get_account", declared_effect="read", code_origin="model"))

    assert shipped.allowed
    assert not model.allowed


def test_model_written_code_may_only_send_operations_its_own_code_names():
    contract = read_operations(ISSUES, "github_create_issue")
    inside = strict().decide(call("POST", atom="github_create_issue", declared_effect="write",
                                  code_origin="model", contract=contract))
    outside = strict().decide(call("POST", url="https://api.github.com/repos/a/b/collaborators",
                                   atom="github_create_issue", declared_effect="write",
                                   code_origin="model", contract=contract))

    assert inside.allowed
    assert outside.rule == "outside-contract"


def test_model_written_code_with_an_unverified_contract_may_not_mutate():
    contract = read_operations('async def x(url):\n    return await nexus_call("POST", url)\n', "x")
    decision = strict().decide(call("POST", atom="x", declared_effect="write", code_origin="model",
                                    contract=contract))

    assert decision.rule == "unverified-model-code"


def test_the_runtime_transport_may_notify():
    decision = strict().decide(ProviderCall(
        provider="slack", method="POST", url="https://slack.com/api/chat.postMessage",
        atom="room.slack", declared_effect="notify", code_origin="runtime",
    ))

    assert decision.allowed


def test_a_deployment_rule_refuses_more():
    policy = strict(Rule(name="no-github-writes", decision="deny", match={"provider": "github", "effect": "write"}))

    decision = policy.decide(call("POST", atom="github_create_issue", declared_effect="write", code_origin="shipped"))

    assert decision.rule == "deployment:no-github-writes"


def test_a_deployment_may_lift_only_the_atomless_mutation_refusal():
    lift = Rule(name="our-own-client", decision="allow", match={"provider": "github"})
    policy = strict(lift)

    assert policy.decide(call("POST")).allowed
    assert not policy.decide(call("DELETE", atom="github_create_issue", declared_effect="write",
                                  code_origin="shipped")).allowed


def test_an_unreadable_policy_refuses_everything(tmp_path):
    broken = tmp_path / "policy.json"
    broken.write_text("{not json")
    policy = strict(*_load_rules(str(broken)))

    assert not policy.decide(call("GET")).allowed


def test_rules_load_from_json(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"rules": [
        {"name": "no-deletes", "decision": "deny", "match": {"method": "DELETE"}},
        {"name": "typo", "decision": "permit", "match": {"provider": "x"}},
    ]}))

    rules = _load_rules(str(path))

    assert [(r.name, r.decision) for r in rules] == [("no-deletes", "deny"), ("typo", "deny")]


@pytest.mark.parametrize("mode", ["off", "report", "strict"])
def test_current_policy_reads_the_mode(monkeypatch, mode):
    from jarviscore.control import policy as policy_module

    monkeypatch.setenv("JARVISCORE_CONTROL_MODE", mode)
    monkeypatch.setattr(policy_module, "_cached", None)

    assert policy_module.current_policy().mode == mode
