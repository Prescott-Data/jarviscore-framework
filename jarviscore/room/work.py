"""
Agents working in a room: goals run on the room's current version and come
back as a proposal.

``Room.for_mesh`` installs ``RoomSource`` so a goal can name a room as its
workspace. ``ask`` runs the goal on the room's head; every agent step works on
its own copy of those files, and the run's final changes are filed as one
proposal that people review like any other. The room's history records who
asked and which workflow does the work; the steps' progress stays in that
workflow's own ledger (``Room.progress``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import uuid4

from jarviscore.execution.workspace import SourceRef, SourceSnapshot

from jarviscore.room.room import ROOM_PROVIDER, Proposal, Room


class RoomSource:
    """Workspace source adapter: ``{"provider": "room", "locator": <room>, "revision": <version>}``."""

    def __init__(self, blob_storage, redis_store):
        self._blob_storage = blob_storage
        self._redis_store = redis_store

    async def capture(self, source: SourceRef) -> SourceSnapshot:
        room = Room(source.locator, blob_storage=self._blob_storage, redis_store=self._redis_store)
        version = int(source.revision) if source.revision else room.head().version
        return await room.snapshot(version)


@dataclass
class AskResult:
    """What came of asking the room's agents for something."""

    workflow_id: str
    status: str
    proposal: Optional[Proposal]
    summary: str
    result: Dict[str, Any]


def new_workflow_id(room_id: str) -> str:
    return f"room-{room_id}-{uuid4().hex[:8]}"


def install(mesh, room: Room) -> None:
    """Let goals on this mesh use rooms stored where ``room`` is stored."""
    adapters = mesh.config.setdefault("workspace_source_adapters", {})
    adapters.setdefault(ROOM_PROVIDER, RoomSource(room.store.blob_storage, room.redis_store))


async def ask(
    room: Room,
    mesh,
    goal: str,
    *,
    asked_by: str,
    revision_of: str = "",
    plan_template: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    workflow_id: str = "",
) -> AskResult:
    room.require(asked_by, "editor", "ask for work")
    head = room.head()
    workflow_id = workflow_id or new_workflow_id(room.id)
    task = goal
    room_context: Dict[str, Any] = {"id": room.id, "asked_by": asked_by, "version": head.version}
    if revision_of:
        previous = room.proposal(revision_of)
        room_context["feedback"] = {
            "proposal": revision_of,
            "decision": previous.status,
            "by": previous.decided_by,
            "reason": previous.reason,
        }
        if previous.status == "conflicted":
            task = (
                f"{goal}\n\nA previous attempt ({revision_of}) could not be merged: "
                f"{', '.join(previous.conflicts) or 'its files'} changed in the meantime. "
                "Redo the work on the current files."
            )
        else:
            task = (
                f"{goal}\n\nA previous attempt ({revision_of}) was rejected by "
                f"{previous.decided_by or 'a reviewer'}: {previous.reason or 'no reason given'}. "
                "Address that and redo the work on the current files."
            )
    room.note("ask.started", by=asked_by, goal=goal, workflow_id=workflow_id,
              version=head.version, revision_of=revision_of)
    try:
        result = await mesh.execute_goal(
            task,
            workflow_id=workflow_id,
            context={
                "workspace_source": {
                    "provider": ROOM_PROVIDER,
                    "locator": room.id,
                    "revision": str(head.version),
                },
                "room": room_context,
                # With memory_scope_field="room_id", every agent working in the
                # room shares the room's memory across workflows.
                "room_id": room.id,
                # Steps use the asker's own accounts (jarviscore.auth.principal).
                "acting_for": asked_by,
            },
            plan_template=plan_template,
            timeout=timeout,
        )
    except BaseException as exc:
        room.note("ask.failed", by=asked_by, workflow_id=workflow_id,
                  error=f"{type(exc).__name__}: {exc}")
        raise

    steps = result.get("steps") or []
    deltas, authors = await _final_deltas(room, mesh, workflow_id, steps)
    proposal = None
    if deltas:
        proposal = await room.propose_deltas(
            deltas,
            base_version=head.version,
            author=", ".join(authors) or "agents",
            asked_by=asked_by,
            title=goal,
            workflow_id=workflow_id,
            revision_of=revision_of,
        )
    summary = str(result.get("result_summary") or "")
    room.note("ask.finished", by=asked_by, workflow_id=workflow_id,
              status=result.get("status"), summary=summary,
              proposal=proposal.id if proposal else "")
    return AskResult(workflow_id, str(result.get("status")), proposal, summary, result)


async def _final_deltas(room: Room, mesh, workflow_id: str, steps: List[Dict[str, Any]]):
    """The cumulative deltas of completed steps that no other changing step builds on."""
    changed = {}
    for step in steps:
        step_id = str(step.get("id") or "")
        if step.get("status") != "completed" or not step_id:
            continue
        manifest = mesh._workspace_delta_manifest(
            {"output": step.get("output")}, workflow_id=workflow_id, step_id=step_id
        )
        if manifest:
            changed[step_id] = (step, manifest)
    plan = {"steps": [{"id": s.get("id"), "depends_on": s.get("depends_on", [])} for s in steps]}
    final = mesh._maximal_workspace_dependency_ids(list(changed), plan)
    deltas = [await room.store.load_delta(changed[step_id][1]) for step_id in final]
    # Deltas are cumulative, so everyone whose step changed files is in the result.
    roles = {
        entry.get("step_id"): entry.get("role") or entry.get("agent_id")
        for entry in room.progress(workflow_id) if entry.get("event") == "step_claimed"
    }
    authors = []
    for step_id, (step, _) in changed.items():
        who = roles.get(step_id) or str(step.get("capability") or "")
        if who and who not in authors:
            authors.append(who)
    return deltas, authors
