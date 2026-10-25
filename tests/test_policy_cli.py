"""`jarviscore policy check` names what a deployment would silently refuse; `review` what strict would."""
import json

import pytest

from jarviscore.control import policy as policy_module
from jarviscore.control.effects import Effect, mediated
from jarviscore.control.policy import check_policy, review_journal
from jarviscore.evidence import journal as journal_module

GOOD = {
    "rules": [{"name": "no-deletes", "decision": "deny", "match": {"method": "DELETE"}}],
    "approvals": [{"name": "payments", "match": {"effect": "write"}, "roles": ["finance"], "assurance": "verified"}],
    "principals": {"carol": ["finance"]},
    "grounding": [{
        "name": "pay", "match": {"provider": "erp", "method": "POST", "path": "/payments"},
        "bind": [{"name": "invoice", "read": {"provider": "erp", "path": "/invoices/{id}"},
                  "where": {"id": "request.json.invoice"}}],
        "require": [{"field": "request.json.amount", "at_most": "invoice.amount_due", "as": "money"}],
    }],
    "effects": [{"name": "quiet", "decision": "deny", "match": {"sink": "peer", "action": "broadcast"}}],
}


def write(tmp_path, document, name="policy.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document))
    return str(path)


def test_a_policy_that_reads_as_written_has_no_problems(tmp_path):
    problems, summary = check_policy(write(tmp_path, GOOD))

    assert problems == []
    assert summary == {"rules": 1, "approvals": 1, "principals": 1, "grounding": 1, "effects": 1}


@pytest.mark.parametrize("change, problem", [
    ({"effect": []}, "Unknown section 'effect'"),
    ({"rules": [{"name": "r", "decision": "block", "match": {}}]}, "treated as deny"),
    ({"rules": [{"name": "r", "decision": "deny", "match": {"host": "x"}}]}, "never applies"),
    ({"approvals": [{"name": "a", "assurance": "strong"}]}, "assurance must be"),
    ({"approvals": [{"name": "a", "role": ["x"]}]}, "unknown keys"),
    ({"grounding": [{**GOOD["grounding"][0], "require": [{"field": "iban", "equals": "invoice.iban"}]}]}, "the calls it matches are refused"),
    ({"effects": [{"name": "e", "decision": "deny", "match": {"kind": "peer"}}]}, "every effect would be refused"),
])
def test_every_rule_a_deployment_would_silently_refuse_on_is_named(tmp_path, change, problem):
    problems, _ = check_policy(write(tmp_path, {**GOOD, **change}))

    assert any(problem in p for p in problems), problems


def test_an_unreadable_file_is_named(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text("rules: [unclosed")

    problems, _ = check_policy(str(path))

    assert "refuses every call and effect" in problems[0]


def test_review_groups_what_strict_mode_would_refuse_with_what_to_do(monkeypatch, tmp_path):
    path = write(tmp_path, {})
    monkeypatch.setenv("JARVISCORE_CONTROL_MODE", "report")
    monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", path)
    monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
    monkeypatch.setattr(policy_module, "_cached", None)
    monkeypatch.setattr(journal_module, "_journal", None)
    send = Effect("browser", "send", target="tracker.test/collect", origin="page",
                  attributes={"host": "tracker.test", "page": "shop.test"})
    for _ in range(3):
        with mediated(send, workflow_id="wf", step_id="s1"):
            pass
    with mediated(Effect("code", "run", origin="model", attributes={"confined": False}), workflow_id="wf", step_id="s1"):
        pass

    groups = review_journal(str(tmp_path / "journal"))

    assert [(g["rule"], g["count"], g["state"]) for g in groups] == [
        ("browser-send-off-site", 3, "would refuse"), ("unconfined-execution", 1, "would refuse"),
    ]
    assert 'target: "<host>/*"' in groups[0]["remedy"] and groups[0]["target"] == "tracker.test/collect"
