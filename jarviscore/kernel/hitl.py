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

    Triggers (any match → escalate):
      - reason_code in reason_codes
      - confidence < max_confidence   (agent not confident enough)
      - risk_score > min_risk_score   (action too risky to auto-proceed)

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
    ) -> Tuple[bool, str]:
        """
        Evaluate whether to escalate to a human.

        Returns:
            (should_escalate: bool, reason_string: str)
        """
        if not self.enabled:
            return False, ""

        # Reason code match
        if reason_code and self.reason_codes and reason_code in self.reason_codes:
            return True, f"reason_code:{reason_code}"

        # Low confidence
        if confidence is not None and confidence < self.max_confidence:
            return True, f"low_confidence:{confidence:.2f}<{self.max_confidence:.2f}"

        # High risk
        if risk_score is not None and risk_score > self.min_risk_score:
            return True, f"high_risk:{risk_score:.2f}>{self.min_risk_score:.2f}"

        return False, ""


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
