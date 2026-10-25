"""Consequential actions wait for a person through JarvisCore HITL.

The browser and coder kernels share this one path. An unapproved action raises
a typed ``HITLRequest`` and pauses its step; the person's ``HITLResolution`` is
the only authority that lets it run; and what became of it is settled on the
same record, so an approved action runs at most once.

An approval covers exactly the action the person saw (``HITLAction.binding``).
When the deployment requires more of an approver (roles, not the requester,
a verified identity: ``control.approvals``), the approver is checked again when
the action is about to run, under the policy in force then. Carrying an action
out is claimed atomically; a claim with no outcome means a run stopped half way,
so the outcome is unknown and is reconciled, never retried blindly.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from jarviscore.contracts.hitl import (
    HITLAction,
    HITLCategory,
    HITLRequest,
    HITLResolution,
    HITLType,
)

logger = logging.getLogger(__name__)


def _durable(store, workflow_id, step_id) -> bool:
    return bool(
        store is not None
        and hasattr(store, "create_hitl_request_typed")
        and workflow_id
        and step_id
    )


def _record_event(workflow_id: str, step_id: str, kind: str, data: dict[str, Any]) -> None:
    """Write an approval event to the run's journal; a journal that fails never blocks a person."""
    from jarviscore.evidence.journal import current_journal

    journal = current_journal()
    if journal is None:
        return
    try:
        journal.append(f"{workflow_id}/{step_id}", kind, data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Journal write failed for %s: %s", kind, exc)


def _waiting(action: HITLAction, request_id: str, workflow_id: str, step_id: str) -> dict[str, Any]:
    return {
        "status": "waiting",
        "hitl_required": True,
        "hitl_type": "approval",
        "typed_outcome": "WAITING_FOR_APPROVAL",
        "system": action.system,
        "action_id": action.action_id,
        "binding": action.binding_digest(),
        "hitl_request_id": request_id,
        "action": action.description,
        "consequence": action.consequence,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "detail": f"Waiting for approval: {action.consequence}",
    }


def _same_binding(record: dict[str, Any], action: HITLAction) -> bool:
    """Whether the decision on record was asked for exactly this action."""
    asked = record.get("action")
    if not isinstance(asked, dict):
        return False
    try:
        return HITLAction(**asked).binding_digest() == action.binding_digest()
    except Exception:  # noqa: BLE001 - an unreadable record covers nothing
        return False


def _asks_again(record: Optional[dict], action: HITLAction) -> bool:
    """Whether ``gate`` puts ``action`` to a person, given the record on file."""
    outcome = (record or {}).get("outcome")
    return (
        record is None
        or (isinstance(outcome, dict) and outcome.get("status") == "not_performed")
        or (not isinstance(outcome, dict) and not _same_binding(record, action))
    )


def asked(store, workflow_id: str, step_id: str, action: HITLAction) -> bool:
    """Whether ``action`` is already before a person, decided, or done, so ``gate`` will not ask."""
    lookup = getattr(store, "get_hitl_request", None)
    if not _durable(store, workflow_id, step_id) or not callable(lookup):
        return False
    try:
        record = lookup(workflow_id, step_id, action.action_id)
    except Exception:  # noqa: BLE001 - unknown means ask as usual
        return False
    return not _asks_again(record if isinstance(record, dict) else None, action)


def _ask(store, workflow_id: str, step_id: str, action: HITLAction, requirement, checks=None) -> dict[str, Any]:
    from jarviscore.auth.principal import acting_for

    requester = acting_for.get() or ""
    request = HITLRequest(
        workflow_id=workflow_id,
        step_id=step_id,
        type=HITLType.approval,
        category=HITLCategory.critical_action,
        description=action.description or action.consequence,
        action=action,
        payload={
            "binding": action.binding_digest(),
            "requester": requester,
            **({"requirement": requirement.as_record()} if requirement is not None else {}),
            # What policy found when the action was previewed (grounding against records).
            **({"checks": checks} if checks else {}),
        },
    )
    store.create_hitl_request_typed(request)
    _record_event(workflow_id, step_id, "approval.request", {
        "action_id": action.action_id,
        "binding": action.binding_digest(),
        "tool": action.tool,
        "system": action.system,
        "consequence": action.consequence,
        "requester": requester,
        "requirement": requirement.as_record() if requirement is not None else None,
        **({"checks": checks} if checks else {}),
    })
    return _waiting(action, request.request_id, workflow_id, step_id)


def gate(
    store,
    workflow_id: str,
    step_id: str,
    action: HITLAction,
    requirement=None,
    directory: Optional[Mapping[str, Any]] = None,
    checks: Optional[list] = None,
) -> dict[str, Any] | None:
    """None when a person approved exactly ``action``, may approve it, and it is now claimed to run.

    Otherwise the tool result to return instead: waiting, declined, already ran
    (its recorded outcome, whatever arguments are offered again), or outcome unknown.
    """
    from jarviscore.control.approvals import Approver, ApprovalRequirement, check_approver

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
    if _asks_again(record, action):
        # An approval that could not be carried out leaves the action undecided, and
        # one given for other arguments does not cover these: the person decides again.
        return _ask(store, workflow_id, step_id, action, requirement, checks)
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
    if isinstance(outcome, dict):
        return {
            **outcome,
            "note": "This approved action already ran; this is its recorded outcome. Do not repeat it.",
        }
    if record.get("executing_at"):
        return _unknown(action, workflow_id, step_id)

    # Policy may have changed since the decision; the approver is held to the policy now.
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    required = requirement or ApprovalRequirement.from_record(payload.get("requirement"))
    refusal = check_approver(
        required, Approver.from_record(record),
        requester=str(payload.get("requester") or ""), directory=directory,
    )
    if refusal is not None:
        if hasattr(store, "reopen_hitl_action"):
            store.reopen_hitl_action(workflow_id, step_id, action.action_id, refusal)
        _record_event(workflow_id, step_id, "approval.reopened", {
            "action_id": action.action_id, "binding": action.binding_digest(), "reason": refusal,
        })
        waiting = _waiting(action, str(record.get("request_id") or ""), workflow_id, step_id)
        return {**waiting, "detail": f"{waiting['detail']} ({refusal})"}

    claim = getattr(store, "claim_hitl_execution", None)
    if callable(claim) and claim(workflow_id, step_id, action.action_id) is not True:
        return _unknown(action, workflow_id, step_id)
    _record_event(workflow_id, step_id, "approval.claim", {
        "action_id": action.action_id, "binding": action.binding_digest(),
        "approver": record.get("approver") or record.get("resolved_by") or "",
    })
    return None


def _unknown(action: HITLAction, workflow_id: str, step_id: str) -> dict[str, Any]:
    return {
        "status": "error",
        "semantic_error": "OUTCOME_UNKNOWN",
        "typed_outcome": "OUTCOME_UNKNOWN",
        "error": (
            "This approved action was started and its outcome was not recorded, so it is "
            "not run again. A person must check whether it happened and reconcile it "
            f"(Mesh.reconcile_hitl): {action.consequence}"
        ),
        "action_id": action.action_id,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "system": action.system,
    }


def settle(store, workflow_id: str, step_id: str, action_id: str, outcome: dict[str, Any]) -> None:
    """Record what became of a decided action against its decision.

    A tool that refused before acting (``performed: False``) changed nothing, so
    the decision stands for the action until it is actually carried out.
    """
    if not _durable(store, workflow_id, step_id):
        return
    if isinstance(outcome, dict) and outcome.get("performed") is False:
        release = getattr(store, "release_hitl_execution", None)
        if callable(release):
            release(workflow_id, step_id, action_id)
        return
    store.settle_hitl_action(workflow_id, step_id, action_id, outcome)
    _record_event(workflow_id, step_id, "approval.settle", {
        "action_id": action_id,
        "status": str((outcome or {}).get("status") or "") if isinstance(outcome, dict) else "",
    })


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


def assertion_keys() -> dict[str, str]:
    """Keys this deployment accepts approval assertions under (``APPROVAL_ASSERTION_KEYS``)."""
    import importlib

    settings = importlib.import_module("jarviscore.config.settings").settings
    keys = dict(getattr(settings, "approval_assertion_keys", None) or {})
    single = getattr(settings, "approval_assertion_key", None)
    if single:
        keys.setdefault("default", single)
    return {str(kid): str(key) for kid, key in keys.items() if key}


def record_decision(
    store,
    workflow_id: str,
    step_id: str,
    action_id: str,
    decision: str,
    *,
    resolved_by: str = "",
    note: str = "",
    approver=None,
    assertion: Optional[str] = None,
):
    """Record a person's decision on a waiting action, if the deployment accepts them as its approver.

    The approver comes from an approval assertion when one is given (verified
    against this deployment's keys and the exact action), else from an
    ``Approver`` the application built (``asserted``), else from ``resolved_by``
    (``unauthenticated``). An approval from someone the requirement does not
    accept raises ``ApprovalRefused``; anyone may decline. The first decision
    stands. Returns the approver recorded.
    """
    from dataclasses import replace

    from jarviscore.contracts.hitl import APPROVED_DECISIONS, normalize_hitl_decision
    from jarviscore.control.approvals import (
        Approver,
        ApprovalRefused,
        ApprovalRequirement,
        check_approver,
        verify_assertion,
    )
    from jarviscore.control.policy import current_policy

    record = store.get_hitl_request(workflow_id, step_id, action_id)
    if not record or not isinstance(record.get("action"), dict):
        raise KeyError(f"Workflow {workflow_id!r} has no action {action_id!r} awaiting a decision")
    action = HITLAction(**record["action"])
    binding = action.binding_digest()
    normalized = normalize_hitl_decision(decision)
    if assertion:
        who = verify_assertion(
            assertion, assertion_keys(), workflow_id=workflow_id, action_id=action_id,
            binding=binding, decision=normalized.value,
        )
    elif approver is not None:
        # Built by application code in this process: trusted as far as that code is.
        who = replace(approver, assurance="asserted" if approver.assurance == "verified" else approver.assurance)
    else:
        who = Approver(subject=resolved_by, assurance="unauthenticated")
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    if normalized in APPROVED_DECISIONS:
        refusal = check_approver(
            ApprovalRequirement.from_record(payload.get("requirement")), who,
            requester=str(payload.get("requester") or ""),
            directory=current_policy().principals,
        )
        if refusal is not None:
            _record_event(workflow_id, step_id, "approval.refused", {
                "action_id": action_id, "binding": binding, "reason": refusal, **who.as_record(),
            })
            raise ApprovalRefused(refusal)
    decided = store.resolve_hitl_action_once(
        workflow_id, step_id, action_id, normalized.value,
        responder=who.subject, comment=note, approver=who.as_record(),
    )
    if decided is None:
        raise KeyError(f"Workflow {workflow_id!r} has no action {action_id!r} awaiting a decision")
    if decided is False:
        raise ValueError("This action has already been decided.")
    _record_event(workflow_id, step_id, "approval.decision", {
        "action_id": action_id, "binding": binding, "decision": normalized.value, **who.as_record(),
    })
    return who


def reconcile(
    store,
    workflow_id: str,
    step_id: str,
    action_id: str,
    *,
    performed: bool,
    outcome: Optional[dict[str, Any]] = None,
    resolved_by: str = "",
    note: str = "",
) -> None:
    """Settle an action whose outcome is unknown, from what a person found it did.

    ``performed=True`` records ``outcome`` as what happened, so it never runs
    again; ``performed=False`` releases it, so the approved action can be carried
    out once more.
    """
    record = store.get_hitl_request(workflow_id, step_id, action_id)
    if not record or not record.get("executing_at") or isinstance(record.get("outcome"), dict):
        raise ValueError("Only an action whose outcome is unknown can be reconciled.")
    if performed:
        store.settle_hitl_action(workflow_id, step_id, action_id, {
            **(outcome or {"status": "success"}), "reconciled_by": resolved_by, "note": note,
        })
    else:
        store.release_hitl_execution(workflow_id, step_id, action_id)
    _record_event(workflow_id, step_id, "approval.reconciled", {
        "action_id": action_id, "performed": performed, "by": resolved_by, "note": note,
    })
