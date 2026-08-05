"""Tests for `jarviscore inspect` - the trace reader."""

import json
import os

import pytest

from jarviscore.cli.inspect import _clip, _discover, _list_runs, _run_summary, _show_run


def _write_trace(trace_dir, workflow_id, step_id, events):
    os.makedirs(trace_dir, exist_ok=True)
    path = os.path.join(trace_dir, f"{workflow_id}_{step_id}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        for i, (etype, data) in enumerate(events):
            fh.write(json.dumps({
                "workflow_id": workflow_id,
                "step_id": step_id,
                "timestamp": f"2026-08-04T10:00:{i:02d}+00:00",
                "type": etype,
                "data": data,
            }) + "\n")
    return path


@pytest.fixture
def trace_dir(tmp_path):
    d = str(tmp_path / "traces")
    _write_trace(d, "research-run", "step-1", [
        ("workflow_start", {"step_count": 2}),
        ("step_claimed", {"agent_id": "researcher"}),
        ("llm_request", {"provider": "claude", "model": "sonnet"}),
        ("llm_response", {"tokens": 420, "latency_ms": 900}),
        ("tool_start", {"tool_name": "web_search", "params": {"q": "x"}}),
        ("tool_result", {"result": "found 3 sources"}),
        ("step_complete", {"summary": "research done"}),
    ])
    _write_trace(d, "research-run", "step-2", [
        ("step_claimed", {"agent_id": "writer"}),
        ("step_failed", {"error": "provider timeout"}),
        ("error_recovery", {"error": "provider timeout", "action": "retried with fallback"}),
        ("workflow_complete", {"status": "complete", "summary": "done"}),
    ])
    _write_trace(d, "other-run", "s1", [
        ("workflow_start", {"step_count": 1}),
        ("workflow_complete", {"status": "failed", "summary": "boom"}),
    ])
    return d


def test_discover_groups_files_by_workflow(trace_dir):
    runs = _discover(trace_dir)
    assert set(runs) == {"research-run", "other-run"}
    assert len(runs["research-run"]) == 2


def test_run_summary_aggregates_steps_tokens_failures(trace_dir):
    runs = _discover(trace_dir)
    s = _run_summary(runs["research-run"])
    assert s["steps"] == 2
    assert s["tokens"] == 420
    assert s["failures"] == 2      # step_failed + error_recovery
    assert s["status"] == "complete"
    assert s["duration"].endswith("s")


def test_list_runs_renders_table(trace_dir, capsys):
    assert _list_runs(trace_dir) == 0
    out = capsys.readouterr().out
    assert "research-run" in out
    assert "other-run" in out
    assert "workflow" in out       # header


def test_list_runs_empty_dir_is_helpful(tmp_path, capsys):
    assert _list_runs(str(tmp_path / "nowhere")) == 1
    assert "no trace files" in capsys.readouterr().out


def test_show_run_renders_timeline_grouped_by_step(trace_dir, capsys):
    assert _show_run(trace_dir, "research-run", step=None, errors_only=False) == 0
    out = capsys.readouterr().out
    assert "[step-1]" in out and "[step-2]" in out
    assert "web_search" in out
    assert "420 tokens" in out
    assert "STEP FAILED: provider timeout" in out
    assert "!! " in out            # error marker


def test_show_run_errors_only_filter(trace_dir, capsys):
    assert _show_run(trace_dir, "research-run", step=None, errors_only=True) == 0
    out = capsys.readouterr().out
    assert "STEP FAILED" in out and "RECOVERY" in out
    assert "web_search" not in out


def test_show_run_prefix_match_and_ambiguity(trace_dir, capsys):
    assert _show_run(trace_dir, "research", step=None, errors_only=False) == 0
    # shared prefix of both runs is ambiguous
    _write_trace(trace_dir, "research-run-b", "s1", [("workflow_start", {})])
    assert _show_run(trace_dir, "research", step=None, errors_only=False) == 1
    assert "ambiguous" in capsys.readouterr().err


def test_show_run_unknown_workflow(trace_dir, capsys):
    assert _show_run(trace_dir, "nope", step=None, errors_only=False) == 1
    assert "no run matching" in capsys.readouterr().err


def test_clip_marks_truncation_honestly():
    assert _clip("short") == "short"
    clipped = _clip("x" * 500, 100)
    assert clipped.startswith("x" * 100)
    assert "[clipped: showing 100 of 500 chars]" in clipped


def test_unparseable_lines_survive_as_events(trace_dir, capsys):
    with open(os.path.join(trace_dir, "research-run_step-1.jsonl"), "a") as fh:
        fh.write("not json at all\n")
    assert _show_run(trace_dir, "research-run", step=None, errors_only=True) == 0
    assert "unparseable_line" in capsys.readouterr().out
