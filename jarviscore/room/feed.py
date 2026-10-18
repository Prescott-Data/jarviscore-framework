"""One readable line per room event, for terminals and chat bridges."""

from __future__ import annotations

import time
from typing import Any, Dict


def describe(event: Dict[str, Any]) -> str:
    kind = event.get("type", "")
    by = event.get("by") or "someone"
    proposal = event.get("proposal", "")
    paths = event.get("paths") or []
    files = f"{len(paths)} file{'s' if len(paths) != 1 else ''}"
    if kind == "room.created":
        source = f" from {event['source']}" if event.get("source") else ""
        return f"{by} opened the room with {event.get('files', 0)} files{source} (v1)"
    if kind == "ask.started":
        again = f", redoing {event['revision_of']}" if event.get("revision_of") else ""
        return f"{by} asked: {event.get('goal', '')}{again}"
    if kind == "plan.ready":
        steps = " → ".join(f"{s.get('step')} ({s.get('capability')})" for s in event.get("steps", []))
        return f"plan: {steps}"
    if kind == "plan.rejected":
        return f"plan template refused: {event.get('error', '')}"
    if kind.startswith("step."):
        verb = {"claimed": "took", "completed": "finished", "blocked": "is blocked on",
                "requeued": "handed back", "claim_expired": "lost hold of",
                "resumed": "resumed", "epoch_continued": "kept working on"}.get(kind[5:], kind[5:])
        who = event.get("by") or "a peer"
        extra = f": {event.get('error') or event.get('reason')}" if (
            event.get("error") or event.get("reason")) else ""
        return f"{who} {verb} {event.get('step', '')}{extra}"
    if kind == "ask.finished":
        tail = f" → {proposal} to review" if proposal else " (no changes)"
        return f"agents finished ({event.get('status')}){tail}"
    if kind == "ask.failed":
        return f"the work stopped: {event.get('error', '')}"
    if kind == "proposal.opened":
        ask = f" for {event['asked_by']}" if event.get("asked_by") not in ("", None, by) else ""
        title = f": {event['title']}" if event.get("title") else ""
        return f"▲ {proposal} proposed by {by}{ask}{title} ({files}, on v{event.get('base_version')})"
    if kind == "proposal.accepted":
        merged = f", merged over {event['merged_over']} newer" if event.get("merged_over") else ""
        return f"✓ {by} accepted {proposal} → v{event.get('version')}{merged}"
    if kind == "proposal.rejected":
        return f"✗ {by} rejected {proposal}: {event.get('reason', '')}"
    if kind == "member.changed":
        role = event.get("role", "")
        who = event.get("person", "")
        return f"{by} removed {who} from the room" if role == "removed" else f"{by} made {who} {role}"
    if kind == "proposal.conflicted":
        return f"⚠ {proposal} conflicts with newer changes to {', '.join(paths)}"
    return f"{kind} {by}"


def stamp(event: Dict[str, Any]) -> str:
    return time.strftime("%H:%M:%S", time.localtime(float(event.get("at", 0))))
