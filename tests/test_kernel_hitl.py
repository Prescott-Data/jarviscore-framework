"""
Tests for 6E: HumanTask + AdaptiveHITLPolicy.

What these tests prove:
- HumanTask creates with valid defaults and unique IDs
- Policy disabled → never escalates
- Policy enabled + low confidence → escalates with reason
- Policy enabled + high risk → escalates with reason
- Policy enabled + matching reason code → escalates
- Policy enabled + all values OK → does not escalate
"""

import pytest

from jarviscore.kernel.hitl import HumanTask, AdaptiveHITLPolicy


class TestHumanTask:

    def test_default_creation(self):
        task = HumanTask(description="Review this output")
        assert task.type == "approval"
        assert task.status == "created"
        assert task.description == "Review this output"
        assert len(task.id) == 8
        assert task.user_response is None

    def test_unique_ids(self):
        t1 = HumanTask(description="a")
        t2 = HumanTask(description="b")
        assert t1.id != t2.id

    def test_all_types(self):
        for t in ("approval", "exception", "input_request", "notification"):
            task = HumanTask(type=t, description="test")
            assert task.type == t

    def test_serialization_roundtrip(self):
        task = HumanTask(
            type="input_request",
            description="Enter API key",
            request_payload={"field": "api_key"},
        )
        data = task.model_dump()
        restored = HumanTask.model_validate(data)
        assert restored.description == "Enter API key"
        assert restored.request_payload == {"field": "api_key"}


class TestPolicyDisabled:

    def test_never_escalates_when_disabled(self):
        policy = AdaptiveHITLPolicy(enabled=False)
        should, reason = policy.should_escalate(confidence=0.1, risk_score=0.99)
        assert should is False
        assert reason == ""


class TestPolicyConfidence:

    def test_low_confidence_triggers(self):
        policy = AdaptiveHITLPolicy(enabled=True, max_confidence=0.8)
        should, reason = policy.should_escalate(confidence=0.5)
        assert should is True
        assert "low_confidence" in reason

    def test_high_confidence_passes(self):
        policy = AdaptiveHITLPolicy(enabled=True, max_confidence=0.8)
        should, reason = policy.should_escalate(confidence=0.9)
        assert should is False

    def test_exact_threshold_passes(self):
        """Confidence == max_confidence is NOT below threshold."""
        policy = AdaptiveHITLPolicy(enabled=True, max_confidence=0.8)
        should, _ = policy.should_escalate(confidence=0.8)
        assert should is False


class TestPolicyRiskScore:

    def test_high_risk_triggers(self):
        policy = AdaptiveHITLPolicy(enabled=True, min_risk_score=0.7)
        should, reason = policy.should_escalate(risk_score=0.9)
        assert should is True
        assert "high_risk" in reason

    def test_low_risk_passes(self):
        policy = AdaptiveHITLPolicy(enabled=True, min_risk_score=0.7)
        should, _ = policy.should_escalate(risk_score=0.3)
        assert should is False

    def test_exact_threshold_passes(self):
        """Risk score == min_risk_score is NOT above threshold."""
        policy = AdaptiveHITLPolicy(enabled=True, min_risk_score=0.7)
        should, _ = policy.should_escalate(risk_score=0.7)
        assert should is False


class TestPolicyReasonCodes:

    def test_matching_reason_code_triggers(self):
        policy = AdaptiveHITLPolicy(
            enabled=True, reason_codes=["destructive_action", "external_api"]
        )
        should, reason = policy.should_escalate(reason_code="destructive_action")
        assert should is True
        assert "reason_code:destructive_action" in reason

    def test_non_matching_reason_code_passes(self):
        policy = AdaptiveHITLPolicy(
            enabled=True, reason_codes=["destructive_action"]
        )
        should, _ = policy.should_escalate(reason_code="safe_action")
        assert should is False

    def test_empty_reason_codes_list(self):
        policy = AdaptiveHITLPolicy(enabled=True, reason_codes=[])
        should, _ = policy.should_escalate(reason_code="anything")
        assert should is False


class TestPolicyNoTriggers:

    def test_no_arguments_does_not_escalate(self):
        """Policy enabled but no trigger values → no escalation."""
        policy = AdaptiveHITLPolicy(enabled=True)
        should, _ = policy.should_escalate()
        assert should is False
