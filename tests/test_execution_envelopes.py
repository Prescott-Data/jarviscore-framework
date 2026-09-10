import json

import pytest

from jarviscore.orchestration.envelopes import (
    CapabilityMandate,
    ClaimRecord,
    DependencyAuthorization,
    ExecutionBudget,
    EffectIntentDecision,
    FulfillmentRecord,
    WorkflowEvidence,
    WorkflowEnvelope,
    neutral_context,
    terminal_step_status,
)


def test_neutral_context_copies_data_and_removes_authority():
    original = {
        "source_context": {"lead": {"email": "lead@example.com"}},
        "workflow_id": "wf-1",
        "system": "hubspot",
        "effect": "write",
        "_secret": "hidden",
    }

    neutral = neutral_context(original)
    neutral["source_context"]["lead"]["email"] = "changed@example.com"

    assert neutral == {
        "source_context": {"lead": {"email": "changed@example.com"}},
        "workflow_id": "wf-1",
    }
    assert original["source_context"]["lead"]["email"] == "lead@example.com"


def test_workflow_envelope_round_trips_neutral_context():
    envelope = WorkflowEnvelope(
        workflow_id="wf-1",
        goal="Resolve the lead",
        context={"source_context": {"lead": {"email": "lead@example.com"}}},
        obligations=[{"id": "o1"}],
        steps=[{"id": "s1", "status": "pending"}],
        revision=2,
        published_at=12.5,
    )

    restored = WorkflowEnvelope.from_record(envelope.to_record())

    assert restored == envelope


def test_capability_mandate_preserves_existing_redis_shape():
    mandate = CapabilityMandate.open(
        mandate_id="need-1",
        workflow_id="wf-1",
        requester_agent_id="requester-1",
        requester_step_id="s1",
        capability="contact_verification",
        question="Resolve the contact.",
        context={"source_context": {"lead": {"email": "lead@example.com"}}},
        now=10.0,
    )
    claimed = CapabilityMandate(
        **{
            **mandate.__dict__,
            "status": "fulfilled",
            "updated_at": 20.0,
            "claim": ClaimRecord("resolver-1:claim", "resolver-1", 30.0),
            "fulfillment": FulfillmentRecord(
                "resolver-1", {"status": "success", "output": {"verified": True}}
            ),
        }
    )

    record = claimed.to_record()
    restored = CapabilityMandate.from_record(record)

    assert record["id"] == "need-1"
    assert record["claim_id"] == "resolver-1:claim"
    assert record["fulfilled_by"] == "resolver-1"
    assert restored == claimed


def test_workflow_evidence_is_a_defensive_snapshot():
    artifacts = {"step_1": {"deal_id": "deal-1"}}
    evidence = WorkflowEvidence(
        artifacts=artifacts,
        interpretations={"step_1": {"decision": "proceed"}},
        states={"step_1": "completed", "step_2": "blocked"},
    )

    record = evidence.to_record()
    record["artifacts"]["step_1"]["deal_id"] = "changed"

    assert evidence.artifacts["step_1"]["deal_id"] == "deal-1"


def test_execution_budget_is_bounded_and_round_trips_with_workflow():
    budget = ExecutionBudget.from_record({
        "max_steps": 12,
        "max_replans": 2,
        "max_peer_depth": 2,
        "peer_timeout_seconds": 45,
    })
    envelope = WorkflowEnvelope(
        workflow_id="wf-budget",
        goal="Bound the work",
        budget=budget,
    )

    restored = WorkflowEnvelope.from_record(envelope.to_record())

    assert restored.budget == budget
    assert restored.to_record()["budget"]["max_steps"] == 12


def test_agent_yield_is_a_durable_waiting_step():
    assert terminal_step_status("yield") == "waiting"
    assert terminal_step_status("waiting") == "waiting"
    assert terminal_step_status("hitl") == "waiting"
    assert terminal_step_status("blocked") == "blocked"
    assert terminal_step_status("success") == "completed"
    assert terminal_step_status("failure") == "failed"


def test_effect_intent_decision_requires_typed_grounded_json():
    decision = EffectIntentDecision.from_response(
        '{"decision":"redirect","reason":"Deal absence is unverified",'
        '"missing_evidence":["Inspect existing deals"]}'
    )
    assert decision.decision == "redirect"
    assert decision.missing_evidence == ("Inspect existing deals",)


def test_effect_intent_decision_can_prove_the_effect_is_already_satisfied():
    decision = EffectIntentDecision.from_response(json.dumps({
        "decision": "already_satisfied",
        "reason": "The requested meeting already exists with the intended attendee.",
        "missing_evidence": [],
        "supporting_evidence": ["event-1 includes ephy@example.com"],
    }))

    assert decision.decision == "already_satisfied"
    assert decision.supporting_evidence == (
        "event-1 includes ephy@example.com",
    )


def test_effect_intent_already_satisfied_requires_evidence():
    with pytest.raises(ValueError, match="requires supporting_evidence"):
        EffectIntentDecision.from_response(json.dumps({
            "decision": "already_satisfied",
            "reason": "It exists.",
            "missing_evidence": [],
        }))


def test_dependency_authorization_is_typed():
    decision = DependencyAuthorization.from_response(
        '{"decision":"allow","reason":"The unresolved cleanup is unrelated."}'
    )
    assert decision.decision == "allow"
