"""
Status Manager - Tracks workflow and step execution status

Simplified from integration-agent
"""
import logging
import time
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    """Step execution status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class StatusManager:
    """
    Tracks status of workflow steps.

    Simplified from integration-agent's version.
    Removes: P2P status sync, persistent storage
    Keeps: In-memory status tracking
    """

    def __init__(self):
        """Initialize status manager."""
        self.statuses: Dict[str, Dict[str, Any]] = {}
        logger.info("Status manager initialized")

    def update(
        self,
        step_id: str,
        status: str,
        error: Optional[str] = None,
        output: Optional[Any] = None
    ):
        """
        Update step status.

        Args:
            step_id: Step identifier
            status: New status (pending, in_progress, completed, failed)
            error: Optional error message if failed
            output: Optional output data if completed
        """
        if step_id not in self.statuses:
            self.statuses[step_id] = {
                'step_id': step_id,
                'created_at': time.time()
            }

        self.statuses[step_id].update({
            'status': status,
            'updated_at': time.time(),
            'error': error,
            'output': output
        })

        logger.debug(f"Status updated: {step_id} -> {status}")

    def get(self, step_id: str) -> Optional[Dict[str, Any]]:
        """
        Get status for a step.

        Args:
            step_id: Step identifier

        Returns:
            Status dictionary or None if not found
        """
        return self.statuses.get(step_id)

    def is_completed(self, step_id: str) -> bool:
        """Check if step is completed."""
        status = self.get(step_id)
        return status and status.get('status') == 'completed'

    def is_failed(self, step_id: str) -> bool:
        """Check if step has failed."""
        status = self.get(step_id)
        return status and status.get('status') == 'failed'

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        """Get all tracked statuses."""
        return self.statuses.copy()

    def clear(self):
        """Clear all statuses."""
        self.statuses.clear()
        logger.debug("Status manager cleared")
