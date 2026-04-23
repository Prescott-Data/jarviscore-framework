"""
jarviscore.contracts — Canonical data contracts for all framework entities.

Every object that crosses a boundary (file → API, agent → kernel, Redis → UI)
must be validated against one of these models.

Importing:
    from jarviscore.contracts import MeetingNote, Task, TaskCreate, TaskStatus
    from jarviscore.contracts import HITLRequest, HITLResolution, HITLPolicy, HITLDecision
    from jarviscore.contracts import HumanTask, AdaptiveHITLPolicy   # kernel-facing
"""

from .meeting_note import (
    MeetingNote,
    MeetingNoteCreate,
    DiscussionEntry,
    ActionItem,
    MeetingType,
)

from .task import (
    Task,
    TaskCreate,
    TaskUpdate,
    TaskStatus,
    TaskPriority,
)

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
    # Meeting Notes
    "MeetingNote",
    "MeetingNoteCreate",
    "DiscussionEntry",
    "ActionItem",
    "MeetingType",
    # Tasks
    "Task",
    "TaskCreate",
    "TaskUpdate",
    "TaskStatus",
    "TaskPriority",
    # HITL
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
