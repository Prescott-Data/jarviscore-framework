"""
jarviscore.contracts.meeting_note
===================================
Canonical schema for all meeting notes produced by agents or the dashboard.

Every meeting note written to disk (meetings/*.json) or returned from
/api/meetings/* MUST conform to MeetingNote. This replaces the loose
norm dict aliasing in app.py and gives agents a typed output shape.

Supported meeting types:
    shift_kickoff  — daily shift briefing
    standup        — async agent status update
    scrum          — cross-team sprint sync
    retro          — retrospective
    l10            — Level 10 meeting (founder-led)
    founder        — ad-hoc founder-initiated discussion
    general        — fallback for unclassified meetings
"""

from __future__ import annotations

import uuid
import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class MeetingType(str, Enum):
    shift_kickoff = "shift_kickoff"
    standup       = "standup"
    scrum         = "scrum"
    retro         = "retro"
    l10           = "l10"
    founder       = "founder"
    general       = "general"


class DiscussionEntry(BaseModel):
    """A single point raised during the discussion phase."""
    agent: str
    point: str


class ActionItem(BaseModel):
    """A follow-up action owned by a specific agent or person."""
    owner: str                          # agent role or person name
    task: str                           # description of the action
    deadline: Optional[str] = None      # ISO time or human "09:00"

    @field_validator("owner", "task", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> str:
        return str(v or "").strip()


class MeetingNote(BaseModel):
    """
    Canonical meeting note — single source of truth for all agent + UI
    meeting representations.

    Persisted as:  meetings/{id}.json
    Served by:     GET /api/meetings and GET /api/meetings/{id}
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str
    type: str = MeetingType.general.value   # stored as string for JSON compat
    team: str = ""
    # ── When / Who ────────────────────────────────────────────────────────────
    date: str = Field(
        default_factory=lambda: datetime.date.today().isoformat()
    )
    participants: List[str] = Field(default_factory=list)
    agenda: List[str] = Field(default_factory=list)

    # ── Content ───────────────────────────────────────────────────────────────
    discussion: List[DiscussionEntry] = Field(default_factory=list)
    resolutions: List[str] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    summary: str = ""
    notes: str = ""       # raw unstructured notes or transcript
    report: str = ""      # full markdown formatted report (for UI rendering)

    # ── Metadata ──────────────────────────────────────────────────────────────
    created_at: Optional[str] = Field(
        default_factory=lambda: datetime.datetime.utcnow().isoformat() + "Z"
    )
    created_by: Optional[str] = None

    # ── Computed (read-only, for API responses) ───────────────────────────────
    @property
    def action_items_count(self) -> int:
        return len(self.action_items)

    def to_list_entry(self) -> Dict[str, Any]:
        """
        Compact representation for GET /api/meetings list endpoint.
        Keeps only fields needed for the meeting row card.
        """
        return {
            "id":                self.id,
            "title":             self.title,
            "type":              self.type,
            "team":              self.team,
            "date":              self.date,
            "participants":      self.participants,
            "summary":           self.summary,
            "action_items_count": self.action_items_count,
        }

    def to_detail(self) -> Dict[str, Any]:
        """
        Full representation for GET /api/meetings/{id} detail endpoint.
        """
        return self.model_dump()


class MeetingNoteCreate(BaseModel):
    """
    Request body for POST /api/meetings (dashboard or agent creating a meeting).
    A subset of MeetingNote — id and timestamps are server-generated.
    """
    title: str
    type: str = MeetingType.general.value
    team: str = ""
    date: Optional[str] = None
    participants: List[str] = Field(default_factory=list)
    agenda: List[str] = Field(default_factory=list)
    discussion: List[DiscussionEntry] = Field(default_factory=list)
    resolutions: List[str] = Field(default_factory=list)
    action_items: List[ActionItem] = Field(default_factory=list)
    summary: str = ""
    notes: str = ""
    report: str = ""
    created_by: Optional[str] = None

    def to_meeting_note(self) -> MeetingNote:
        """Promote to full MeetingNote, stamping id and created_at."""
        data = self.model_dump()
        data["id"] = uuid.uuid4().hex[:12]
        data["created_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        if not data.get("date"):
            data["date"] = datetime.date.today().isoformat()
        return MeetingNote(**data)


def normalise_meeting(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Coerce a raw dict (from disk or legacy agent output) into a
    MeetingNote-compatible dict, handling all known field aliases.

    Used in /api/meetings/normalised to provide a consistent shape
    regardless of which agent wrote the file.
    """
    action_items_raw = (
        raw.get("action_items")
        or raw.get("actions")
        or []
    )
    # Normalise action item field names
    action_items = []
    for a in action_items_raw:
        if isinstance(a, dict):
            action_items.append({
                "owner":    a.get("owner") or a.get("agent") or a.get("assigned_to") or "",
                "task":     a.get("task") or a.get("description") or "",
                "deadline": a.get("deadline") or a.get("due") or None,
            })

    return {
        "id":                raw.get("id", ""),
        "title":             raw.get("title", "Untitled Meeting"),
        "type":              raw.get("type", MeetingType.general.value),
        "team":              raw.get("team", ""),
        "date":              raw.get("date", ""),
        "participants":      raw.get("participants") or raw.get("attendees") or [],
        "agenda":            raw.get("agenda", []),
        "discussion":        raw.get("discussion", []),
        "resolutions":       raw.get("resolutions", []),
        "action_items":      action_items,
        "action_items_count": len(action_items),
        "summary":           raw.get("summary") or raw.get("outcome") or "",
        "notes":             raw.get("notes") or raw.get("transcript") or "",
        "report":            raw.get("report", ""),
        "created_at":        raw.get("created_at"),
        "created_by":        raw.get("created_by"),
    }
