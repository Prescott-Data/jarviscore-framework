"""
Agents working in a room: goals run on the room's current version and come
back as a proposal.

``Room.for_mesh`` installs ``RoomSource`` so a goal can name a room as its
workspace. ``ask`` runs the goal on the room's head; every agent step works on
its own copy of those files, and the run's final changes are filed as one
proposal that people review like any other. The room's history records who
asked and which workflow does the work; the steps' progress stays in that
workflow's own ledger (``Room.progress``).

Work runs as the person who asked: their connected accounts, their access.
Every use of a connected system is recorded against the workflow, and work
that used anyone's connection to a system the room does not share is *held*:
its proposal and summary are for the asker alone until they release them.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import uuid4

from jarviscore.auth.people import Person
from jarviscore.execution.workspace import SourceRef, SourceSnapshot
from jarviscore.room.room import ROOM_PROVIDER, Proposal, Room, _who


class RoomSource:
    """Workspace source adapter: ``{"provider": "room", "locator": "<tenant>/<room>", "revision": <version>}``."""

    def __init__(self, blob_storage, redis_store):
        self._blob_storage = blob_storage
        self._redis_store = redis_store

    async def capture(self, source: SourceRef) -> SourceSnapshot:
        tenant, _, room_id = source.locator.partition("/")
        room = Room(room_id, tenant=tenant, blob_storage=self._blob_storage,
                    redis_store=self._redis_store)
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
    #: The person the work is held for (it used their private access), or "".
    held_for: str = ""
    #: Every connected system the work used, and whose access: [{"provider", "person"}].
    sources: List[Dict[str, str]] = None


#: What the room does with the work, for the planner: proposing is the room's job,
#: so a request that says "return it as a proposal" is not an extra step to plan.
ROOM_WORK_CONTRACT = (
    "This work is on the room's files. Put new work in a new file with a clear name, and "
    "change an existing file only when the request is about that file. Every file written "
    "in the room's folder is part of the change: the room files what changed as a proposal "
    "for people to review, so no step needs to propose, present or deliver the changed files."
)

#: How much of an earlier attempt a revision is shown, per file and in all.
_EARLIER_FILE_CHARS, _EARLIER_TOTAL_CHARS = 8000, 16000


def short_title(goal: str, limit: int = 80) -> str:
    """A proposal title from a request: its first sentence, cut at a word."""
    first = " ".join(str(goal or "").strip().split("\n\n", 1)[0].split())
    for stop in (". ", "? ", "! "):
        if stop in first:
            first = first.split(stop, 1)[0] + stop.strip()
            break
    if len(first) <= limit:
        return first
    return first[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


async def _earlier_attempt(room: Room, previous: Proposal) -> str:
    """What a revised proposal wrote, for the agents redoing it: its files, and their text."""
    paths = sorted(path for path, change in previous.changes.items() if change)
    if not paths:
        return ""
    if previous.held_for:
        # Held work came from someone's private access: its text is theirs alone.
        return (f"The earlier attempt wrote {', '.join(paths)}; it is held for its asker, so its "
                "text is not shown here.")
    parts = [f"The earlier attempt wrote {', '.join(paths)}. Keep the work in the same "
             f"file{'s' if len(paths) > 1 else ''}, starting from what it wrote:"]
    budget = _EARLIER_TOTAL_CHARS
    for path in paths:
        try:
            text = (await room._blob(previous.changes[path]["blob_path"])).decode("utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            parts.append(f"--- {path}: not text, not shown ---")
            continue
        shown = text[: min(_EARLIER_FILE_CHARS, max(0, budget))]
        budget -= len(shown)
        cut = "" if len(shown) == len(text) else "\n[… cut]"
        parts.append(f"--- {path}, as the earlier attempt wrote it ---\n{shown}{cut}")
    return "\n".join(parts)


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
    asked_by: Person,
    revision_of: str = "",
    plan_template: Optional[Dict[str, Any]] = None,
    timeout: Optional[float] = None,
    workflow_id: str = "",
    title: str = "",
    follows: str = "",
    takes: Optional[List[str]] = None,
) -> AskResult:
    room.require(asked_by, "editor", "ask for work")
    from jarviscore.auth.spending import Spending

    Spending(room.redis_store).check(asked_by.key)   # SpendCapReached: their allowance is used up
    head = room.head()
    workflow_id = workflow_id or new_workflow_id(room.id)
    task = goal
    room_context: Dict[str, Any] = {"id": room.id, "tenant": room.tenant, "asked_by": asked_by.id,
                                    "asked_by_name": asked_by.display, "version": head.version}
    if revision_of:
        previous = room.proposal(revision_of)
        room_context["feedback"] = {
            "proposal": revision_of,
            "decision": previous.status,
            "by": room.name_of(previous.decided_by) if previous.decided_by else "",
            "reason": previous.reason,
        }
        if previous.status == "conflicted":
            task = (
                f"{goal}\n\nA previous attempt ({revision_of}) could not be merged: "
                f"{', '.join(previous.conflicts) or 'its files'} changed in the meantime. "
                "Redo the work on the current files."
            )
        elif previous.status == "open":
            task = f"{goal}\n\nThis revises an earlier attempt ({revision_of}), which is not in the room's files yet."
        else:
            task = (
                f"{goal}\n\nA previous attempt ({revision_of}) was rejected by "
                f"{room_context['feedback']['by'] or 'a reviewer'}: {previous.reason or 'no reason given'}. "
                "Address that and redo the work."
            )
        earlier = await _earlier_attempt(room, previous)
        if earlier:
            task = f"{task}\n\n{earlier}"
    task = f"{task}\n\n{ROOM_WORK_CONTRACT}"
    room.note("ask.started", **_who(asked_by), goal=goal, workflow_id=workflow_id,
              version=head.version, revision_of=revision_of, title=title or short_title(goal),
              **({"follows": follows, "takes": list(takes or [])} if follows else {}))
    try:
        # Submitted, not executed: the work belongs to the mesh and goes on if this
        # process stops; whichever process is running then finishes it (``resume``).
        await mesh.submit_goal(
            task,
            workflow_id=workflow_id,
            context={
                "workspace_source": {
                    "provider": ROOM_PROVIDER,
                    "locator": room.key,
                    "revision": str(head.version),
                },
                "room": room_context,
                # The room's memory scope: unique across tenants.
                "room_id": room.key,
                # Steps use the asker's own accounts (jarviscore.auth.principal).
                "acting_for": asked_by.key,
            },
            plan_template=plan_template,
            timeout=timeout,
        )
        result = await _wait(room, mesh, workflow_id, timeout)
    except asyncio.CancelledError:
        raise  # this process is stopping, not the work
    except BaseException as exc:
        if isinstance(exc, TimeoutError):
            # Nobody is waiting for it any more: stop it rather than let it change things later.
            mesh.cancel_goal(workflow_id, reason="the room stopped waiting for it")
        room.note("ask.failed", **_who(asked_by), workflow_id=workflow_id,
                  error=f"{type(exc).__name__}: {exc}")
        raise
    return await finish(room, mesh, workflow_id, result)


async def finish(room: Room, mesh, workflow_id: str, result: Dict[str, Any]) -> Optional[AskResult]:
    """File what finished work in ``room`` changed as one proposal, and record that it finished.

    Safe to call more than once and from several processes: the work is
    finished once, and a finish interrupted by a restart is completed by the
    next (``resume``). Returns None if it was already finished.
    """
    started = _started(room, workflow_id)
    if started is None:
        raise KeyError(f"No work {workflow_id} was asked for in room {room.id}")
    lock, holder = f"{room.key}:finishing:{workflow_id}", uuid4().hex
    while not room.redis_store.take_lease(lock, holder, 300):
        await asyncio.sleep(0.1)
    try:
        if _ended(room, workflow_id):
            return None
        asked_by = room.identities.get(room.tenant, started.get("by", "")) or Person(
            room.tenant, started.get("by", ""), started.get("by_name", ""))
        sources = room.redis_store.workflow_sources(workflow_id)
        held_for = asked_by.id if room.private_sources(workflow_id) else ""
        if not held_for and started.get("revision_of"):
            try:
                # Redoing work held for this person keeps it theirs until they release it.
                revised = room.proposal(started["revision_of"])
                held_for = asked_by.id if revised.held_for == asked_by.id else ""
            except KeyError:
                held_for = ""
        steps = result.get("steps") or []
        proposal = None
        revising = started.get("revision_of", "")
        replaced_by = room.overtaken_by(revising) if revising else ""
        if replaced_by:
            # The team took another version of the same work while this one ran.
            summary = f"Not filed: {revising} was already replaced by {replaced_by}."
            room.note("ask.finished", **_who(asked_by), workflow_id=workflow_id,
                      status="superseded", summary=summary, proposal="", held_for="")
            return AskResult(workflow_id, "superseded", None, summary, result, "", sources)
        # Stopped work proposes nothing: whoever stopped it did not want its changes.
        deltas, authors = ([], []) if result.get("status") == "cancelled" else \
            await _final_deltas(room, mesh, workflow_id, steps)
        if deltas and not room.can(asked_by, "editor"):
            # The asker was removed, or lost the right to propose, while it ran.
            room.note("ask.failed", **_who(asked_by), workflow_id=workflow_id,
                      error=f"{asked_by.display} can no longer propose changes in this room")
            return None
        if deltas:
            proposal = await room.propose_deltas(
                deltas,
                base_version=int(started.get("version") or 0),
                author=", ".join(authors) or "agents",
                asked_by=asked_by,
                title=started.get("title") or short_title(started.get("goal", "")),
                workflow_id=workflow_id,
                revision_of=started.get("revision_of", ""),
                held_for=held_for,
                sources=sources,
            )
        summary = str(result.get("result_summary") or "")
        room.note("ask.finished", **_who(asked_by), workflow_id=workflow_id,
                  status=result.get("status"), summary=summary,
                  proposal=proposal.id if proposal else "", held_for=held_for)
        return AskResult(workflow_id, str(result.get("status")), proposal, summary, result,
                         held_for, sources)
    finally:
        room.redis_store.release_lease(lock, holder)


def _started(room: Room, workflow_id: str) -> Optional[Dict[str, Any]]:
    return next((e for e in room.events() if e.get("type") == "ask.started"
                 and e.get("workflow_id") == workflow_id), None)


def _ended(room: Room, workflow_id: str) -> bool:
    return any(e.get("type") in ("ask.finished", "ask.failed") and e.get("workflow_id") == workflow_id
               for e in room.events())


def unfinished(room: Room) -> List[Dict[str, Any]]:
    """The ``ask.started`` events of work that has not finished or failed."""
    running: Dict[str, Dict[str, Any]] = {}
    for event in room.events():
        workflow = event.get("workflow_id", "")
        if event.get("type") == "ask.started" and workflow:
            running[workflow] = event
        elif event.get("type") in ("ask.finished", "ask.failed"):
            running.pop(workflow, None)
    return list(running.values())


async def resume(room: Room, mesh, workflow_id: str, *, timeout: Optional[float] = None,
                 lost_after: float = 900.0) -> Optional[AskResult]:
    """Wait for work started in ``room`` by a process that has since stopped, and finish it.

    Work whose plan never reached the mesh (its process stopped while planning)
    is recorded as failed once ``lost_after`` seconds have passed.
    """
    started = _started(room, workflow_id)
    if started is None or _ended(room, workflow_id):
        return None
    definition = room.redis_store.get_workflow_definition(workflow_id)
    if definition is None:
        # Still being planned (the mesh's planner does that, not the process that asked):
        # wait for the plan, up to ``lost_after`` from when the work was asked for.
        left = float(started.get("at") or 0) + lost_after - time.time()
        if left > 0:
            definition = await mesh._wait_for_workflow_definition(workflow_id, left)
        if definition is None:
            if _ended(room, workflow_id):
                return None
            room.note("ask.failed", by=started.get("by", ""), by_name=started.get("by_name", ""),
                      workflow_id=workflow_id, error="the work was lost before it started; ask again")
            return None
    try:
        result = await _wait(room, mesh, workflow_id, timeout)
    except TimeoutError as exc:
        mesh.cancel_goal(workflow_id, reason="the room stopped waiting for it")
        room.note("ask.failed", by=started.get("by", ""), by_name=started.get("by_name", ""),
                  workflow_id=workflow_id, error=f"TimeoutError: {exc}")
        return None
    return await finish(room, mesh, workflow_id, result)


async def _wait(room: Room, mesh, workflow_id: str, timeout: Optional[float]) -> Dict[str, Any]:
    """Wait until the work is done. Work paused for a person is not done: it
    goes on once they answer (``HITLQueue.resolve`` resumes it)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout if timeout is not None else None

    def left() -> Optional[float]:
        return None if deadline is None else max(0.0, deadline - loop.time())

    definition = room.redis_store.get_workflow_definition(workflow_id) \
        or await mesh._wait_for_workflow_definition(workflow_id, left())
    if definition is None:
        planning = room.redis_store.get_workflow_planning_status(workflow_id) or {}
        if planning.get("status") == "failed":
            raise RuntimeError(f"the agents could not plan this: {planning.get('error') or 'no reason given'}")
        raise TimeoutError("the agents did not make a plan in time")
    while True:
        result = await mesh._wait_for_workflow_terminal(workflow_id, definition, left())
        if result.get("status") != "waiting":
            return result
        if deadline is not None and loop.time() >= deadline:
            raise TimeoutError(f"the work waited for a person for more than {timeout:.0f}s")
        await asyncio.sleep(float(mesh.config.get("distributed_poll_interval", 2.0)))


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
