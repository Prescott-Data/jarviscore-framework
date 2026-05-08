"""
jarviscore.kernel.defaults.research_flow
==========================================
Explicit research state machine for the ResearcherSubAgent.

Ported from integration-agent-javiscore — provides phase-based tool gating
to prevent tool misuse loops and enforce disciplined research progression.

Phases:
    INIT       → Entry point, cast a wide net
    SEARCHING  → Active search, collecting URLs
    EXTRACTING → Deep-reading promising leads
    VERIFYING  → Cross-referencing findings
    DIAGNOSING → Recovery from stalls or failures
    STUCK      → Exhausted options, must publish what we have
    DONE       → Research complete, findings published
"""

from enum import Enum
from typing import Any, Dict


class ResearchPhase(str, Enum):
    """Research workflow phases — ordered by progression."""
    INIT = "init"
    SEARCHING = "searching"
    EXTRACTING = "extracting"
    VERIFYING = "verifying"
    DIAGNOSING = "diagnosing"
    DONE = "done"
    STUCK = "stuck"


class ResearchFlow:
    """
    Research state machine snapshot helper.

    Usage:
        state.internal_variables["research_flow"] = ResearchFlow.snapshot(
            ResearchPhase.SEARCHING, "batch_discovery"
        )
    """

    @staticmethod
    def snapshot(phase: ResearchPhase, reason: str) -> Dict[str, Any]:
        """Create a serializable phase snapshot for state persistence."""
        return {"phase": phase.value, "reason": reason}
