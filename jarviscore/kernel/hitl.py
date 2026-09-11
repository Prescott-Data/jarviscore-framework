"""
jarviscore.kernel.hitl — Human-in-the-Loop kernel integration layer.

Provides:
  - HumanTask: lightweight kernel-facing alias for HITLRequest
  - AdaptiveHITLPolicy: policy engine for autonomous escalation decisions

The canonical typed contracts live in jarviscore.contracts.hitl.
This module imports and re-exports them for backward compat, and adds
the AdaptiveHITLPolicy decision engine which is kernel-internal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ── Re-export the canonical contracts ────────────────────────────────────────
from jarviscore.contracts.hitl import (
    HITLRequest,
    HITLResolution,
    HITLPolicy,
    HITLDecision,
    HITLStatus,
    HITLType,
    APPROVED_DECISIONS,
    REJECTED_DECISIONS,
    normalize_hitl_decision,
)

# ── Kernel-facing alias ───────────────────────────────────────────────────────
# HumanTask is the name the kernel uses internally. It is HITLRequest.
# Agents and external code should use HITLRequest from contracts directly.
HumanTask = HITLRequest


# ── Adaptive Policy Engine ────────────────────────────────────────────────────

@dataclass
class AdaptiveHITLPolicy:
    """
    Decides when the kernel should pause for human input.

        HITL is admissible only for one of the canonical human-only categories.
        Confidence, token spend, and routine execution failure never qualify.

    Default: disabled — agents never escalate unless you turn this on.

    Usage:
        policy = AdaptiveHITLPolicy(enabled=True, max_confidence=0.8)
        should, reason = policy.should_escalate(confidence=0.5)
        if should:
            req = HITLRequest(
                workflow_id=wf_id,
                step_id=step_id,
                description=reason,
                type=HITLType.approval,
            )
            redis_store.create_hitl_request_typed(req)
    """

    enabled: bool = False
    reason_codes: List[str] = field(default_factory=list)
    max_confidence: float = 0.8
    min_risk_score: float = 0.7

    def should_escalate(
        self,
        reason_code: Optional[str] = None,
        confidence: Optional[float] = None,
        risk_score: Optional[float] = None,
        autonomous_paths_exhausted: bool = False,
        human_exclusive: bool = False,
    ) -> Tuple[bool, str]:
        """
        Evaluate whether to escalate to a human.

        Returns:
            (should_escalate: bool, reason_string: str)
        """
        if not self.enabled:
            return False, ""

        allowed = {"auth_required", "data_required", "critical_action"}
        category = str(reason_code or "")
        if category not in allowed:
            return False, ""
        if self.reason_codes and category not in self.reason_codes:
            return False, ""
        if category == "data_required" and not (
            autonomous_paths_exhausted and human_exclusive
        ):
            return False, ""
        return True, f"category:{category}"



__all__ = [
    # Kernel-facing alias (preferred name inside kernel code)
    "HumanTask",
    # Full contracts (for external code and the kernel equally)
    "HITLRequest",
    "HITLResolution",
    "HITLPolicy",
    "HITLDecision",
    "HITLStatus",
    "HITLType",
    "APPROVED_DECISIONS",
    "REJECTED_DECISIONS",
    "normalize_hitl_decision",
    # Policy engine
    "AdaptiveHITLPolicy",
]
