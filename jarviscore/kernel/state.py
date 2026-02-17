"""
KernelState — Pydantic model for checkpoint/resume.

Serializable via model_dump_json() / model_validate_json() for
Redis-backed crash recovery.
"""

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class KernelState(BaseModel):
    """
    Serializable state for the kernel's OODA loop.

    Persisted to Redis via save_checkpoint() for crash recovery.
    The kernel can resume from any checkpoint by loading the state
    and continuing the OODA loop from where it left off.
    """

    workflow_id: str = ""
    step_id: str = ""
    task: str = ""
    status: Literal["active", "waiting", "completed", "failed"] = "active"
    turn: int = 0
    phase: str = "discovery"

    system_prompt: str = ""
    context: Dict[str, Any] = Field(default_factory=dict)

    # Tool execution history (for audit trail and prompt building)
    tool_history: List[Dict[str, Any]] = Field(default_factory=list)
    scratchpad_notes: List[str] = Field(default_factory=list)

    # Budget tracking (mirrors lease state for checkpoint)
    thinking_tokens_used: int = 0
    action_tokens_used: int = 0
    total_cost_usd: float = 0.0

    # Error tracking
    error: Optional[str] = None
    failure_ledger: List[Dict[str, Any]] = Field(default_factory=list)

    # Timestamps
    started_at: float = Field(default_factory=time.time)
    last_checkpoint_at: Optional[float] = None

    # Final output
    output: Optional[Any] = None
    code: Optional[str] = None
