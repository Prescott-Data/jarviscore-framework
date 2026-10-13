"""
FailureLedger records failures as facts.

What these tests prove:
- A class the tool declares (error_type) is recorded; nothing is guessed from prose or codes
- A status code is recorded as a fact beside the class
- The whole error is kept, never clipped
- record() indexes the failure under the run's workflow id
- The ledger records; it never guards a call
"""

from unittest.mock import MagicMock

from jarviscore.kernel.cognition import FailureLedger


def _recorded(**kwargs):
    ledger = FailureLedger(agent_id="a", workflow_id="wf-1")
    ledger.record("call_api", {"x": 1}, **kwargs)
    return ledger.recent_failures[-1]


class TestRecordsWhatTheToolSaid:

    def test_a_declared_error_type_is_recorded(self):
        entry = _recorded(error="404 not found", output={"status": "error", "error_type": "quota_exceeded"})
        assert entry["error_type"] == "QUOTA_EXCEEDED"

    def test_prose_is_never_turned_into_a_class(self):
        for text in ("rate limit exceeded", "HTTP 401 from gateway", "connection refused", "not found"):
            assert _recorded(error=text)["error_type"] == "UNKNOWN"

    def test_a_status_code_is_a_fact_not_a_class(self):
        entry = _recorded(error="request failed", output={"status": "error", "status_code": 429})
        assert entry["error_type"] == "UNKNOWN"
        assert entry["status_code"] == 429

    def test_the_whole_error_is_kept(self):
        error = "upstream said: " + "x" * 5000
        assert _recorded(error=error)["error"] == error


class TestRecordIndexing:

    def test_record_indexes_under_its_workflow_id(self):
        redis = MagicMock()
        redis.index_failure_event = MagicMock()

        ledger = FailureLedger(agent_id="agent-9", workflow_id="wf-real-42", redis_store=redis)
        ledger.record("web_search", {"q": "x"}, error="403 forbidden", output={"error_type": "auth_forbidden"})

        kwargs = redis.index_failure_event.call_args.kwargs
        assert kwargs["workflow_id"] == "wf-real-42"
        assert kwargs["error_type"] == "AUTH_FORBIDDEN"


class TestRecordsWithoutGuarding:

    def test_ledger_offers_no_guard(self):
        ledger = FailureLedger(agent_id="a", workflow_id="wf")
        ledger.record("tool", {"p": 1}, error="something inexplicable")
        assert ledger.recent_failures[-1]["error_type"] == "UNKNOWN"
        assert not hasattr(ledger, "is_guarded")
        assert not hasattr(ledger, "render_block")
