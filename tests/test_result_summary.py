"""result_summary display contract on execute_task envelopes (#40)."""

from jarviscore.core.envelope import attach_result_summary, derive_result_summary


def test_success_string_payload_is_the_summary():
    assert derive_result_summary("success", "The answer is 42.") == "The answer is 42."


def test_success_dict_probes_prose_keys():
    out = {"data": {"rows": [1, 2]}, "final_answer": "Two rows matched."}
    assert derive_result_summary("success", out) == "Two rows matched."


def test_success_nested_prose():
    out = {"response": {"content": "Done: report drafted."}}
    assert derive_result_summary("success", out) == "Done: report drafted."


def test_success_structured_only_falls_back_to_summary():
    assert derive_result_summary("success", {"rows": [1]}, summary="Fetched one row.") == "Fetched one row."


def test_success_never_serialises_dicts():
    result = derive_result_summary("success", {"rows": [1, 2, 3]})
    assert "{" not in result and "[" not in result


def test_failure_uses_error_sentence_first_line_only():
    err = "Kernel exception: boom\nTraceback (most recent call last):\n  ..."
    assert derive_result_summary("failure", None, err) == "Kernel exception: boom"


def test_yield_without_error_uses_summary():
    assert derive_result_summary("yield", None, None, summary="Lease budget exhausted") == "Lease budget exhausted"


def test_attach_is_idempotent():
    env = {"status": "success", "output": "hi", "result_summary": "already set"}
    assert attach_result_summary(env)["result_summary"] == "already set"


def test_attach_fills_missing():
    env = {"status": "failure", "output": None, "error": "no provider key"}
    assert attach_result_summary(env)["result_summary"] == "no provider key"
