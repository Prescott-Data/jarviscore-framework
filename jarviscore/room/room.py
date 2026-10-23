"""
A room: shared work that a team's people and agents change together.

A room belongs to a tenant and holds a set of files. Its current state is an
immutable snapshot, its *head*. Nobody writes to the head directly. Agents and
people make **proposals** against a version of it; accepting one moves the head
forward. If the head moved since a proposal was made, accepting merges it: a
file only one side changed is taken, and in a text file both sides changed,
edits to different lines are both kept. Edits to the same lines that differ, or
a file deleted on one side and changed on the other, are a conflict that stops
the accept instead of overwriting anyone.

Every change to a room is one atomic transition that also records who did it
and why in the room's history, so the history is complete and every surface
reads the same account of what happened.

A room is private: only people with a role can see it or act in it. Its owner
can open it to everyone in the tenant. Every operation a person performs takes
the ``Person`` who performs it, from the surface's own authentication.

    room = Room.for_mesh(mesh, "launch", tenant="acme")
    await room.ensure({"plan.md": plan}, by=alice)
    asked = await room.ask("Fill in the risks from brief.md", asked_by=alice)
    await room.accept(asked.proposal.id, by=bob)
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4

from jarviscore.auth.people import Identities, Person
from jarviscore.execution.merge import merge_text
from jarviscore.execution.workspace import (
    BlobSnapshotStore,
    SnapshotEntry,
    SourceRef,
    SourceSnapshot,
    WorkspaceDelta,
    WorkspaceDeltaConflict,
    _register_workspace_path,
)
from jarviscore.storage.errors import RoomStateChanged

logger = logging.getLogger(__name__)

#: Provider name a goal uses to work on a room: workspace_source={"provider": "room", ...}
ROOM_PROVIDER = "room"

#: Written by checkout() so push() knows which version a local copy started from.
CHECKOUT_MARKER = ".jarviscore-room.json"

#: Never read back from a checkout: tool and build state, not work.
IGNORED_NAMES = (".git", ".venv", "__pycache__", "node_modules", ".tmp", ".DS_Store")

_ACCEPT_ATTEMPTS = 20

#: Each role can do what the ones before it can.
ROLES = ("viewer", "editor", "owner")

#: Who can see a room besides its members.
VISIBILITIES = ("members", "tenant")


class RoomPermissionError(PermissionError):
    """The person may not do this in the room."""


class RoomConflict(RuntimeError):
    """A proposal changes paths someone else changed differently since it was made."""

    def __init__(self, proposal_id: str, paths: List[str]):
        self.proposal_id = proposal_id
        self.paths = paths
        super().__init__(f"{proposal_id} conflicts with newer changes to: {', '.join(paths)}")


@dataclass(frozen=True)
class Head:
    version: int
    snapshot_id: str
    manifest_blob_path: str
    updated_by: str
    updated_at: float
    proposal_id: str = ""

    def to_record(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Head":
        return cls(**{k: record[k] for k in cls.__dataclass_fields__ if k in record})


@dataclass
class Proposal:
    id: str
    title: str
    #: Who wrote the change: agent roles, or the person's name.
    author: str
    #: The person responsible for it (who asked, or who wrote it): a person id.
    asked_by: str
    base_version: int
    base_manifest: str
    #: path -> SnapshotEntry fields of the new content, or None for a deletion.
    changes: Dict[str, Optional[Dict[str, Any]]]
    status: str = "open"
    created_at: float = field(default_factory=time.time)
    workflow_id: str = ""
    revision_of: str = ""
    decided_by: str = ""
    decided_at: float = 0.0
    reason: str = ""
    accepted_version: int = 0
    conflicts: List[str] = field(default_factory=list)
    #: Made with someone's private access: only they see it until they release it.
    held_for: str = ""
    #: Which connected systems the work used, and whose access.
    sources: List[Dict[str, str]] = field(default_factory=list)

    def to_record(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Proposal":
        return cls(**{k: record[k] for k in cls.__dataclass_fields__ if k in record})

    @property
    def paths(self) -> List[str]:
        return sorted(self.changes)


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # added | modified | deleted
    before: Optional[bytes]
    after: Optional[bytes]

    def unified(self, context: int = 3) -> str:
        """A unified diff for text; a one-line note for binary content."""
        try:
            before = (self.before or b"").decode("utf-8")
            after = (self.after or b"").decode("utf-8")
        except UnicodeDecodeError:
            return f"Binary file {self.path} {self.status}\n"
        return "".join(difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="/dev/null" if self.before is None else f"a/{self.path}",
            tofile="/dev/null" if self.after is None else f"b/{self.path}",
            n=context,
        ))


def _bytes(content) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else bytes(content)


def _who(person: Person) -> Dict[str, str]:
    """How a person appears in history events: stable id, and the name people see."""
    return {"by": person.id, "by_name": person.display}


_UNSET = object()


class Room:
    """Shared, versioned work in a tenant. See the module docstring."""

    def __init__(self, room_id: str, *, tenant: str, blob_storage, redis_store):
        _register_workspace_path(room_id, {}, label="room id")
        for label, value in (("room id", room_id), ("tenant", tenant)):
            if not value or any(c in value for c in "/{}"):
                raise ValueError(f"A {label} cannot be empty or contain '/', '{{' or '}}': {value!r}")
        self.id = room_id
        self.tenant = tenant
        #: Unique across tenants; every key of the room carries it.
        self.key = f"{tenant}/{room_id}"
        self.store = BlobSnapshotStore(blob_storage)
        #: The mesh's RedisContextStore: head, proposals, settings and history.
        self.redis_store = redis_store
        self.identities = Identities(redis_store)
        self._memory: Any = _UNSET

    @property
    def memory(self):
        """The room's team memory in Athena (``RoomMemory``), or None without Athena
        (``ATHENA_URL``). Assign your own, or None to keep none."""
        if self._memory is _UNSET:
            from jarviscore.room.memory import RoomMemory

            self._memory = RoomMemory.from_env(self)
        return self._memory

    @memory.setter
    def memory(self, value) -> None:
        self._memory = value
        self._memory_chosen = True

    def _memory_to_erase(self):
        """Where the room's memory can be: Athena when configured, and always the
        local store, which agents use when Athena is not configured."""
        from jarviscore.room.memory import LocalRoomMemory

        places = [LocalRoomMemory(self)]
        if self.memory is not None:
            places.insert(0, self.memory)
        return places

    # ── Construction ────────────────────────────────────────────────────────

    @classmethod
    def open(cls, room_id: str, *, tenant: str, redis_url: Optional[str] = None,
             settings=None) -> "Room":
        """The room as a Mesh with the same settings sees it: same Redis, same file storage."""
        from jarviscore.config.settings import Settings
        from jarviscore.storage import get_blob_storage
        from jarviscore.storage.redis_store import RedisContextStore

        settings = settings or Settings()
        url = redis_url or getattr(settings, "redis_url", None)
        if not url:
            raise ValueError("Rooms live in the mesh's Redis: set REDIS_URL")
        import redis

        store = RedisContextStore(client=redis.Redis.from_url(url, decode_responses=True))
        return cls(room_id, tenant=tenant, blob_storage=get_blob_storage(settings), redis_store=store)

    @classmethod
    def for_mesh(cls, mesh, room_id: str, *, tenant: str) -> "Room":
        """A room on a started Mesh, using its Redis and BlobStorage.

        The room can then ``ask`` the mesh's agents to work on it.
        """
        if getattr(mesh, "_blob_storage", None) is None or getattr(mesh, "_redis_store", None) is None:
            raise RuntimeError("A room needs a started Mesh with Redis and BlobStorage")
        room = cls(room_id, tenant=tenant, blob_storage=mesh._blob_storage,
                   redis_store=mesh._redis_store)
        from jarviscore.room.work import install

        install(mesh, room)
        room.mesh = mesh
        return room

    async def ask(self, goal: str, *, asked_by: Person, revision_of: str = "", **options):
        """Have the mesh's agents do ``goal`` on the room's current files, as ``asked_by``.

        Returns an ``AskResult`` whose ``proposal`` holds their changes for
        people to review, or None if they changed nothing. ``revision_of``
        names a proposal this one revises; its feedback is passed on to the
        agents. Options: ``timeout`` and ``plan_template`` (passed to
        ``Mesh.execute_goal``), ``workflow_id`` to choose the run's id.
        """
        mesh = getattr(self, "mesh", None)
        if mesh is None:
            raise RuntimeError("Use Room.for_mesh(mesh, room_id, tenant=...) to have agents work in a room")
        from jarviscore.room.work import ask

        return await ask(self, mesh, goal, asked_by=asked_by, revision_of=revision_of, **options)

    async def ensure(self, files: Optional[Mapping[str, Any]] = None, *, by: Person) -> Head:
        """Create the room with these files, owned by ``by``, if it does not exist; return its head."""
        existing = self.redis_store.get_room_head(self.key)
        if existing:
            return Head.from_record(existing)
        snapshot = await self.store.capture(self._source(1), "v1", dict(files or {}))
        return self._create(snapshot, by, files=len(snapshot.entries))

    async def ensure_from(self, snapshot: SourceSnapshot, *, by: Person) -> Head:
        """Create the room from an existing snapshot, such as a captured repository."""
        existing = self.redis_store.get_room_head(self.key)
        if existing:
            return Head.from_record(existing)
        await self.store.validate(snapshot)
        first = await self.store.compose(self._source(1), "v1", list(snapshot.entries))
        return self._create(first, by, files=len(first.entries),
                            source=f"{snapshot.source.provider}:{snapshot.source.locator}"
                                   f"@{snapshot.resolved_revision}")

    def _create(self, snapshot: SourceSnapshot, by: Person, **fields) -> Head:
        self._same_tenant(by)
        head = Head(1, snapshot.snapshot_id, snapshot.manifest_blob_path, by.id, time.time())
        meta = {"created_by": by.id, "visibility": "members", "tenant_role": "editor",
                "members": {by.id: "owner"}, "names": {by.id: by.display}, "shared_connectors": []}
        event = {"type": "room.created", "at": time.time(), "version": 1, **_who(by), **fields}
        self.redis_store.create_room(self.key, head.to_record(), meta, event)
        return Head.from_record(self.redis_store.get_room_head(self.key))

    def exists(self) -> bool:
        return self.redis_store.get_room_head(self.key) is not None

    # ── Reading (trusted code: check ``require(person, "viewer", ...)`` for people) ──

    def head(self) -> Head:
        record = self.redis_store.get_room_head(self.key)
        if not record:
            raise KeyError(f"Room {self.id!r} does not exist")
        return Head.from_record(record)

    def _source(self, version: int) -> SourceRef:
        return SourceRef(ROOM_PROVIDER, self.key, str(version))

    async def snapshot(self, version: Optional[int] = None) -> SourceSnapshot:
        """The room as it was at ``version`` (default: now)."""
        head = self.head()
        if version is None or int(version) == head.version:
            return await self.store.load(head.manifest_blob_path)
        found = await self.store.find(self._source(int(version)), f"v{int(version)}")
        if found is None:
            raise KeyError(f"Room {self.id!r} has no version {version}")
        return found

    async def read(self, path: str, version: Optional[int] = None) -> Optional[bytes]:
        for entry in (await self.snapshot(version)).entries:
            if entry.path == path:
                return await self._blob(entry.blob_path)
        return None

    async def files(self, version: Optional[int] = None) -> Dict[str, bytes]:
        snapshot = await self.snapshot(version)
        return {entry.path: await self._blob(entry.blob_path) for entry in snapshot.entries}

    async def _store(self, path: str, payload: bytes, executable: bool = False) -> Dict[str, Any]:
        """Save content once, by hash, and return its snapshot entry fields."""
        digest = hashlib.sha256(payload).hexdigest()
        blob_path = f"rooms/{self.tenant}/{self.id}/objects/{digest}"
        if await self.store.blob_storage.read(blob_path) is None:
            await self.store.blob_storage.save(blob_path, payload)
        return asdict(SnapshotEntry(path, blob_path, digest, len(payload), executable))

    async def _blob(self, blob_path: str) -> bytes:
        payload = await self.store.blob_storage.read(blob_path)
        if payload is None:
            raise FileNotFoundError(blob_path)
        return _bytes(payload)

    def proposal(self, proposal_id: str) -> Proposal:
        record = self.redis_store.get_room_proposal(self.key, proposal_id)
        if not record:
            raise KeyError(f"No proposal {proposal_id!r} in room {self.id!r}")
        return Proposal.from_record(record)

    def proposals(self, status: Optional[str] = None) -> List[Proposal]:
        return [Proposal.from_record(r) for r in self.redis_store.list_room_proposals(self.key)
                if status is None or r.get("status") == status]

    def events(self, after: str = "") -> List[Dict[str, Any]]:
        """The room's history after event ``after`` (an event's ``seq``), oldest first."""
        return self.redis_store.get_room_events(self.key, after)

    def progress(self, workflow_id: str, after: str = "") -> List[Dict[str, Any]]:
        """How the work asked for in ``workflow_id`` is going: that workflow's own ledger
        (plan published, each step claimed by whom, completed, blocked), after entry ``after``."""
        return self.redis_store.get_ledger_after(workflow_id, after)

    def note(self, kind: str, **fields) -> str:
        """Record something that happened in the room, for everyone following it."""
        return self.redis_store.append_room_event(self.key, {"type": kind, "at": time.time(), **fields})

    def private_sources(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Connected systems a piece of work used that the room does not share
        (someone's own mail, drive, CRM...): their data is for that person only."""
        shared = set(self.settings().get("shared_connectors") or [])
        return [s for s in self.redis_store.workflow_sources(workflow_id)
                if str(s.get("provider", "")).lower() not in shared]

    def audit(self, since: float = 0.0, until: Optional[float] = None) -> List[Dict[str, Any]]:
        """Everything done in the room, as records for an auditor, oldest first.

        Each record says when, who (``by`` and ``by_name``), what (``action``),
        to what (``target``), and why (``detail``: a goal, a reason, a role).
        A piece of work's records also name its ``workflow_id``, the connected
        systems it used and whose access each was (``sources``), and what its
        model use cost (``usage``). Private work's records say that it was held,
        and for whom, not what it found.
        """
        records = []
        for event in self.events():
            at = float(event.get("at") or 0)
            if at < since or (until is not None and at > until):
                continue
            kind = event.get("type", "")
            target = event.get("proposal") or event.get("person") or event.get("workflow_id") or ""
            detail = (event.get("goal") or event.get("reason") or event.get("error")
                      or event.get("role") or event.get("visibility") or "")
            if kind == "room.connectors":
                detail = ", ".join(event.get("shared") or []) or "none"
            if kind == "ask.finished":
                detail = event.get("status") or ""
            record = {"at": at, "room": self.key, "action": kind, "by": event.get("by", ""),
                      "by_name": event.get("by_name", ""), "target": target, "detail": str(detail),
                      "version": event.get("version"), "held_for": event.get("held_for") or ""}
            workflow = event.get("workflow_id") or ""
            if workflow and kind in ("ask.started", "ask.finished", "ask.failed"):
                record["workflow_id"] = workflow
                record["sources"] = self.redis_store.workflow_sources(workflow)
                if kind != "ask.started":
                    usage = self.redis_store.get_workflow_budget_usage(workflow) or {}
                    record["usage"] = {"tokens": usage.get("used_tokens", 0),
                                       "usd": usage.get("cost_usd", 0.0), "calls": usage.get("call_count", 0)}
            records.append({k: v for k, v in record.items() if v not in (None, "")})
        return records

    def visible_to(self, person: Person, proposal: Proposal) -> bool:
        """Whether ``person`` may see a proposal's contents (held work is for its asker only)."""
        return self.can(person, "viewer") and (not proposal.held_for or proposal.held_for == person.id)

    # ── Who may do what ─────────────────────────────────────────────────────

    def settings(self) -> Dict[str, Any]:
        meta = self.redis_store.get_room_meta(self.key)
        return {k: meta.get(k) for k in ("created_by", "visibility", "tenant_role", "shared_connectors")}

    def members(self) -> Dict[str, str]:
        """Person id -> role."""
        return dict(self.redis_store.get_room_meta(self.key).get("members") or {})

    def name_of(self, person_id: str) -> str:
        names = self.redis_store.get_room_meta(self.key).get("names") or {}
        return names.get(person_id) or person_id

    def role_of(self, person: Person) -> Optional[str]:
        """The person's role here, or None if they cannot see the room."""
        if person.tenant != self.tenant or not self.identities.is_active(person):
            return None
        meta = self.redis_store.get_room_meta(self.key)
        role = (meta.get("members") or {}).get(person.id)
        if role is None and meta.get("visibility") == "tenant":
            role = meta.get("tenant_role") or "editor"
        return role

    def can(self, person: Person, role: str) -> bool:
        held = self.role_of(person)
        return held is not None and ROLES.index(held) >= ROLES.index(role)

    def require(self, person: Person, role: str, action: str) -> None:
        if not isinstance(person, Person):
            raise TypeError(f"{action} needs the Person who does it, not {person!r}")
        if not self.can(person, role):
            held = self.role_of(person)
            raise RoomPermissionError(
                f"{person.display} cannot {action} in room {self.id}: "
                + (f"they are a {held}" if held else "they are not a member")
                + f" and it needs {role}"
            )

    def _same_tenant(self, person: Person) -> None:
        if not isinstance(person, Person) or person.tenant != self.tenant:
            raise RoomPermissionError(f"{person!r} is not in tenant {self.tenant}")

    def set_role(self, person: Person, role: Optional[str], *, by: Person) -> Dict[str, str]:
        """Give ``person`` a role, or None to remove them. Owners only; one owner always stays."""
        if role is not None and role not in ROLES:
            raise ValueError(f"role must be one of {ROLES} or None, not {role!r}")
        self.require(by, "owner", "change members")
        self._same_tenant(person)

        def change(meta):
            members = dict(meta.get("members") or {})
            if role is None:
                members.pop(person.id, None)
            else:
                members[person.id] = role
            if "owner" not in members.values():
                raise RoomPermissionError(f"Room {self.id} must keep at least one owner")
            names = {**(meta.get("names") or {}), person.id: person.display}
            return {**meta, "members": members, "names": names}

        meta = self.redis_store.update_room_meta(self.key, change, event={
            "type": "member.changed", "at": time.time(), **_who(by),
            "person": person.id, "person_name": person.display, "role": role or "removed"})
        return dict(meta["members"])

    def set_visibility(self, visibility: str, *, by: Person, tenant_role: str = "editor") -> None:
        """``members`` (only people with a role) or ``tenant`` (everyone in the tenant, as ``tenant_role``)."""
        if visibility not in VISIBILITIES or tenant_role not in ROLES[:2]:
            raise ValueError(f"visibility must be one of {VISIBILITIES}, tenant_role viewer or editor")
        self.require(by, "owner", "change who can see the room")
        self.redis_store.update_room_meta(
            self.key, lambda meta: {**meta, "visibility": visibility, "tenant_role": tenant_role},
            event={"type": "room.visibility", "at": time.time(), **_who(by),
                   "visibility": visibility, "tenant_role": tenant_role})

    def set_shared_connectors(self, providers: Iterable[str], *, by: Person) -> None:
        """Connected systems whose data everyone in the room may see, such as a team drive.

        Work that uses only these (or none) is shown to the room directly; work
        that used anyone's other connections is held for that person to release.
        """
        self.require(by, "owner", "change the room's shared connectors")
        providers = sorted({str(p).lower() for p in providers})
        self.redis_store.update_room_meta(
            self.key, lambda meta: {**meta, "shared_connectors": providers},
            event={"type": "room.connectors", "at": time.time(), **_who(by), "shared": providers})

    # ── Proposing ───────────────────────────────────────────────────────────

    async def propose(
        self,
        changes: Mapping[str, Any],
        *,
        by: Person,
        author: str = "",
        title: str = "",
        base_version: Optional[int] = None,
        workflow_id: str = "",
        revision_of: str = "",
    ) -> Optional[Proposal]:
        """Propose new content per path (``None`` deletes), as ``by``. None if nothing changes."""
        self.require(by, "editor", "propose changes")
        base = await self.snapshot(base_version)
        current = {entry.path: entry for entry in base.entries}
        entries: Dict[str, Optional[Dict[str, Any]]] = {}
        seen: Dict[str, str] = {}
        for raw_path, content in changes.items():
            path = _register_workspace_path(raw_path, seen, label="proposal")
            if content is None:
                if path in current:
                    entries[path] = None
                continue
            payload = _bytes(content)
            if path in current and current[path].sha256 == hashlib.sha256(payload).hexdigest():
                continue
            executable = current[path].executable if path in current else False
            entries[path] = await self._store(path, payload, executable)
        return self._open(entries, base, by, author=author or by.display, title=title,
                          workflow_id=workflow_id, revision_of=revision_of)

    async def propose_deltas(
        self,
        deltas: Iterable[WorkspaceDelta],
        *,
        base_version: int,
        asked_by: Person,
        author: str,
        title: str = "",
        workflow_id: str = "",
        revision_of: str = "",
        held_for: str = "",
        sources: Optional[List[Dict[str, str]]] = None,
    ) -> Optional[Proposal]:
        """Turn the workspace deltas of work ``asked_by`` asked for into one proposal."""
        self.require(asked_by, "editor", "propose changes")
        base = await self.snapshot(base_version)
        current = {entry.path: entry for entry in base.entries}
        entries: Dict[str, Optional[Dict[str, Any]]] = {}
        for delta in deltas:
            if delta.snapshot_id != base.snapshot_id:
                raise ValueError("Workspace delta was not made against this room version")
            for entry in (*delta.added, *delta.modified):
                change = asdict(entry)
                earlier = entries.get(entry.path, change)
                if earlier is not None and earlier["sha256"] != change["sha256"]:
                    # Parallel branches changed one file: keep both where they don't overlap.
                    combined = None
                    if entry.path in current:
                        combined = merge_text(
                            await self._blob(current[entry.path].blob_path),
                            await self._blob(earlier["blob_path"]),
                            await self._blob(change["blob_path"]),
                        )
                    if combined is None:
                        raise WorkspaceDeltaConflict(f"Agents disagree about {entry.path!r}")
                    change = await self._store(entry.path, combined, entry.executable)
                elif earlier is None:
                    raise WorkspaceDeltaConflict(f"Agents disagree about {entry.path!r}")
                entries[entry.path] = change
            for path in delta.deleted:
                if entries.get(path, None) is not None:
                    raise WorkspaceDeltaConflict(f"Agents disagree about {path!r}")
                entries[path] = None
        entries = {
            path: change for path, change in entries.items()
            if not (change is not None and path in current
                    and current[path].sha256 == change["sha256"])
            and not (change is None and path not in current)
        }
        return self._open(entries, base, asked_by, author=author, title=title,
                          workflow_id=workflow_id, revision_of=revision_of,
                          held_for=held_for, sources=list(sources or []))

    def _open(self, entries, base: SourceSnapshot, by: Person, **fields) -> Optional[Proposal]:
        if not entries:
            return None
        workflow = fields.get("workflow_id") or ""
        # Work files one proposal: finishing it again (after a restart) finds the same one.
        proposal_id = f"p-{hashlib.sha256(f'{self.key}:{workflow}'.encode()).hexdigest()[:8]}" \
            if workflow else f"p-{uuid4().hex[:8]}"
        proposal = Proposal(
            id=proposal_id,
            asked_by=by.id,
            base_version=int(base.source.revision),
            base_manifest=base.manifest_blob_path,
            changes=entries,
            **fields,
        )
        try:
            self.redis_store.room_transition(self.key, {
                "type": "proposal.opened", "at": time.time(), "proposal": proposal.id,
                "author": proposal.author, **_who(by), "title": proposal.title,
                "base_version": proposal.base_version, "paths": proposal.paths,
                "revision_of": proposal.revision_of, "workflow_id": proposal.workflow_id,
                "held_for": proposal.held_for,
            }, proposal_id=proposal.id, require_status="missing", proposal=proposal.to_record())
        except RoomStateChanged:
            return self.proposal(proposal.id)
        return proposal

    async def diff(self, proposal_id: str) -> List[FileChange]:
        """What the proposal changes, against the version it was made from."""
        proposal = self.proposal(proposal_id)
        base = {e.path: e for e in (await self.store.load(proposal.base_manifest)).entries}
        out = []
        for path in proposal.paths:
            change = proposal.changes[path]
            before = await self._blob(base[path].blob_path) if path in base else None
            after = await self._blob(change["blob_path"]) if change else None
            status = "deleted" if after is None else ("added" if before is None else "modified")
            out.append(FileChange(path, status, before, after))
        return out

    # ── Deciding ────────────────────────────────────────────────────────────

    def release(self, proposal_id: str, *, by: Person) -> Proposal:
        """Show held work to the room. Only the person it is held for can release it."""
        self.require(by, "editor", "release work")
        proposal = self.proposal(proposal_id)
        if proposal.held_for != by.id:
            raise RoomPermissionError(f"Only the person it is held for can release {proposal_id}")
        try:
            self.redis_store.room_transition(self.key, {
                "type": "proposal.released", "at": time.time(), "proposal": proposal_id, **_who(by),
                "title": proposal.title, "paths": proposal.paths, "workflow_id": proposal.workflow_id,
            }, proposal_id=proposal_id, require_status="open", proposal_fields={"held_for": ""})
        except RoomStateChanged as exc:
            raise ValueError(f"{proposal_id} is {exc.proposal_status}, not open") from exc
        return self.proposal(proposal_id)

    async def accept(self, proposal_id: str, *, by: Person) -> Head:
        """Merge an open proposal into the room. Raises RoomConflict on overlapping edits."""
        self.require(by, "editor", "accept changes")
        proposal = self.proposal(proposal_id)
        if proposal.status != "open":
            raise ValueError(f"{proposal_id} is {proposal.status}, not open")
        if proposal.held_for:
            raise RoomPermissionError(
                f"{proposal_id} used {self.name_of(proposal.held_for)}'s private access; "
                "they must release it before it can be accepted")
        # One decision at a time per line of work (a proposal and its revisions), so two
        # people accepting competing versions at once cannot both land.
        lock, holder = f"{self.key}:lineage:{self.lineage(proposal_id)[-1]}", uuid4().hex
        while not self.redis_store.take_lease(lock, holder, 60):
            await asyncio.sleep(0.05)
        try:
            return await self._accept(proposal_id, by)
        finally:
            self.redis_store.release_lease(lock, holder)

    async def _accept(self, proposal_id: str, by: Person) -> Head:
        proposal = self.proposal(proposal_id)
        if proposal.status != "open":
            raise ValueError(f"{proposal_id} is {proposal.status}, not open")
        overtaken = self.overtaken_by(proposal_id)
        if overtaken:
            raise ValueError(
                f"{proposal_id} revises an earlier version that {overtaken} already replaced: "
                "ask for changes to the current version instead")
        base = {e.path: e for e in (await self.store.load(proposal.base_manifest)).entries}

        for _ in range(_ACCEPT_ATTEMPTS):
            head = self.head()
            current = {e.path: e for e in (await self.store.load(head.manifest_blob_path)).entries}
            conflicts: List[str] = []
            line_merged: Dict[str, Dict[str, Any]] = {}
            for path, change in proposal.changes.items():
                head_sha = current[path].sha256 if path in current else None
                base_sha = base[path].sha256 if path in base else None
                our_sha = change["sha256"] if change else None
                if head_sha in (base_sha, our_sha):
                    continue
                if None not in (head_sha, base_sha, our_sha):
                    # Both sides edited this file since the proposal's version.
                    combined = merge_text(
                        await self._blob(base[path].blob_path),
                        await self._blob(change["blob_path"]),
                        await self._blob(current[path].blob_path),
                    )
                    if combined is not None:
                        line_merged[path] = await self._store(
                            path, combined, current[path].executable)
                        continue
                conflicts.append(path)
            if conflicts:
                try:
                    self.redis_store.room_transition(self.key, {
                        "type": "proposal.conflicted", "at": time.time(), "proposal": proposal_id,
                        **_who(by), "paths": conflicts, "version": head.version,
                    }, proposal_id=proposal_id, require_status="open", expected_version=head.version,
                        proposal_fields={"status": "conflicted", "conflicts": conflicts,
                                         "decided_by": by.id, "decided_at": time.time()})
                except RoomStateChanged as exc:
                    if exc.head_moved:
                        continue  # the room moved; the conflict may be different now
                    raise ValueError(f"{proposal_id} is {exc.proposal_status}, not open") from exc
                raise RoomConflict(proposal_id, conflicts)

            merged = dict(current)
            for path, change in proposal.changes.items():
                change = line_merged.get(path, change)
                if change is None:
                    merged.pop(path, None)
                else:
                    merged[path] = SnapshotEntry(**change)
            version = head.version + 1
            snapshot = await self.store.compose(self._source(version), f"v{version}",
                                                list(merged.values()))
            new_head = Head(version, snapshot.snapshot_id, snapshot.manifest_blob_path,
                            by.id, time.time(), proposal_id)
            try:
                self.redis_store.room_transition(self.key, {
                    "type": "proposal.accepted", "at": time.time(), "proposal": proposal_id,
                    **_who(by), "author": proposal.author, "asked_by": proposal.asked_by,
                    "version": version, "paths": proposal.paths,
                    "merged_over": head.version - proposal.base_version,
                    "line_merged": sorted(line_merged), "workflow_id": proposal.workflow_id,
                }, proposal_id=proposal_id, require_status="open", expected_version=head.version,
                    head=new_head.to_record(),
                    proposal_fields={"status": "accepted", "decided_by": by.id,
                                     "decided_at": time.time(), "accepted_version": version})
            except RoomStateChanged as exc:
                if exc.head_moved:
                    continue  # someone moved the head; merge against the new one
                raise ValueError(f"{proposal_id} is {exc.proposal_status}, not open") from exc
            if proposal.revision_of:
                self._close_overtaken(proposal_id, by)
            return new_head
        raise RuntimeError(f"Could not accept {proposal_id}: the room kept changing")

    def _close_replaced(self, replaced_id: str, proposal_id: str, by: Person) -> None:
        """A revision that lands replaces the proposal it revised."""
        replaced = self.redis_store.get_room_proposal(self.key, replaced_id) or {}
        try:
            self.redis_store.room_transition(self.key, {
                "type": "proposal.rejected", "at": time.time(), "proposal": replaced_id, **_who(by),
                "author": replaced.get("author", ""), "reason": f"replaced by {proposal_id}",
                "workflow_id": replaced.get("workflow_id", ""),
            }, proposal_id=replaced_id, require_status="open",
                proposal_fields={"status": "rejected", "decided_by": by.id, "decided_at": time.time(),
                                 "reason": f"replaced by {proposal_id}"})
        except RoomStateChanged:
            pass  # it was already decided

    def lineage(self, proposal_id: str) -> List[str]:
        """``proposal_id`` and the proposals it revises, nearest first; the last is where
        that line of work started."""
        chain: List[str] = []
        current = proposal_id
        while current and current not in chain:
            chain.append(current)
            current = (self.redis_store.get_room_proposal(self.key, current) or {}).get("revision_of", "")
        return chain

    def overtaken_by(self, proposal_id: str) -> str:
        """The accepted proposal that took another version of ``proposal_id``'s line of
        work, or "". Work or a revision built on an overtaken version must not land."""
        line = set(self.lineage(proposal_id))
        for accepted in self.proposals("accepted"):
            if accepted.id not in line and line & set(self.lineage(accepted.id)):
                return accepted.id
        return ""

    def _close_overtaken(self, winner_id: str, by: Person) -> None:
        """Once one version of a line of work lands, the rest of the line is out of date:
        what it revised is replaced, other open versions close, and work on them stops."""
        line = self.lineage(winner_id)
        for replaced in line[1:]:
            self._close_replaced(replaced, winner_id, by)
        reason = f"superseded by {winner_id}"
        for other in self.proposals("open"):
            if other.id == winner_id or winner_id in self.lineage(other.id) or not self.overtaken_by(other.id):
                continue
            try:
                self.redis_store.room_transition(self.key, {
                    "type": "proposal.rejected", "at": time.time(), "proposal": other.id, **_who(by),
                    "author": other.author, "reason": reason, "workflow_id": other.workflow_id,
                }, proposal_id=other.id, require_status="open",
                    proposal_fields={"status": "rejected", "decided_by": by.id,
                                     "decided_at": time.time(), "reason": reason})
            except RoomStateChanged:
                logger.debug("%s was decided meanwhile; nothing to supersede", other.id)
        mesh = getattr(self, "mesh", None)
        if mesh is None:
            return
        running: Dict[str, str] = {}
        for event in self.events():
            workflow = event.get("workflow_id", "")
            if event.get("type") == "ask.started" and event.get("revision_of"):
                running[workflow] = event["revision_of"]
            elif event.get("type") in ("ask.finished", "ask.failed"):
                running.pop(workflow, None)
        for workflow, revising in running.items():
            if revising in line or self.overtaken_by(revising):
                try:
                    mesh.cancel_goal(workflow, reason=f"{by.display} accepted {winner_id} instead")
                except Exception:  # noqa: BLE001 - the work ending on its own is fine too
                    logger.warning("Could not stop %s after %s was accepted", workflow, winner_id,
                                   exc_info=True)

    async def reject(self, proposal_id: str, *, by: Person, reason: str) -> Proposal:
        """Turn down an open proposal with a reason its author can act on."""
        self.require(by, "editor", "reject changes")
        proposal = self.proposal(proposal_id)
        if proposal.held_for and proposal.held_for != by.id:
            raise RoomPermissionError(f"{proposal_id} is held for {self.name_of(proposal.held_for)}; "
                                      "only they can discard it")
        try:
            self.redis_store.room_transition(self.key, {
                "type": "proposal.rejected", "at": time.time(), "proposal": proposal_id, **_who(by),
                "author": proposal.author, "reason": reason, "workflow_id": proposal.workflow_id,
            }, proposal_id=proposal_id, require_status="open",
                proposal_fields={"status": "rejected", "decided_by": by.id,
                                 "decided_at": time.time(), "reason": reason})
        except RoomStateChanged as exc:
            raise ValueError(f"{proposal_id} is {exc.proposal_status}, not open") from exc
        return self.proposal(proposal_id)

    # ── Local copies for people ─────────────────────────────────────────────

    async def checkout(self, destination: str, *, by: Person) -> Head:
        """Write the room's current files into an empty directory to work on by hand."""
        self.require(by, "viewer", "check out the room")
        target = Path(destination)
        if target.exists() and any(target.iterdir()):
            raise FileExistsError(f"{destination} is not empty")
        if target.exists():
            target.rmdir()  # materialize() creates the directory itself
        head = self.head()
        snapshot = await self.store.load(head.manifest_blob_path)
        await self.store.materialize(snapshot, target)
        (target / CHECKOUT_MARKER).write_text(json.dumps({
            "room": self.id, "tenant": self.tenant, "version": head.version,
            "files": {e.path: e.sha256 for e in snapshot.entries},
        }, indent=2))
        return head

    async def push(self, directory: str, *, by: Person, title: str = "") -> Optional[Proposal]:
        """Propose what changed in a checkout since it was made. None if nothing did."""
        self.require(by, "editor", "propose changes")
        root = Path(directory)
        marker = json.loads((root / CHECKOUT_MARKER).read_text())
        if marker.get("room") != self.id or marker.get("tenant", self.tenant) != self.tenant:
            raise ValueError(f"{directory} is a checkout of room {marker.get('room')!r}")
        known: Dict[str, str] = marker.get("files", {})
        changes: Dict[str, Optional[bytes]] = {}
        seen = set()
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if (path.is_dir() or relative == CHECKOUT_MARKER
                    or set(Path(relative).parts) & set(IGNORED_NAMES)):
                continue
            if path.is_symlink():
                raise ValueError(f"Checkouts cannot contain symlinks: {relative}")
            payload = path.read_bytes()
            seen.add(relative)
            if known.get(relative) != hashlib.sha256(payload).hexdigest():
                changes[relative] = payload
        for relative in known:
            if relative not in seen:
                changes[relative] = None
        return await self.propose(changes, by=by, title=title, base_version=int(marker["version"]))

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def delete(self, *, by: Person) -> None:
        """Remove the room's state and history for good. Owners only.

        What the room remembers in Athena is erased by ``forget``; await it first
        when the room had memory (``delete`` removes the record of who had private
        memory in it)."""
        self.require(by, "owner", "delete the room")
        self.redis_store.delete_room(self.key)

    async def forget(self, *, by: Person) -> Dict[str, int]:
        """Erase everything the room remembers, in Athena and in the local store: the
        team's memory and every person's private memory in the room, including
        people who have left. Owners only. Returns the counts; raises if Athena
        did not confirm."""
        self.require(by, "owner", "erase the room's memory")
        totals: Dict[str, int] = {}
        for memory in self._memory_to_erase():
            for name, n in (await memory.erase()).items():
                totals[name] = totals.get(name, 0) + n
        self.note("memory_erased", by=by.id)
        return totals

    async def forget_person(self, person: Person, *, by: Person) -> Dict[str, Any]:
        """Erase what work for ``person`` learned from their own access in this room
        (their private memory here). The person themselves or an owner."""
        self._same_tenant(person)
        if by.key != person.key:
            self.require(by, "owner", f"erase {person.display}'s memory")
        result: Dict[str, Any] = {}
        for memory in self._memory_to_erase():
            result.update(await memory.erase_person(person))
        self.note("memory_erased", by=by.id, person=person.id)
        return result
