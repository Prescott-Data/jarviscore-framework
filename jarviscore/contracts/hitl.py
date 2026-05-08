"""
jarviscore.contracts.hitl
===========================
Canonical HITL (Human-in-the-Loop) contracts — typed request, resolution,
policy, and decision models.

Design aligned with the CA (collaboration_agent_javiscore2) HitlOrchestrator:
  - HITLRequest   ← created by kernel/orchestrator, stored in Redis
  - HITLResolution← written by human reviewer, polled by kernel
  - HITLPolicy    ← declares who can resolve and by what rule
  - HITLDecision  ← the typed set of valid human decisions

Fixes the gap in jarviscore where redis_store.create_hitl_request()
and resolve_hitl_request() returned plain untyped dicts, and the kernel
read .get("decision") with no validation.

Usage:
    # Kernel creating a request
    req = HITLRequest(
        workflow_id=state.workflow_id,
        step_id=state.step_id,
        type=HITLType.approval,
        description="Approve outbound email before sending",
        targets=["reviewer", "founder"],
        channels=["dashboard", "slack"],
        payload={"draft": email_draft},
    )
    redis_store.create_hitl_request_typed(req)

    # Kernel polling for resolution
    resolution = redis_store.get_hitl_resolution(workflow_id, step_id)
    if resolution and resolution.is_approved:
        # proceed
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class HITLDecision(str, Enum):
    """
    Valid human decisions on a HITL request.

    Approved set:  approve | approved | continue | resume | yes
    Rejected set:  reject  | rejected | deny     | denied | no
    Other:         defer   | escalate
    """
    approve  = "approve"
    approved = "approved"
    continue_ = "continue"
    resume   = "resume"
    yes      = "yes"
    reject   = "reject"
    rejected = "rejected"
    deny     = "deny"
    denied   = "denied"
    no       = "no"
    defer    = "defer"
    escalate = "escalate"


class HITLType(str, Enum):
    """What kind of human interaction is requested."""
    approval      = "approval"        # binary approve/reject
    exception     = "exception"       # unexpected condition requiring judgement
    input_request = "input_request"   # open-ended text input needed
    notification  = "notification"    # inform only, no action required


class HITLCategory(str, Enum):
    """
    The ONLY valid reasons an agent may escalate to human review.

    Anything outside these three categories must be handled autonomously.
    Agents that call hitl.request() without a valid category will be rejected
    at the queue layer.

    auth_required   — A credential, token, or Nexus connection is missing or
                      has expired. The agent cannot authenticate to proceed.
                      Example: Nexus returns 401, .env key absent, OAuth expired.

    data_required   — Critical input data is missing and CANNOT be obtained
                      via API, scraping, or any autonomous means. Only the
                      founder can supply it (e.g. bank statement CSV, private
                      contract text, unreleased pricing).

    critical_action — The next action is irreversible, financially material,
                      or reputationally sensitive enough that the agent should
                      not execute without explicit founder sign-off.
                      Example: sending an investor email, publishing a press
                      release, making a payment, deleting production data.
    """
    auth_required   = "auth_required"
    data_required   = "data_required"
    critical_action = "critical_action"


class HITLStatus(str, Enum):
    """Lifecycle state of a HITL request."""
    pending   = "pending"
    resolved  = "resolved"
    expired   = "expired"
    cancelled = "cancelled"


# ── Convenience sets (mirrors CA's normalize_decision) ───────────────────────

APPROVED_DECISIONS = {
    HITLDecision.approve,
    HITLDecision.approved,
    HITLDecision.continue_,
    HITLDecision.resume,
    HITLDecision.yes,
}

REJECTED_DECISIONS = {
    HITLDecision.reject,
    HITLDecision.rejected,
    HITLDecision.deny,
    HITLDecision.denied,
    HITLDecision.no,
}


def normalize_hitl_decision(raw: str) -> HITLDecision:
    """
    Coerce a freeform human decision string to a canonical HITLDecision.

    Falls back to HITLDecision.defer on unrecognised input.
    """
    normalized = str(raw or "").strip().lower()
    for d in HITLDecision:
        if d.value == normalized:
            return d
    return HITLDecision.defer


# ── Policy ────────────────────────────────────────────────────────────────────

class HITLPolicy(BaseModel):
    """
    Declares who can resolve a HITL gate and by what consensus rule.

    Mirrors CA's hitl.policy schema in workflow step definitions:
    {
        "hitl": {
            "required": true,
            "targets": ["reviewer", "founder"],
            "channels": ["dashboard", "slack"],
            "policy": {"type": "any_of"}
        }
    }
    """
    type: Literal["any_of", "all_of", "quorum", "ordered"] = "any_of"
    targets: List[str] = Field(default_factory=list)    # user/agent IDs
    channels: List[str] = Field(default_factory=list)   # slack | email | dashboard
    timeout_seconds: Optional[int] = None               # None = no timeout
    description: str = ""


# ── Request ───────────────────────────────────────────────────────────────────

class HITLRequest(BaseModel):
    """
    A HITL request created by the kernel when human input is needed.

    Persisted in Redis as:  hitl_request:{workflow_id}:{step_id}
    The Redis hash fields are a flat JSON representation of this model.

    After creation, the kernel polls get_hitl_resolution() until
    the request is resolved or expired.
    """

    request_id: str = Field(
        default_factory=lambda: f"hitl-{uuid.uuid4().hex[:8]}"
    )
    workflow_id: str
    step_id: str

    type: HITLType = HITLType.approval
    status: HITLStatus = HITLStatus.pending

    # Mandatory: why this escalation is valid. Must be one of the three
    # permitted categories — queue.py rejects requests without a valid one.
    category: HITLCategory = HITLCategory.critical_action

    description: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)

    # Who can resolve and how
    targets: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
    policy: HITLPolicy = Field(default_factory=HITLPolicy)

    # Metadata from HitlOrchestrator.build_declared_request()
    mode: Literal["declared", "adaptive"] = "declared"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    created_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def to_redis_mapping(self) -> Dict[str, str]:
        """Flatten for Redis HSET — all values must be strings."""
        import json
        d = self.model_dump()
        return {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in d.items()}


# ── Resolution ────────────────────────────────────────────────────────────────

class HITLResolution(BaseModel):
    """
    A human (or automated) resolution of a HITL request.

    Written back to the same Redis key by the dashboard or API endpoint.
    The kernel polls for this by looking for status == "resolved".
    """

    request_id: str
    decision: HITLDecision
    resolved_by: Optional[str] = None       # user name / agent id
    note: Optional[str] = None              # optional comment from reviewer
    resolved_at: float = Field(default_factory=time.time)

    @property
    def is_approved(self) -> bool:
        return self.decision in APPROVED_DECISIONS

    @property
    def is_rejected(self) -> bool:
        return self.decision in REJECTED_DECISIONS

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> Optional["HITLResolution"]:
        """
        Construct from a raw Redis hgetall dict.
        Returns None if the request has not been resolved yet.
        """
        if raw.get("status") != HITLStatus.resolved.value:
            return None
        raw_decision = str(raw.get("decision", "")).strip().lower()
        decision = normalize_hitl_decision(raw_decision)
        return cls(
            request_id=str(raw.get("request_id", "")),
            decision=decision,
            resolved_by=raw.get("resolved_by"),
            note=raw.get("note"),
            resolved_at=float(raw.get("resolved_at", time.time())),
        )
