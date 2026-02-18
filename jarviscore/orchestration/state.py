"""
WorkflowState — Serializable workflow execution state for crash recovery.

Phase 7A: Persisted to Redis (workflow_state:{wf_id}) so the engine can
resume after a crash without re-running completed steps.

Zombie detection: running_steps maps step_id → start_time so the engine
can detect steps that are "running" in Redis state but have no live
asyncio.Task (i.e., the process crashed mid-execution).
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Set


@dataclass
class WorkflowState:
    """
    Serializable state for a running workflow.

    Persisted to Redis after every reactive-loop iteration so the engine
    can recover from crashes without re-running completed steps.

    Attributes:
        workflow_id:      Identifies the workflow this state belongs to.
        total_steps:      How many steps the workflow has in total.
        processed_steps:  Step IDs that completed successfully.
        running_steps:    Step IDs currently in-flight → their start timestamp.
                          Used for zombie detection on resume.
        failed_steps:     Step IDs that finished with failure status.
        waiting_steps:    Step IDs paused for HITL → the human-readable reason.
        status:           Overall workflow lifecycle status.
    """

    workflow_id: str
    total_steps: int = 0
    processed_steps: Set[str] = field(default_factory=set)
    running_steps: Dict[str, float] = field(default_factory=dict)
    failed_steps: Set[str] = field(default_factory=set)
    waiting_steps: Dict[str, str] = field(default_factory=dict)
    status: str = "pending"  # pending | running | completed | failed | waiting

    # ------------------------------------------------------------------
    # Status Queries
    # ------------------------------------------------------------------

    def is_complete(self) -> bool:
        """
        True when every step has reached a terminal state.

        Terminal = processed (success) | failed | waiting (HITL pause).
        A workflow is not complete while steps are still running.
        """
        terminal = (
            len(self.processed_steps)
            + len(self.failed_steps)
            + len(self.waiting_steps)
        )
        return terminal >= self.total_steps and not self.running_steps

    def has_waiting_steps(self) -> bool:
        """True if any step is paused for human input."""
        return bool(self.waiting_steps)

    def has_failed_steps(self) -> bool:
        """True if any step finished with failure."""
        return bool(self.failed_steps)

    # ------------------------------------------------------------------
    # Serialization (for Redis persistence)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for Redis storage."""
        return {
            "workflow_id": self.workflow_id,
            "total_steps": self.total_steps,
            "processed_steps": sorted(self.processed_steps),
            "running_steps": self.running_steps,
            "failed_steps": sorted(self.failed_steps),
            "waiting_steps": self.waiting_steps,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkflowState":
        """Deserialize from a dict (Redis load path)."""
        return cls(
            workflow_id=data["workflow_id"],
            total_steps=data.get("total_steps", 0),
            processed_steps=set(data.get("processed_steps", [])),
            running_steps=data.get("running_steps", {}),
            failed_steps=set(data.get("failed_steps", [])),
            waiting_steps=data.get("waiting_steps", {}),
            status=data.get("status", "pending"),
        )
