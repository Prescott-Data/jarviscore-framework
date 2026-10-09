"""Consequential actions wait for a person through JarvisCore HITL.

The browser and coder kernels share this one path. An unapproved action raises
a typed ``HITLRequest`` and pauses its step; the person's ``HITLResolution`` is
the only authority that lets it run; and what became of it is settled on the
same record, so an approved action runs at most once.
"""

from __future__ import annotations

from typing import Any

from jarviscore.contracts.hitl import (
    HITLAction,
    HITLCategory,
    HITLRequest,
    HITLResolution,
    HITLType,
)


def _durable(store, workflow_id, step_id) -> bool:
    return bool(
        store is not None
        and hasattr(store, "create_hitl_request_typed")
        and workflow_id
        and step_id
    )


def _waiting(action: HITLAction, request_id: str, workflow_id: str, step_id: str) -> dict[str, Any]:
    return {
        "status": "waiting",
        "hitl_required": True,
        "hitl_type": "approval",
        "typed_outcome": "WAITING_FOR_APPROVAL",
        "system": action.system,
        "action_id": action.action_id,
        "hitl_request_id": request_id,
        "action": action.description,
        "consequence": action.consequence,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "detail": f"Waiting for approval: {action.consequence}",
    }


def gate(store, workflow_id: str, step_id: str, action: HITLAction) -> dict[str, Any] | None:
    """None when the person approved ``action`` and it has not run; otherwise its tool result."""
    if not _durable(store, workflow_id, step_id):
        return {
            "status": "error",
            "error": (
                "This action needs a person's approval, which requires durable "
                "workflow state; it was not performed."
            ),
            "semantic_error": "APPROVAL_UNAVAILABLE",
        }
    record = store.get_hitl_request(workflow_id, step_id, action.action_id)
    outcome = (record or {}).get("outcome")
    if record is None or (isinstance(outcome, dict) and outcome.get("status") == "not_performed"):
        # An approval that could not be carried out leaves the action undecided.
        request = HITLRequest(
            workflow_id=workflow_id,
            step_id=step_id,
            type=HITLType.approval,
            category=HITLCategory.critical_action,
            description=action.description or action.consequence,
            action=action,
        )
        store.create_hitl_request_typed(request)
        return _waiting(action, request.request_id, workflow_id, step_id)
    resolution = HITLResolution.from_raw(record)
    if resolution is not None and resolution.is_rejected:
        return {
            "status": "error",
            "error": f"The person declined this action, so it was not performed: {action.consequence}",
            "semantic_error": "ACTION_DECLINED",
            "system": action.system,
        }
    if resolution is None or not resolution.is_approved:
        return _waiting(action, str(record.get("request_id") or ""), workflow_id, step_id)
    outcome = record.get("outcome")
    if isinstance(outcome, dict):
        return {
            **outcome,
            "note": "This approved action already ran; this is its recorded outcome. Do not repeat it.",
        }
    return None


def settle(store, workflow_id: str, step_id: str, action_id: str, outcome: dict[str, Any]) -> None:
    """Record what became of a decided action against its decision."""
    if _durable(store, workflow_id, step_id):
        store.settle_hitl_action(workflow_id, step_id, action_id, outcome)


def decided(store, workflow_id: str, step_id: str) -> list[tuple[HITLAction, bool]]:
    """This step's actions a person approved or declined that are not yet settled."""
    if not _durable(store, workflow_id, step_id):
        return []
    actions = []
    for raw in store.list_hitl_action_requests(workflow_id, step_id):
        if raw.get("outcome") is not None or not isinstance(raw.get("action"), dict):
            continue
        resolution = HITLResolution.from_raw(raw)
        if resolution is None or not (resolution.is_approved or resolution.is_rejected):
            continue
        actions.append((HITLAction(**raw["action"]), resolution.is_approved))
    return actions
