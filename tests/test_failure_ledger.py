"""
Tests for issue #60: FailureLedger integrity.

What these tests prove:
- Structured signals (error_type field, status_code) outrank prose sniffing
- Numeric codes in prose match on word boundaries — "1404 rows" is not a 404
- record() feeds the structured output into classification
- is_guarded() queries Redis with the SAME workflow id record() writes
- UNKNOWN guarding is configurable (guard = historical default, skip = lenient)
"""

from unittest.mock import MagicMock

import jarviscore.kernel.cognition as cognition
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


class TestGuardKeyAlignment:

    def test_is_guarded_queries_the_workflow_id_record_writes(self):
        redis = MagicMock()
        redis.has_failure_guard = MagicMock(return_value=False)
        redis.index_failure_event = MagicMock()

        ledger = FailureLedger(agent_id="agent-9", workflow_id="wf-real-42", redis_store=redis)
        fp = ledger.record("web_search", {"q": "x"}, error="403 forbidden")
        ledger.is_guarded(fp)

        written_wf = redis.index_failure_event.call_args.kwargs["workflow_id"]
        read_wf = redis.has_failure_guard.call_args.args[1]
        assert written_wf == read_wf == "wf-real-42"


class TestUnknownGuardPolicy:

    def _guarded_after_unknown_failure(self):
        ledger = FailureLedger(agent_id="a", workflow_id="wf")
        fp = ledger.record("tool", {"p": 1}, error="something inexplicable")
        assert ledger.recent_failures[-1]["error_type"] == "UNKNOWN"
        return ledger.is_guarded(fp)

    def test_default_guards_unknown(self):
        assert self._guarded_after_unknown_failure() is True

    def test_skip_mode_does_not_guard_unknown(self, monkeypatch):
        monkeypatch.setattr(cognition, "_FAILURE_GUARD_UNKNOWN", "skip")
        assert self._guarded_after_unknown_failure() is False

    def test_transient_failures_never_guarded_either_way(self):
        ledger = FailureLedger(agent_id="a", workflow_id="wf")
        fp = ledger.record("tool", {"p": 1}, error="connection timed out")
        assert ledger.is_guarded(fp) is False
