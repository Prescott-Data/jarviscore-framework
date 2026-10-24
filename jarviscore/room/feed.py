"""What is happening in a room, as lines people can read.

Nothing here is stored: ``RoomFeed`` reads the room's own history and, for
each piece of work someone asked for, that workflow's ledger (its plan, who
claimed each step, what finished or got stuck). Terminals and chat surfaces
render the ``FeedItem``s it returns.

    feed = RoomFeed(room)
    while True:
        for item in feed.poll():
            print(item.text)
        await asyncio.sleep(1)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class FeedItem:
    text: str
    #: The room event type, or "progress" for a step of asked-for work.
    kind: str
    at: float = 0.0
    #: The workflow doing the work this is about, if any (chat surfaces thread on it).
    workflow_id: str = ""
    #: The proposal this is about, if any.
    proposal: str = ""
    #: Longer text that goes with the line, such as the agents' summary.
    detail: str = ""
    event: Optional[Dict[str, Any]] = None
    #: Work held for one person (it used their private access): the full line and
    #: detail are for them only, and everyone else sees ``withheld`` instead.
    held_for: str = ""
    withheld: str = ""
    #: Where the feed is once this item is delivered: save it (``RoomFeed(room, cursor)``)
    #: only after the item reached its surface, and nothing is lost on failure.
    cursor: Optional[Dict[str, Any]] = None


def describe(event: Dict[str, Any]) -> str:
    """One line for a room event."""
    kind = event.get("type", "")
    by = event.get("by_name") or event.get("by") or "someone"
    proposal = event.get("proposal", "")
    paths = event.get("paths") or []
    files = f"{len(paths)} file{'s' if len(paths) != 1 else ''}"
    if kind == "room.created":
        source = f" from {event['source']}" if event.get("source") else ""
        return f"{by} opened the room with {event.get('files', 0)} files{source} (v1)"
    if kind == "ask.started" and event.get("follows"):
        return f"the agents take up what the team added: {event.get('title') or event.get('goal', '')}"
    if kind == "ask.started":
        again = f", redoing {event['revision_of']}" if event.get("revision_of") else ""
        return f"{by} asked: {event.get('goal', '')}{again}"
    if kind == "ask.queued":
        return f"{by}'s addition is kept for the work in progress; the agents get it with that work's result"
    if kind == "ask.finished" and event.get("status") == "superseded":
        return f"this version was not filed: {event.get('summary', '')}"
    if kind == "ask.finished":
        tail = f" → {proposal} to review" if proposal else " with no changes to the files"
        return f"the agents finished ({event.get('status')}){tail}"
    if kind == "ask.failed":
        return f"the work stopped: {event.get('error', '')}"
    if kind == "proposal.opened":
        author = event.get("author") or by
        ask = f" for {by}" if author != by else ""
        title = f": {event['title']}" if event.get("title") else ""
        return f"▲ {proposal} proposed by {author}{ask}{title} ({files}, on v{event.get('base_version')})"
    if kind == "proposal.released":
        title = f": {event['title']}" if event.get("title") else ""
        return f"▲ {by} released {proposal}{title} ({files}) for review"
    if kind == "proposal.accepted":
        merged = f", merged over {event['merged_over']} newer" if event.get("merged_over") else ""
        return f"✓ {by} accepted {proposal} → v{event.get('version')}{merged}"
    if kind == "proposal.rejected":
        return f"✗ {by} rejected {proposal}: {event.get('reason', '')}"
    if kind == "proposal.conflicted":
        return f"⚠ {proposal} conflicts with newer changes to {', '.join(paths)}"
    if kind == "member.changed":
        role, who = event.get("role", ""), event.get("person_name") or event.get("person", "")
        return f"{by} removed {who} from the room" if role == "removed" else f"{by} made {who} {role}"
    if kind == "room.visibility":
        whom = "everyone in the team" if event.get("visibility") == "tenant" else "its members only"
        return f"{by} opened the room to {whom}"
    if kind == "room.connectors":
        shared = ", ".join(event.get("shared") or []) or "none"
        return f"{by} set the systems whose data the room shares: {shared}"
    return f"{kind} by {by}"


def withheld(event: Dict[str, Any]) -> str:
    """The line everyone but the asker sees for work held for its asker."""
    by = event.get("by_name") or event.get("by") or "someone"
    if event.get("type") == "proposal.opened":
        return (f"▲ {event.get('proposal')} is ready for {by}: it used {by}'s private access, "
                f"so {by} sees it first and can release it to the room")
    return (f"the agents finished {by}'s request; it used {by}'s private access, "
            f"so the result is shown to {by} first")


_STEP_VERBS = {
    "step_claimed": "took", "step_completed": "finished", "step_failed": "could not finish",
    "step_blocked": "is blocked on", "step_requeued": "handed back", "step_resumed": "resumed",
    "step_claim_expired": "lost hold of", "step_epoch_continued": "kept working on",
    "step_waiting": "is waiting for a person on",
}


class RoomFeed:
    """Reads a room's history and the progress of the work asked for in it."""

    def __init__(self, room, state: Optional[Dict[str, Any]] = None):
        self.room = room
        state = state or {}
        #: Last room event read.
        self.after: str = state.get("after", "")
        #: Workflow id -> {"after": last ledger entry read, "roles": step -> role}.
        self.following: Dict[str, Dict[str, Any]] = dict(state.get("following") or {})

    def state(self) -> Dict[str, Any]:
        """Where the feed is, to save and resume from (``RoomFeed(room, state)``)."""
        return json.loads(json.dumps({"after": self.after, "following": self.following}))

    def skip_history(self) -> None:
        """Start from now: only what happens next is returned."""
        events = self.room.events()
        self.after = events[-1]["seq"] if events else ""

    def poll(self) -> List[FeedItem]:
        """Everything new since the last poll, in order."""
        items: List[FeedItem] = []
        for event in self.room.events(self.after):
            kind = event.get("type", "")
            workflow = event.get("workflow_id", "")
            if workflow in self.following:
                # The steps come before what they led to (the proposal, the finish).
                items.extend(self._progress(workflow))
            self.after = event["seq"]
            if kind in ("ask.finished", "ask.failed"):
                self.following.pop(workflow, None)
            detail = str(event.get("summary") or "") if kind == "ask.finished" else ""
            if kind == "ask.started" and workflow:
                self.following.setdefault(workflow, {"after": "", "roles": {}, "asker": event.get("by", ""),
                                                     "asker_name": event.get("by_name", "")})
            held = str(event.get("held_for") or "") if kind in ("ask.finished", "proposal.opened") else ""
            items.append(FeedItem(describe(event), kind, float(event.get("at") or 0),
                                  workflow, event.get("proposal", ""), detail, event,
                                  held_for=held, withheld=withheld(event) if held else "",
                                  cursor=self.state()))
        for workflow in list(self.following):
            items.extend(self._progress(workflow))
        return items

    def _progress(self, workflow_id: str) -> List[FeedItem]:
        followed = self.following[workflow_id]
        items = []
        entries = self.room.progress(workflow_id, followed["after"])
        # Once the work has used someone's private access, why a step failed or is
        # blocked may quote that data: the reason is for the asker only.
        private = bool(entries) and bool(self.room.private_sources(workflow_id))
        for entry in entries:
            followed["after"] = entry["_id"]
            line = self._describe_progress(workflow_id, entry, followed["roles"])
            if not line:
                continue
            bare = self._describe_progress(workflow_id, entry, dict(followed["roles"]), reason=False)
            held = followed.get("asker", "") if private and bare != line else ""
            items.append(FeedItem(line, "progress", _entry_time(entry), workflow_id, event=entry,
                                  held_for=held, withheld=bare if held else "", cursor=self.state()))
        return items

    def _describe_progress(self, workflow_id: str, entry: Dict[str, Any],
                           roles: Dict[str, str], reason: bool = True) -> str:
        event = str(entry.get("event") or "")
        step = str(entry.get("step_id") or "")
        if event == "dag_published":
            definition = self.room.redis_store.get_workflow_definition(workflow_id) or {}
            steps = " → ".join(f"{s.get('id')} ({s.get('capability', '')})"
                               for s in definition.get("steps", []))
            return f"plan: {steps}" if steps else ""
        if event == "plan_template_rejected":
            return "the plan was refused" + (f": {entry.get('error', '')}" if reason else "")
        if event == "workflow_cancelled":
            return "the work was stopped" + (f": {entry.get('reason', '')}" if reason and entry.get("reason") else "")
        if event == "planning_failed":
            return "planning failed" + (f": {entry.get('error', '')}" if reason else "")
        if event == "step_claimed":
            roles[step] = str(entry.get("role") or entry.get("agent_id") or "")
        if event in _STEP_VERBS:
            who = roles.get(step) or "an agent"
            why = entry.get("blockers") or entry.get("reason") or entry.get("error")
            tail = f": {why}" if why and reason else ""
            return f"{who} {_STEP_VERBS[event]} {step}{tail}"
        return ""


def _entry_time(entry: Dict[str, Any]) -> float:
    try:
        if entry.get("timestamp"):
            return float(entry["timestamp"])
        # A stream id starts with the milliseconds it was written at.
        return int(str(entry.get("_id", "0")).split("-")[0]) / 1000
    except ValueError:
        return 0.0


def stamp(at: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(at or time.time()))
