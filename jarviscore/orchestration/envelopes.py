"""Canonical durable envelopes for distributed Mesh execution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Literal, Optional, cast
import json


AUTHORITY_KEYS = frozenset({
    "system",
    "systems",
    "effect",
    "capability",
    "step_id",
    "execution_contract",
    "execution_budget",
    "output_schema",
    "mesh_workflow_id",
})


def neutral_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Copy caller context while removing execution authority and private state."""
    return deepcopy({
        key: value
        for key, value in dict(context or {}).items()
        if key not in AUTHORITY_KEYS and not str(key).startswith("_")
    })


@dataclass(frozen=True)
class ExecutionBudget:
    max_seconds: float = 900.0
    max_steps: int = 30
    max_replans: int = 8
    max_tokens: int = 240_000
    max_peer_depth: int = 2
    peer_timeout_seconds: float = 300.0

    @classmethod
    def from_record(cls, record: Optional[Dict[str, Any]] = None):
        values = dict(record or {})
        return cls(
            max_seconds=max(1.0, float(values.get("max_seconds", 900.0))),
            max_steps=max(1, int(values.get("max_steps", 30))),
            max_replans=max(0, int(values.get("max_replans", 8))),
            max_tokens=max(1, int(values.get("max_tokens", 240_000))),
            max_peer_depth=max(1, int(values.get("max_peer_depth", 2))),
            peer_timeout_seconds=max(
                1.0, float(values.get("peer_timeout_seconds", 300.0))
            ),
        )

    def to_record(self) -> Dict[str, Any]:
        return {
            "max_seconds": self.max_seconds,
            "max_steps": self.max_steps,
            "max_replans": self.max_replans,
            "max_tokens": self.max_tokens,
            "max_peer_depth": self.max_peer_depth,
            "peer_timeout_seconds": self.peer_timeout_seconds,
        }


@dataclass(frozen=True)
class WorkflowEnvelope:
    workflow_id: str
    goal: str
    context: Dict[str, Any] = field(default_factory=dict)
    obligations: list[Dict[str, Any]] = field(default_factory=list)
    steps: list[Dict[str, Any]] = field(default_factory=list)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    revision: int = 1
    published_at: Optional[float] = None

    def to_record(self) -> Dict[str, Any]:
        record = {
            "workflow_id": self.workflow_id,
            "goal": self.goal,
            "context": neutral_context(self.context),
            "obligations": deepcopy(self.obligations),
            "steps": deepcopy(self.steps),
            "budget": self.budget.to_record(),
            "revision": self.revision,
        }
        if self.published_at is not None:
            record["published_at"] = self.published_at
        return record

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "WorkflowEnvelope":
        return cls(
            workflow_id=str(record.get("workflow_id") or ""),
            goal=str(record.get("goal") or ""),
            context=neutral_context(record.get("context") or {}),
            obligations=deepcopy(record.get("obligations") or []),
            steps=deepcopy(record.get("steps") or []),
            budget=ExecutionBudget.from_record(record.get("budget")),
            revision=int(record.get("revision") or 0),
            published_at=record.get("published_at"),
        )


@dataclass(frozen=True)
class WorkflowEvidence:
    artifacts: Dict[str, Any] = field(default_factory=dict)
    interpretations: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    states: Dict[str, str] = field(default_factory=dict)

    def to_record(self) -> Dict[str, Any]:
        return {
            "artifacts": deepcopy(self.artifacts),
            "interpretations": deepcopy(self.interpretations),
            "states": dict(self.states),
        }


MandateStatus = Literal[
    "open", "claimed", "fulfilled", "failed", "cancelled"
]


def terminal_step_status(
    result_status: Any,
) -> Literal["completed", "waiting", "blocked", "failed"]:
    """Normalize agent envelopes at the durable step boundary."""
    status = str(result_status or "").lower()
    if status in {"success", "completed", "complete"}:
        return "completed"
    if status in {"waiting", "yield", "hitl"}:
        return "waiting"
    if status == "blocked":
        return "blocked"
    return "failed"


@dataclass(frozen=True)
class EffectIntentDecision:
    decision: Literal["allow", "redirect", "already_satisfied"]
    reason: str
    missing_evidence: tuple[str, ...] = ()
    supporting_evidence: tuple[str, ...] = ()

    @classmethod
    def from_response(cls, content: str):
        text = str(content or "").strip()
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Effect intent review must be valid JSON") from exc
        decision = str(data.get("decision") or "").lower()
        if decision not in {"allow", "redirect", "already_satisfied"}:
            raise ValueError(
                "Effect intent decision must be allow, redirect, or already_satisfied"
            )
        reason = str(data.get("reason") or "").strip()
        if not reason:
            raise ValueError("Effect intent decision requires a reason")
        missing = data.get("missing_evidence") or []
        if not isinstance(missing, list):
            raise ValueError("missing_evidence must be a list")
        supporting = data.get("supporting_evidence") or []
        if not isinstance(supporting, list):
            raise ValueError("supporting_evidence must be a list")
        if decision == "already_satisfied" and not supporting:
            raise ValueError("already_satisfied requires supporting_evidence")
        return cls(
            decision=cast(
                Literal["allow", "redirect", "already_satisfied"], decision
            ),
            reason=reason,
            missing_evidence=tuple(str(item) for item in missing if str(item)),
            supporting_evidence=tuple(
                str(item) for item in supporting if str(item)
            ),
        )


@dataclass(frozen=True)
class DependencyAuthorization:
    decision: Literal["allow", "block"]
    reason: str

    @classmethod
    def from_response(cls, content: str):
        text = str(content or "").strip()
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Dependency authorization must be valid JSON") from exc
        decision = str(data.get("decision") or "").lower()
        if decision not in {"allow", "block"}:
            raise ValueError("Dependency authorization must be allow or block")
        reason = str(data.get("reason") or "").strip()
        if not reason:
            raise ValueError("Dependency authorization requires a reason")
        return cls(cast(Literal["allow", "block"], decision), reason)


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    agent_id: str
    expires_at: float


@dataclass(frozen=True)
class FulfillmentRecord:
    agent_id: str
    result: Dict[str, Any]


@dataclass(frozen=True)
class CapabilityMandate:
    mandate_id: str
    workflow_id: str
    requester_agent_id: str
    requester_step_id: str
    capability: str
    question: str
    context: Dict[str, Any]
    status: MandateStatus
    created_at: float
    updated_at: float
    claim: Optional[ClaimRecord] = None
    fulfillment: Optional[FulfillmentRecord] = None
    error: Optional[str] = None

    def claimed(self, claim_id: str, agent_id: str, expires_at: float, now: float):
        if self.status != "open":
            raise ValueError("Only an open capability mandate can be claimed")
        return replace(
            self,
            status="claimed",
            updated_at=now,
            claim=ClaimRecord(claim_id, agent_id, expires_at),
        )

    def renewed(self, expires_at: float, now: float):
        if self.status != "claimed" or self.claim is None:
            raise ValueError("Only a claimed capability mandate can be renewed")
        return replace(
            self,
            updated_at=now,
            claim=replace(self.claim, expires_at=expires_at),
        )

    def fulfilled(self, agent_id: str, result: Dict[str, Any], now: float):
        if self.status != "claimed":
            raise ValueError("Only a claimed capability mandate can be fulfilled")
        return replace(
            self,
            status="fulfilled",
            updated_at=now,
            claim=None,
            fulfillment=FulfillmentRecord(agent_id, deepcopy(result)),
        )

    def failed(self, reason: str, now: float):
        if self.status not in {"open", "claimed"}:
            raise ValueError("Only an active capability mandate can fail")
        return replace(
            self,
            status="failed",
            updated_at=now,
            claim=None,
            error=reason,
        )

    def reopened(self, now: float):
        if self.status != "claimed":
            raise ValueError("Only a claimed capability mandate can be reopened")
        return replace(self, status="open", updated_at=now, claim=None)

    def cancelled(self, reason: str, now: float):
        if self.status not in {"open", "claimed"}:
            return self
        return replace(
            self,
            status="cancelled",
            updated_at=now,
            claim=None,
            error=reason,
        )

    @classmethod
    def open(
        cls,
        *,
        mandate_id: str,
        workflow_id: str,
        requester_agent_id: str,
        requester_step_id: str,
        capability: str,
        question: str,
        context: Optional[Dict[str, Any]],
        now: float,
    ) -> "CapabilityMandate":
        return cls(
            mandate_id=mandate_id,
            workflow_id=workflow_id,
            requester_agent_id=requester_agent_id,
            requester_step_id=requester_step_id,
            capability=capability,
            question=question,
            context=neutral_context(context),
            status="open",
            created_at=now,
            updated_at=now,
        )

    def to_record(self) -> Dict[str, Any]:
        """Serialize to the existing Redis shape for rolling compatibility."""
        record: Dict[str, Any] = {
            "id": self.mandate_id,
            "workflow_id": self.workflow_id,
            "requester_agent_id": self.requester_agent_id,
            "requester_step_id": self.requester_step_id,
            "capability": self.capability,
            "question": self.question,
            "context": neutral_context(self.context),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.claim is not None:
            record.update({
                "claimed_by": self.claim.agent_id,
                "claim_id": self.claim.claim_id,
                "claim_expires_at": self.claim.expires_at,
            })
        if self.fulfillment is not None:
            record.update({
                "fulfilled_by": self.fulfillment.agent_id,
                "result": deepcopy(self.fulfillment.result),
            })
        if self.error:
            record["error"] = self.error
        return record

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "CapabilityMandate":
        claim = None
        if record.get("claim_id"):
            claim = ClaimRecord(
                claim_id=str(record["claim_id"]),
                agent_id=str(record.get("claimed_by") or ""),
                expires_at=float(record.get("claim_expires_at") or 0),
            )
        fulfillment = None
        if "result" in record:
            fulfillment = FulfillmentRecord(
                agent_id=str(record.get("fulfilled_by") or ""),
                result=deepcopy(record.get("result") or {}),
            )
        return cls(
            mandate_id=str(record.get("id") or ""),
            workflow_id=str(record.get("workflow_id") or ""),
            requester_agent_id=str(record.get("requester_agent_id") or ""),
            requester_step_id=str(record.get("requester_step_id") or ""),
            capability=str(record.get("capability") or ""),
            question=str(record.get("question") or ""),
            context=neutral_context(record.get("context") or {}),
            status=cast(MandateStatus, str(record.get("status") or "open")),
            created_at=float(record.get("created_at") or 0),
            updated_at=float(record.get("updated_at") or 0),
            claim=claim,
            fulfillment=fulfillment,
            error=str(record.get("error")) if record.get("error") else None,
        )
