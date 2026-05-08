"""
jarviscore.hitl — Human-in-the-Loop escalation queue.
=====================================================

Native framework HITL infrastructure.  Agents call ``self.hitl.request()``
when a step needs human review.  Items are persisted to **both** Redis
(typed ``HITLRequest``) and flat JSON files (for file-based dashboard
polling), so the system works with or without Redis.

The Mesh injects an ``HITLQueue`` instance into every agent at start()
time as ``agent.hitl`` — the same lifecycle as ``agent.mailbox``.

Quick start (inside any AutoAgent)::

    item_id = self.hitl.request(
        title="Review Q2 deck before sending",
        content=deck_summary,
        urgency="high",
        context={"file": "output/q2_deck.pptx"},
    )
    decision = await self.hitl.wait(item_id, timeout=3600)
    if decision and decision.is_approved:
        await self._send_deck()

Contracts re-exported for convenience::

    from jarviscore.hitl import HITLRequest, HITLResolution, HITLDecision
"""

from jarviscore.contracts.hitl import (
    HITLCategory,
    HITLDecision,
    HITLPolicy,
    HITLRequest,
    HITLResolution,
    HITLStatus,
    HITLType,
    APPROVED_DECISIONS,
    REJECTED_DECISIONS,
    normalize_hitl_decision,
)
from .queue import HITLQueue

__all__ = [
    # Queue (the main thing agents use)
    "HITLQueue",
    # Contracts (re-exported for convenience)
    "HITLCategory",
    "HITLDecision",
    "HITLPolicy",
    "HITLRequest",
    "HITLResolution",
    "HITLStatus",
    "HITLType",
    "APPROVED_DECISIONS",
    "REJECTED_DECISIONS",
    "normalize_hitl_decision",
]
