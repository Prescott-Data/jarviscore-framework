"""
Tests for issue #60: FailureLedger integrity.

What these tests prove:
- Structured signals (error_type field, status_code) outrank prose sniffing
- Numeric codes in prose match on word boundaries — "1404 rows" is not a 404
- record() feeds the structured output into classification
- record() indexes the failure under the run's workflow id
- The ledger records; it never guards a call
"""

from unittest.mock import MagicMock

from jarviscore.kernel.cognition import FailureLedger


classify = FailureLedger._classify_error


class TestStructuredFirstClassification:

    def test_explicit_error_type_field_wins(self):
        out = {"status": "error", "error_type": "quota_exceeded", "error": "404 not found"}
        assert classify("404 not found", output=out) == "QUOTA_EXCEEDED"

    def test_status_code_outranks_prose(self):
        out = {"status": "error", "status_code": 429, "error": "the request failed"}
        assert classify("the request failed", output=out) == "RATE_LIMIT"

    def test_code_key_also_recognized(self):
        assert classify("boom", output={"code": 403}) == "AUTH_FORBIDDEN"

    def test_5xx_classifies_as_network(self):
        assert classify("server error", output={"status_code": 503}) == "NETWORK"

    def test_non_numeric_code_falls_through_to_prose(self):
        assert classify("connection reset", output={"code": "ERR_RESET"}) == "NETWORK"


class TestWordBoundaryProse:

    def test_1404_rows_is_not_a_404(self):
        assert classify("processed 1404 rows before failing") == "UNKNOWN"

    def test_plain_404_still_matches(self):
        assert classify("upstream returned 404") == "NOT_FOUND"

    def test_race_condition_401_boundary(self):
        assert classify("id 84012 missing") == "UNKNOWN"
        assert classify("HTTP 401 from gateway") == "AUTH_UNAUTHORIZED"

    def test_historical_text_classes_unchanged(self):
        assert classify("request timed out after 30s") == "TIMEOUT"
        assert classify("rate limit exceeded") == "RATE_LIMIT"
        assert classify("schema validation failed") == "SCHEMA_VALIDATION"
        assert classify("connection refused") == "NETWORK"


class TestRecordUsesStructuredOutput:

    def test_record_classifies_from_output_dict(self):
        ledger = FailureLedger(agent_id="a", workflow_id="wf-1")
        ledger.record(
            "call_api", {"x": 1},
            error="request failed",
            output={"status": "error", "status_code": 429},
        )
        assert ledger.recent_failures[-1]["error_type"] == "RATE_LIMIT"


class TestRecordIndexing:

    def test_record_indexes_under_its_workflow_id(self):
        redis = MagicMock()
        redis.index_failure_event = MagicMock()

        ledger = FailureLedger(agent_id="agent-9", workflow_id="wf-real-42", redis_store=redis)
        ledger.record("web_search", {"q": "x"}, error="403 forbidden")

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
