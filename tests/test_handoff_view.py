from jarviscore.core.envelope import handoff_view


def test_a_later_reader_sees_the_delivered_work_whole_and_working_state_by_reference():
    artifact = {
        "answer": "4 syncs failed today",
        "observed_tool_result": {"rows": ["a", "b"]},
        "browser_state": {"sync_details": {"0": "x" * 5000}, "procedure": "open each row"},
        "browser_programs": [{"code": "rows = ..."}],
    }

    view = handoff_view(artifact, "inspect")

    assert view["answer"] == artifact["answer"]
    assert view["observed_tool_result"] == artifact["observed_tool_result"]
    assert "browser_state" not in view and "browser_programs" not in view
    held = view["working_state"]["fields"]
    assert held["browser_state"]["keys"] == ["procedure", "sync_details"]
    assert held["browser_state"]["chars"] > 5000
    assert held["browser_programs"]["items"] == 1
    assert 'read_workflow_step("inspect")' in view["working_state"]["read_whole"]
    assert artifact["browser_state"]["sync_details"]["0"] == "x" * 5000


def test_an_artifact_without_working_state_passes_through_unchanged():
    artifact = {"answer": "done", "rows": [1, 2]}
    assert handoff_view(artifact, "s") is artifact
    assert handoff_view("plain text", "s") == "plain text"


def test_unfinished_envelope_keeps_status_and_progress_without_repeating_working_state():
    output = {"answer": "one item remains", "browser_state": {"rows": ["full row"] * 1000}}
    artifact = {
        "status": "epoch_exhausted", "output": output, "payload": output,
        "progress": {"working_notes": ["second item still unread"]},
    }
    view = handoff_view(artifact, "inspect")
    assert view["status"] == "epoch_exhausted"
    assert view["progress"] == artifact["progress"]
    assert view["output"]["answer"] == "one item remains"
    assert "browser_state" not in view["output"]
    assert "working_state" in view["output"]
    assert "payload" not in view
    assert artifact["payload"]["browser_state"]["rows"] == ["full row"] * 1000
