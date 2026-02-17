"""
6E: Human-in-the-Loop — HumanTask model and AdaptiveHITLPolicy.

The kernel pauses execution when human approval or input is needed.
The AdaptiveHITLPolicy decides when to escalate based on configurable
triggers: confidence thresholds, risk scores, and reason codes.
"""

import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field


class HumanTask(BaseModel):
    """
    A request for human input or approval.

    Created by the kernel when the HITL policy triggers.
    Persisted to Redis via RedisContextStore.create_hitl_request().
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    type: Literal["approval", "exception", "input_request", "notification"] = "approval"
    description: str = ""
    status: str = "created"
    channel: str = "email"
    assigned_to: Optional[str] = None
    request_payload: Dict[str, Any] = Field(default_factory=dict)
    user_response: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


@dataclass
class AdaptiveHITLPolicy:
    """
    Decides when the kernel should pause for human input.

    Triggers:
    - enabled=False → never escalate (default)
    - confidence < max_confidence → escalate (agent not sure enough)
    - risk_score > min_risk_score → escalate (action too risky)
    - reason_code in reason_codes → escalate (specific conditions)

    Usage:
        policy = AdaptiveHITLPolicy(enabled=True, max_confidence=0.8)
        should, reason = policy.should_escalate(confidence=0.5)
        if should:
            # Create HumanTask and yield
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
            (should_escalate, reason_string)
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
