"""The journal: every record intact, every run accounted for, every provider call decided first."""
import json
import os

from jarviscore.evidence.journal import HEADS, Journal, verify


def write_run(journal, run="wf-1/step0", *, refused=False):
    journal.append(run, "policy.decision", {"call_id": "c1", "outcome": "deny" if refused else "allow",
                                            "enforced": refused})
    if not refused:
        journal.append(run, "effect.attempt", {"call_id": "c1"})
        journal.append(run, "effect.outcome", {"call_id": "c1", "status": 200})


def lines(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read().splitlines()


def rewrite(path, new_lines):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(new_lines) + ("\n" if new_lines else ""))


def test_an_untouched_journal_verifies(tmp_path):
    journal = Journal(str(tmp_path))
    write_run(journal)
    write_run(journal, "wf-1/step1", refused=True)

    report = verify(str(tmp_path))

    assert report.ok, report.problems
    assert (report.runs, report.events, report.effects, report.refused) == (2, 4, 1, 1)


def test_an_edited_event_is_detected(tmp_path):
    journal = Journal(str(tmp_path))
    write_run(journal)
    path = journal.run_path("wf-1/step0")
    events = lines(path)
    edited = json.loads(events[2])
    edited["data"]["status"] = 500
    events[2] = json.dumps(edited)
    rewrite(path, events)

    assert any("does not match its hash" in p for p in verify(str(tmp_path)).problems)


def test_a_removed_event_is_detected(tmp_path):
    journal = Journal(str(tmp_path))
    write_run(journal)
    path = journal.run_path("wf-1/step0")
    events = lines(path)
    rewrite(path, [events[0], events[2]])

    problems = verify(str(tmp_path)).problems
    assert any("does not follow" in p for p in problems)


def test_a_run_cut_short_is_detected_by_the_head_log(tmp_path):
    journal = Journal(str(tmp_path))
    write_run(journal)
    path = journal.run_path("wf-1/step0")
    rewrite(path, lines(path)[:2])

    problems = verify(str(tmp_path)).problems
    assert any("cut short" in p for p in problems)


def test_a_removed_run_is_detected(tmp_path):
    journal = Journal(str(tmp_path))
    write_run(journal)
    os.remove(journal.run_path("wf-1/step0"))

    assert any("record is missing" in p for p in verify(str(tmp_path)).problems)


def test_an_edited_head_log_is_detected(tmp_path):
    journal = Journal(str(tmp_path))
    write_run(journal)
    heads = os.path.join(str(tmp_path), HEADS)
    edited = lines(heads)
    edited[0] = edited[0].replace('"run_seq":0', '"run_seq":9')
    assert edited[0] != lines(heads)[0]
    rewrite(heads, edited)

    assert not verify(str(tmp_path)).ok


def test_a_journal_being_written_is_noted_not_reported_as_tampered(tmp_path):
    journal = Journal(str(tmp_path))
    write_run(journal)
    heads = os.path.join(str(tmp_path), HEADS)
    # What verify sees when a run is appended after it read the head log, or a write
    # was interrupted between the run and the head log: nothing registered is lost.
    rewrite(heads, lines(heads)[:-1])

    report = verify(str(tmp_path))
    assert report.ok and any("after its registered head" in note for note in report.notes)


def test_a_provider_call_without_a_decision_is_flagged(tmp_path):
    journal = Journal(str(tmp_path))
    journal.append("wf-2/step0", "effect.attempt", {"call_id": "orphan"})

    assert any("no decision before it" in p for p in verify(str(tmp_path)).problems)


def test_a_provider_call_policy_refused_is_flagged(tmp_path):
    journal = Journal(str(tmp_path))
    journal.append("wf-3/step0", "policy.decision", {"call_id": "c9", "outcome": "deny", "enforced": True})
    journal.append("wf-3/step0", "effect.attempt", {"call_id": "c9"})

    assert any("policy refused" in p for p in verify(str(tmp_path)).problems)


def test_events_carry_no_query_strings_or_bodies_by_construction(tmp_path):
    journal = Journal(str(tmp_path))
    event = journal.append("wf-4/step0", "policy.decision", {"call_id": "c", "path": "/v1/charges"})

    assert set(event) == {"v", "run", "seq", "ts", "kind", "data", "prev", "hash"}


def _verify_cli(monkeypatch, *args):
    import pytest
    from jarviscore.cli import verify as cli

    monkeypatch.setattr("sys.argv", ["jarviscore verify", *args])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    return exited.value.code


def test_the_verify_command_exits_by_what_it_found(tmp_path, monkeypatch, capsys):
    journal = Journal(str(tmp_path))
    write_run(journal)
    assert _verify_cli(monkeypatch, str(tmp_path)) == 0

    path = journal.run_path("wf-1/step0")
    rewrite(path, lines(path)[:1])
    assert _verify_cli(monkeypatch, str(tmp_path), "--json") == 1
    assert '"ok": false' in capsys.readouterr().out

    assert _verify_cli(monkeypatch, str(tmp_path / "nowhere")) == 2
