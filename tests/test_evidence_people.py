"""Evidence per person and per tenant: what agents did for them, exported for their auditor."""
import json
import os
import subprocess
import sys

import pytest

from jarviscore import OnBehalfOf, act_for
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import Journal, verify
from jarviscore.evidence.people import account, erase, export
from jarviscore.evidence.replay import replay
from jarviscore.control import policy as policy_module
from test_replay import LedgerAgent, ScriptedLLM, SCRIPT


def decide(log, run, person, method="GET", outcome="allow", enforced=False, rule=None):
    log.append(run, "policy.decision", {
        "call_id": f"{run}-{method}", "host": "erp.example", "path": "/invoices", "method": method,
        "acting_for": person, "outcome": outcome, "enforced": enforced, "rule": rule,
    })
    if outcome == "allow":
        log.append(run, "effect.attempt", {"call_id": f"{run}-{method}"})


@pytest.fixture
def journal(monkeypatch, tmp_path):
    (tmp_path / "policy.json").write_text("{}")
    monkeypatch.setenv("JARVISCORE_CONTROL_MODE", "report")
    monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(tmp_path / "policy.json"))
    monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
    monkeypatch.setenv("JARVISCORE_JOURNAL_CAPTURE", "full")
    monkeypatch.setattr(policy_module, "_cached", None)
    monkeypatch.setattr(journal_module, "_journal", None)
    return str(tmp_path / "journal")


@pytest.fixture
def recorded(tmp_path):
    root = str(tmp_path / "journal")
    log = Journal(root)
    decide(log, "wf-1/a", "acme/u_1")
    decide(log, "wf-1/a", "acme/u_1", "POST", "deny", True, "outside-mandate")
    decide(log, "wf-2/a", "acme/u_2", "POST")
    decide(log, "wf-3/a", "globex/u_1")
    decide(log, "wf-4/a", "acme/u_1")
    decide(log, "wf-4/a", "globex/u_9")  # one run that worked for two tenants
    decide(log, "wf-5/a", None)
    log.close()
    return root


def test_the_account_of_a_person_is_every_run_done_for_them_and_nothing_else(recorded):
    mine = account(recorded, "acme/u_1")
    assert [r["run"] for r in mine] == ["wf-1/a", "wf-4/a"]
    first = mine[0]
    assert first["for"] == ["acme/u_1"] and not first["shared"]
    assert [(d["action"], d["outcome"], d["rule"]) for d in first["decisions"]] == [
        ("GET", "allow", None), ("POST", "deny", "outside-mandate")]
    assert first["refused"] == 1 and first["effects"] == 1
    assert mine[1]["shared"] is True
    assert account(recorded, "acme/u_") == []  # a prefix is not a person; a tenant ends in "/"


def test_the_account_of_a_tenant_covers_all_its_people_and_no_other_tenant(recorded):
    assert [r["run"] for r in account(recorded, "acme/")] == ["wf-1/a", "wf-2/a", "wf-4/a"]
    assert [r["run"] for r in account(recorded, "globex/")] == ["wf-3/a", "wf-4/a"]
    with pytest.raises(ValueError):
        account(recorded, " ")


def test_an_export_holds_the_tenants_runs_verifiable_on_their_own(recorded, tmp_path):
    out = str(tmp_path / "acme")
    manifest = export(recorded, "acme/", out)

    assert manifest["runs"] == ["wf-1/a", "wf-2/a"]
    assert manifest["left_out_shared"] == ["wf-4/a"]  # never hand one tenant another's work
    assert sorted(os.listdir(os.path.join(out, "runs"))) == ["wf-1_a.jsonl", "wf-2_a.jsonl"]
    report = verify(out, export=True)
    assert report.ok, report.problems
    assert report.runs == 2 and report.refused == 1
    assert any("an export for acme/" in note and "3 other run(s)" in note for note in report.notes)
    with pytest.raises(FileExistsError):
        export(recorded, "acme/", out)


def test_an_export_still_shows_tampering_and_a_run_it_claims_but_lacks(recorded, tmp_path):
    out = str(tmp_path / "acme")
    export(recorded, "acme/", out)
    run = os.path.join(out, "runs", "wf-1_a.jsonl")
    with open(run) as handle:
        text = handle.read()
    with open(run, "w") as handle:
        handle.write(text.replace('"deny"', '"allow"', 1))
    os.remove(os.path.join(out, "runs", "wf-2_a.jsonl"))

    problems = " | ".join(verify(out, export=True).problems)
    assert "does not match its hash" in problems
    assert "wf-2/a: listed in this export but its record is missing" in problems


def test_an_export_is_not_a_whole_journal_and_a_whole_journal_cannot_pass_as_one(recorded, tmp_path):
    out = str(tmp_path / "acme")
    export(recorded, "acme/", out)
    assert any("export.json" in p for p in verify(out).problems)

    # Whoever deletes a run from a whole journal cannot hide it by calling the journal an export.
    os.remove(os.path.join(recorded, "runs", "wf-3_a.jsonl"))
    with open(os.path.join(recorded, "export.json"), "w") as handle:
        json.dump({"for": "acme/", "runs": []}, handle)
    plain = verify(recorded)
    assert not plain.ok and any("export.json" in p for p in plain.problems)
    assert not verify(str(tmp_path / "absent"), export=True).ok


@pytest.mark.asyncio
async def test_a_run_records_whom_it_was_for_and_its_export_replays(journal, tmp_path):
    root = journal
    LedgerAgent.effects = []
    with act_for(OnBehalfOf.of("acme", "u_1")):
        agent = LedgerAgent(llm_client=ScriptedLLM(SCRIPT))
        await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})
    agent = LedgerAgent(llm_client=ScriptedLLM(SCRIPT))
    await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "other"})
    journal_module._journal.close()

    assert [r["run"] for r in account(root, "acme/u_1")] == ["wf/pay"]
    out = str(tmp_path / "export")
    manifest = export(root, "acme/u_1", out, content=True)
    assert manifest["runs"] == ["wf/pay"] and manifest["content"] > 0
    assert verify(out, export=True).ok

    LedgerAgent.effects = []
    report = await replay(out, "wf/pay")
    assert report.reproduced, report.divergence
    assert LedgerAgent.effects == []


def test_the_cli_lists_and_exports_a_persons_evidence(recorded, tmp_path):
    env = {**os.environ, "PYTHONPATH": os.getcwd()}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "jarviscore.cli", *args],
                              capture_output=True, text=True, env=env)

    listed = cli("evidence", "acme/u_1", recorded)
    assert listed.returncode == 0, listed.stderr
    assert "wf-1/a" in listed.stdout and "refused" in listed.stdout and "outside-mandate" in listed.stdout
    assert "wf-3/a" not in listed.stdout
    assert cli("evidence", "nobody/x", recorded).returncode == 2

    out = str(tmp_path / "out")
    exported = cli("evidence", "acme/", recorded, "--export", out)
    assert exported.returncode == 0 and "Left out 1 run(s)" in exported.stdout
    assert cli("verify", "--export", out).returncode == 0
    assert cli("verify", out).returncode == 1


@pytest.mark.asyncio
async def test_erasing_a_persons_content_keeps_the_journal_verifiable_and_others_replayable(journal):
    root = journal
    for person, step in (("acme/u_1", "mine"), ("acme/u_2", "theirs")):
        with act_for(person):
            agent = LedgerAgent(llm_client=ScriptedLLM(SCRIPT))
            await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": step})
    journal_module._journal.close()

    planned = erase(root, "acme/u_1", dry_run=True)
    assert planned["runs"] == 1 and planned["erased"] > 0 and planned["kept_shared"] > 0
    assert erase(root, "acme/u_1") == planned
    assert erase(root, "acme/u_1")["erased"] == 0

    assert verify(root).ok
    assert not (await replay(root, "wf/mine")).reproduced
    assert (await replay(root, "wf/theirs")).reproduced


@pytest.mark.asyncio
async def test_a_run_records_what_the_person_held_and_replays_with_it(journal):
    from jarviscore.auth import principal

    seen = []

    class Witness(LedgerAgent):
        def get_system_prompt(self) -> str:
            seen.append((principal.acting_for.get(), principal.scopes.get(), principal.mandate.get()))
            return super().get_system_prompt()

    carol = OnBehalfOf.of("acme", "carol", mandate={"systems": ["erp"]},
                          scopes={"claims.approve": {"amount": "10000"}})
    with act_for(carol):
        await Witness(llm_client=ScriptedLLM(SCRIPT)).run(
            task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})
    journal_module._journal.close()
    with open(os.path.join(journal, "runs", "wf_pay.jsonl")) as handle:
        start = json.loads(handle.readline())["data"]
    assert start["acting_for"] == "acme/carol" and start["scopes"] and start["mandate"]

    recorded = seen[-1]
    seen.clear()
    report = await replay(journal, "wf/pay", factory=lambda agent_id, llm: Witness(llm_client=llm))
    assert report.reproduced, report.divergence
    assert seen and seen[-1] == recorded == ("acme/carol", carol.scopes, {"systems": ["erp"]})
