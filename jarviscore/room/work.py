"""
Agents working in a room: goals run on the room's current version and come
back as a proposal.

``Room.for_mesh`` installs ``RoomSource`` so a goal can name a room as its
workspace. ``ask`` runs the goal on the room's head; every agent step works on
its own copy of those files, and the run's final changes are filed as one
proposal that people review like any other. While it runs, each step's
progress is written to the room's event log for everyone watching.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import uuid4

from jarviscore.execution.workspace import SourceRef, SourceSnapshot

from jarviscore.room.ledger import RoomLedger
from jarviscore.room.room import ROOM_PROVIDER, Proposal, Room


_GENERATED_ID = re.compile(r"^(.+)-[0-9a-f]{8}$")


class RoomSource:
    """Workspace source adapter: ``{"provider": "room", "locator": <room>, "revision": <version>}``."""

    def __init__(self, blob_storage, ledger: RoomLedger):
        self._blob_storage = blob_storage
        self._ledger = ledger

    async def capture(self, source: SourceRef) -> SourceSnapshot:
        room = Room(source.locator, blob_storage=self._blob_storage, ledger=self._ledger)
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


def install(mesh, room: Room) -> None:
    """Let goals on this mesh use rooms stored where ``room`` is stored."""
    adapters = mesh.config.setdefault("workspace_source_adapters", {})
    adapters.setdefault(ROOM_PROVIDER, RoomSource(room.store.blob_storage, room.ledger))


async def ask(
    room: Room,
    mesh,
    goal: str,
    *,
    asked_by: str,
    revision_of: str = "",
    plan_template: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    poll_interval: float = 0.5,
) -> AskResult:
    head = room.head()
    workflow_id = f"room-{room.id}-{uuid4().hex[:8]}"
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
        task = (
            f"{goal}\n\nA previous attempt ({revision_of}) was rejected by "
            f"{previous.decided_by or 'a reviewer'}: {previous.reason or 'no reason given'}. "
            "Address that and redo the work on the current files."
        )
    room.note("ask.started", by=asked_by, goal=goal, workflow_id=workflow_id,
              version=head.version, revision_of=revision_of)
    cursor: Dict[str, int] = {}
    watcher = asyncio.create_task(
        _report_steps(room, mesh, workflow_id, poll_interval, cursor),
        name=f"room-{room.id}-progress",
    )
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
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        await _report_steps_once(room, mesh, workflow_id, cursor)

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
    authors = []
    for step, _ in changed.values():
        who = _role_of(mesh, str(step.get("claimed_by") or "")) or str(step.get("capability") or "")
        if who and who not in authors:
            authors.append(who)
    return deltas, authors


def _role_of(mesh, agent_id: str) -> str:
    """A readable name for whoever ran a step: its role, local or remote."""
    agent_id = agent_id.split(":", 1)[0]
    if not agent_id:
        return ""
    for agent in getattr(mesh, "agents", []):
        if agent.agent_id == agent_id:
            return agent.role
    remote = getattr(getattr(mesh, "_p2p_coordinator", None), "_remote_agent_registry", {})
    role = (remote.get(agent_id) or {}).get("role")
    if role:
        return str(role)
    # An agent on a node this one cannot see: generated ids are "<role>-<8 hex>".
    match = _GENERATED_ID.match(agent_id)
    return match.group(1) if match else agent_id


async def _report_steps(room: Room, mesh, workflow_id: str, interval: float,
                        cursor: Dict[str, int]) -> None:
    while True:
        await _report_steps_once(room, mesh, workflow_id, cursor)
        await asyncio.sleep(interval)


async def _report_steps_once(room: Room, mesh, workflow_id: str, cursor: Dict[str, int]) -> None:
    """Relay new entries of the workflow's own ledger: complete and in order, not sampled."""
    store = mesh._redis_store
    get_ledger = getattr(store, "get_ledger_full", None)
    if not callable(get_ledger):
        return
    entries = get_ledger(workflow_id)
    for entry in entries[cursor.get("seen", 0):]:
        event = str(entry.get("event") or "")
        if event == "dag_published":
            definition = store.get_workflow_definition(workflow_id) or {}
            room.note("plan.ready", workflow_id=workflow_id, steps=[
                {"step": s.get("id"), "capability": s.get("capability", ""),
                 "task": s.get("task", ""), "depends_on": s.get("depends_on", [])}
                for s in definition.get("steps", [])
            ])
        elif event == "plan_template_rejected":
            room.note("plan.rejected", workflow_id=workflow_id, error=entry.get("error", ""))
        elif event.startswith("step_"):
            room.note(f"step.{event[len('step_'):]}", workflow_id=workflow_id,
                      step=entry.get("step_id", ""),
                      by=_role_of(mesh, str(entry.get("agent_id") or "")),
                      **{k: entry[k] for k in ("error", "reason") if entry.get(k)})
    cursor["seen"] = len(entries)
