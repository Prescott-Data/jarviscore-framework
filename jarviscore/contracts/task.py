"""
jarviscore.contracts.task
===========================
Canonical schema for all tasks created by the founder, agents, or workflows.

Replaces the three overlapping Pydantic models in dashboard/app.py:
  - TaskCreate (line 739)    — missing due_date, watchers, subtasks
  - TaskCreateV2 (line 3344) — superset of the above, inconsistently used
  - TaskUpdate (line 847)    — only status + note

Source of truth for:
  - tasks/{id}.json          (dashboard flat store)
  - tasks/{assignee}/{id}.json (agent queue)
  - Redis hash task:{id}
  - /api/tasks/* responses
"""

from __future__ import annotations

import uuid
import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class TaskStatus(str, Enum):
    pending         = "pending"
    in_progress     = "in_progress"
    awaiting_review = "awaiting_review"
    done            = "done"
    cancelled       = "cancelled"


class TaskPriority(str, Enum):
    urgent  = "urgent"
    high    = "high"
    normal  = "normal"
    low     = "low"


class SubTask(BaseModel):
    """Lightweight subtask attached to a parent task."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str
    status: TaskStatus = TaskStatus.pending
    assignee: Optional[str] = None


class Task(BaseModel):
    """
    Canonical task — single source of truth for all task representations.

    Persisted as:  tasks/{id}.json  and  tasks/{assignee}/{id}.json
    Served by:     GET /api/tasks and GET /api/tasks/{id}
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str
    description: str = ""
    context: str = ""                # additional context for the agent

    # ── Assignment ────────────────────────────────────────────────────────────
    assignee: str                    # agent role or team name
    priority: TaskPriority = TaskPriority.normal
    status: TaskStatus = TaskStatus.pending

    # ── Scheduling ────────────────────────────────────────────────────────────
    due_date: Optional[str] = None   # ISO date YYYY-MM-DD

    # ── Audit ─────────────────────────────────────────────────────────────────
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.utcnow().isoformat()
    )
    created_by: str = "founder"
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    output_summary: Optional[str] = None  # agent-written completion note

    # ── Collaboration ─────────────────────────────────────────────────────────
    watchers: List[str] = Field(default_factory=list)
    subtasks: List[SubTask] = Field(default_factory=list)
    comments: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Read-only derived (for list API responses) ────────────────────────────
    comment_count: int = 0

    @field_validator("priority", mode="before")
    @classmethod
    def _coerce_priority(cls, v: Any) -> str:
        """Accept plain string, fallback to normal."""
        s = str(v or "normal").lower()
        return s if s in {e.value for e in TaskPriority} else "normal"

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v: Any) -> str:
        s = str(v or "pending").lower()
        return s if s in {e.value for e in TaskStatus} else "pending"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for file or Redis storage."""
        return self.model_dump()


class TaskCreate(BaseModel):
    """
    Request body for POST /api/tasks/create.

    This is the single form the founder, Warden, and agents use to create tasks.
    Supersedes both the old TaskCreate and TaskCreateV2 models.
    """
    title: str
    description: str = ""
    assignee: str
    priority: str = TaskPriority.normal.value
    context: str = ""
    due_date: Optional[str] = None
    created_by: Optional[str] = None     # if None, resolved from session
    watchers: List[str] = Field(default_factory=list)
    subtasks: List[Dict[str, Any]] = Field(default_factory=list)

    def to_task(self, created_by: str = "founder") -> Task:
        """Stamp id, created_at and return a full Task."""
        resolved_by = self.created_by or created_by
        return Task(
            id=uuid.uuid4().hex[:8],
            title=self.title,
            description=self.description,
            assignee=self.assignee,
            priority=self.priority,
            context=self.context,
            due_date=self.due_date,
            created_at=datetime.datetime.utcnow().isoformat(),
            created_by=resolved_by,
            watchers=self.watchers,
            subtasks=[SubTask(**s) if isinstance(s, dict) else s for s in self.subtasks],
        )


class TaskUpdate(BaseModel):
    """
    Request body for PATCH /api/tasks/{id} and PATCH /api/tasks/{id}/status.

    All fields optional — only provided fields are updated.
    """
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    output_summary: Optional[str] = None
    note: str = ""                        # legacy compat — treated as output_summary
    watchers: Optional[List[str]] = None
