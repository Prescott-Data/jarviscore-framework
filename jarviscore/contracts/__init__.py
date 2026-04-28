"""
jarviscore.contracts — Framework-level data contracts.

Only contracts that are GENERIC to any multi-agent orchestration system
belong here. Domain-specific schemas (meetings, tasks, etc.) belong in
the consuming application's domain layer (e.g., your_app/contracts/).

Importing:
    from jarviscore.contracts import HITLRequest, HITLResolution, HITLPolicy, HITLDecision
"""

from .hitl import (
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

__all__ = [
    # HITL (Human-in-the-Loop) — core framework primitive
    "HITLRequest",
    "HITLResolution",
    "HITLPolicy",
    "HITLDecision",
    "HITLStatus",
    "HITLType",
    "APPROVED_DECISIONS",
    "REJECTED_DECISIONS",
    "normalize_hitl_decision",
]
