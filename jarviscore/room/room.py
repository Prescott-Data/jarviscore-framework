"""
A room: one shared workspace that people and agents change together.

The room's current state is an immutable source snapshot, its *head*. Nobody
writes to the head directly. Agents and people make **proposals** against a
version of it; accepting one moves the head forward. If the head moved since a
proposal was made, the proposal is merged: a file only one side changed is
taken, and in a text file both sides changed, edits to different lines are
both kept. Edits to the same lines that differ, or a file deleted on one side
and changed on the other, are a conflict that stops the accept rather than
silently overwriting someone's work.

Every change records who made it and who asked for it, and every step is in
the room's event log, so anyone can see what happened and why.

    room = Room.local("launch")
    await room.ensure({"README.md": "# Launch"}, by="alice")
    proposal = await room.propose({"README.md": "# Launch\\n\\nShip Tuesday."},
                                  author="writer", asked_by="alice", title="Add date")
    for change in await room.diff(proposal.id):
        print(change.unified())
    await room.accept(proposal.id, by="bob")
"""

from __future__ import annotations

import difflib
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from uuid import uuid4

from jarviscore.execution.workspace import (
    BlobSnapshotStore,
    SnapshotEntry,
    SourceRef,
    SourceSnapshot,
    WorkspaceDelta,
    WorkspaceDeltaConflict,
    _register_workspace_path,
)
from jarviscore.room.ledger import FileRoomLedger, RedisRoomLedger, RoomLedger
from jarviscore.execution.merge import merge_text

#: Provider name a goal uses to work on a room: workspace_source={"provider": "room", ...}
ROOM_PROVIDER = "room"

#: Written by checkout() so push() knows which version a local copy started from.
CHECKOUT_MARKER = ".jarviscore-room.json"

#: Never read back from a checkout: tool and build state, not work.
IGNORED_NAMES = (".git", ".venv", "__pycache__", "node_modules", ".tmp", ".DS_Store")

_ACCEPT_ATTEMPTS = 20


#: Each role can do what the ones before it can.
ROLES = ("viewer", "editor", "owner")


class RoomPermissionError(PermissionError):
    """The person's role in a members-only room does not allow this."""


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
    author: str
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


class Room:
    """A shared, versioned workspace. See the module docstring."""

    def __init__(self, room_id: str, *, blob_storage, ledger: RoomLedger):
        _register_workspace_path(room_id, {}, label="room id")
        if "/" in room_id:
            raise ValueError(f"Room ids cannot contain '/': {room_id!r}")
        self.id = room_id
        self.store = BlobSnapshotStore(blob_storage)
        self.ledger = ledger

    # ── Construction ────────────────────────────────────────────────────────

    @classmethod
    def local(cls, room_id: str, root: str = ".jarviscore") -> "Room":
        """A room on this machine, with no Redis or shared storage."""
        from jarviscore.storage.local import LocalBlobStorage

        return cls(room_id, blob_storage=LocalBlobStorage(str(Path(root) / "blobs")),
                   ledger=FileRoomLedger(str(Path(root) / "rooms")))

    @classmethod
    def open(cls, room_id: str, *, redis_url: Optional[str] = None, settings=None) -> "Room":
        """The room as a Mesh with the same settings sees it: same storage, same Redis."""
        from jarviscore.config.settings import Settings
        from jarviscore.storage import get_blob_storage

        settings = settings or Settings()
        url = redis_url or getattr(settings, "redis_url", None)
        if url:
            import redis

            ledger: RoomLedger = RedisRoomLedger(redis.Redis.from_url(url, decode_responses=True))
        else:
            ledger = FileRoomLedger()
        return cls(room_id, blob_storage=get_blob_storage(settings), ledger=ledger)

    @classmethod
    def for_mesh(cls, mesh, room_id: str) -> "Room":
        """A room on a started Mesh: its BlobStorage, and its Redis when it has one.

        The room can then ``ask`` the mesh's agents to work on it.
        """
        if getattr(mesh, "_blob_storage", None) is None:
            raise RuntimeError("A room needs a started Mesh with BlobStorage")
        redis_store = getattr(mesh, "_redis_store", None)
        ledger = (
            RedisRoomLedger(redis_store._redis) if redis_store is not None
            else FileRoomLedger()
        )
        room = cls(room_id, blob_storage=mesh._blob_storage, ledger=ledger)
        from jarviscore.room.work import install

        install(mesh, room)
        room.mesh = mesh
        return room

    async def ask(self, goal: str, *, asked_by: str, revision_of: str = "", **options):
        """Have the mesh's agents do ``goal`` on the room's current files.

        Returns an ``AskResult`` whose ``proposal`` holds their changes for
        people to review, or None if they changed nothing. ``revision_of``
        names a rejected proposal; its reason is passed on to the agents.
        Options are passed to ``Mesh.execute_goal`` (``timeout``,
        ``plan_template``).
        """
        mesh = getattr(self, "mesh", None)
        if mesh is None:
            raise RuntimeError("Use Room.for_mesh(mesh, room_id) to have agents work in a room")
        from jarviscore.room.work import ask

        return await ask(self, mesh, goal, asked_by=asked_by, revision_of=revision_of, **options)

    async def ensure(self, files: Optional[Mapping[str, Any]] = None, *, by: str = "") -> Head:
        """Create the room with these files if it does not exist; return its head."""
        existing = self.ledger.get_head(self.id)
        if existing:
            return Head.from_record(existing)
        snapshot = await self.store.capture(self._source(1), "v1", dict(files or {}))
        head = Head(1, snapshot.snapshot_id, snapshot.manifest_blob_path, by, time.time())
        if self.ledger.create_room(self.id, head.to_record()):
            self.ledger.update_meta(self.id, lambda meta: {**meta, "created_by": by})
            self._event("room.created", by=by, version=1, files=len(snapshot.entries))
            return head
        return Head.from_record(self.ledger.get_head(self.id))

    async def ensure_from(self, snapshot: SourceSnapshot, *, by: str = "") -> Head:
        """Create the room from an existing snapshot, such as a captured repository."""
        existing = self.ledger.get_head(self.id)
        if existing:
            return Head.from_record(existing)
        await self.store.validate(snapshot)
        first = await self.store.compose(self._source(1), "v1", list(snapshot.entries))
        head = Head(1, first.snapshot_id, first.manifest_blob_path, by, time.time())
        if self.ledger.create_room(self.id, head.to_record()):
            self.ledger.update_meta(self.id, lambda meta: {**meta, "created_by": by})
            self._event("room.created", by=by, version=1, files=len(first.entries),
                        source=f"{snapshot.source.provider}:{snapshot.source.locator}"
                               f"@{snapshot.resolved_revision}")
            return head
        return Head.from_record(self.ledger.get_head(self.id))

    # ── Reading ─────────────────────────────────────────────────────────────

    def head(self) -> Head:
        record = self.ledger.get_head(self.id)
        if not record:
            raise KeyError(f"Room {self.id!r} does not exist")
        return Head.from_record(record)

    def _source(self, version: int) -> SourceRef:
        return SourceRef(ROOM_PROVIDER, self.id, str(version))

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
        blob_path = f"rooms/{self.id}/objects/{digest}"
        if await self.store.blob_storage.read(blob_path) is None:
            await self.store.blob_storage.save(blob_path, payload)
        return asdict(SnapshotEntry(path, blob_path, digest, len(payload), executable))

    async def _blob(self, blob_path: str) -> bytes:
        payload = await self.store.blob_storage.read(blob_path)
        if payload is None:
            raise FileNotFoundError(blob_path)
        return _bytes(payload)

    def proposal(self, proposal_id: str) -> Proposal:
        record = self.ledger.get_proposal(self.id, proposal_id)
        if not record:
            raise KeyError(f"No proposal {proposal_id!r} in room {self.id!r}")
        return Proposal.from_record(record)

    def proposals(self, status: Optional[str] = None) -> List[Proposal]:
        return [Proposal.from_record(r) for r in self.ledger.list_proposals(self.id)
                if status is None or r.get("status") == status]

    def events(self, since: int = 0) -> List[Dict[str, Any]]:
        return self.ledger.events(self.id, since)

    def note(self, kind: str, **fields) -> int:
        """Record something that happened in the room, for everyone watching it."""
        return self._event(kind, **fields)

    def _event(self, kind: str, **fields) -> int:
        return self.ledger.append_event(self.id, {"type": kind, "at": time.time(), **fields})

    # ── Who may do what ─────────────────────────────────────────────────────
    #
    # A room is open by default: everyone on the team can ask, propose, accept
    # and reject, and sees everything ("work with the door open"). Once it has
    # members it is members-only: viewers watch, editors also ask, push, accept
    # and reject, owners also manage members.

    def members(self) -> Dict[str, str]:
        """Person -> role. Empty for an open room."""
        return dict(self.ledger.get_meta(self.id).get("members") or {})

    def role_of(self, person: str) -> Optional[str]:
        meta = self.ledger.get_meta(self.id)
        members = meta.get("members") or {}
        if members:
            return members.get(person)
        return "owner" if person and person == meta.get("created_by") else "editor"

    def can(self, person: str, role: str) -> bool:
        held = self.role_of(person)
        return held is not None and ROLES.index(held) >= ROLES.index(role)

    def require(self, person: str, role: str, action: str) -> None:
        if not self.can(person, role):
            held = self.role_of(person)
            raise RoomPermissionError(
                f"{person or 'Someone unnamed'} cannot {action} in room {self.id}: "
                + (f"they are a {held}" if held else "they are not a member")
                + f" and it needs {role}"
            )

    def set_role(self, person: str, role: Optional[str], *, by: str) -> Dict[str, str]:
        """Give ``person`` a role, or None to remove them. Owners only.

        The first member makes an open room members-only; only its creator can
        do that, and the creator becomes an owner with it.
        """
        if role is not None and role not in ROLES:
            raise ValueError(f"role must be one of {ROLES} or None, not {role!r}")

        def change(meta):
            members = dict(meta.get("members") or {})
            creator = meta.get("created_by") or ""
            if members:
                if members.get(by) != "owner":
                    raise RoomPermissionError(f"Only an owner of room {self.id} can change members")
            else:
                if by != creator or not creator:
                    raise RoomPermissionError(
                        f"Only {creator or 'the creator'} can make room {self.id} members-only")
                members[creator] = "owner"
            if role is None:
                members.pop(person, None)
            else:
                members[person] = role
            if "owner" not in members.values():
                raise RoomPermissionError(f"Room {self.id} must keep at least one owner")
            return {**meta, "members": members}

        members = self.ledger.update_meta(self.id, change)["members"]
        self._event("member.changed", by=by, person=person, role=role or "removed")
        return dict(members)

    # ── Proposing ───────────────────────────────────────────────────────────

    async def propose(
        self,
        changes: Mapping[str, Any],
        *,
        author: str,
        title: str = "",
        asked_by: str = "",
        base_version: Optional[int] = None,
        workflow_id: str = "",
        revision_of: str = "",
    ) -> Optional[Proposal]:
        """Propose new content per path (``None`` deletes). None if nothing changes."""
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
        return self._open(entries, base, author=author, title=title, asked_by=asked_by,
                          workflow_id=workflow_id, revision_of=revision_of)

    async def propose_deltas(
        self,
        deltas: Iterable[WorkspaceDelta],
        *,
        base_version: int,
        author: str,
        title: str = "",
        asked_by: str = "",
        workflow_id: str = "",
        revision_of: str = "",
    ) -> Optional[Proposal]:
        """Turn the workspace deltas of an agent run into one proposal."""
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
        return self._open(entries, base, author=author, title=title, asked_by=asked_by,
                          workflow_id=workflow_id, revision_of=revision_of)

    def _open(self, entries, base: SourceSnapshot, **fields) -> Optional[Proposal]:
        if not entries:
            return None
        proposal = Proposal(
            id=f"p-{uuid4().hex[:8]}",
            base_version=int(base.source.revision),
            base_manifest=base.manifest_blob_path,
            changes=entries,
            **fields,
        )
        self.ledger.put_proposal(self.id, proposal.to_record())
        self._event("proposal.opened", proposal=proposal.id, by=proposal.author,
                    asked_by=proposal.asked_by, title=proposal.title,
                    base_version=proposal.base_version, paths=proposal.paths,
                    revision_of=proposal.revision_of)
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
            status = "deleted" if change is None else "modified" if path in base else "added"
            out.append(FileChange(path, status, before, after))
        return out

    # ── Deciding ────────────────────────────────────────────────────────────

    async def accept(self, proposal_id: str, *, by: str) -> Head:
        """Merge an open proposal into the room. Raises RoomConflict on overlapping edits."""
        self.require(by, "editor", "accept changes")
        proposal = self.proposal(proposal_id)
        if proposal.status != "open":
            raise ValueError(f"{proposal_id} is {proposal.status}, not open")
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
                if self.ledger.decide_proposal(self.id, proposal_id, {
                    "status": "conflicted", "conflicts": conflicts,
                    "decided_by": by, "decided_at": time.time(),
                }):
                    self._event("proposal.conflicted", proposal=proposal_id, by=by,
                                paths=conflicts, version=head.version)
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
                            by, time.time(), proposal_id)
            if not self.ledger.swap_head(self.id, head.version, new_head.to_record()):
                continue  # someone moved the head; merge against the new one
            self.ledger.decide_proposal(self.id, proposal_id, {
                "status": "accepted", "decided_by": by, "decided_at": time.time(),
                "accepted_version": version,
            })
            self._event("proposal.accepted", proposal=proposal_id, by=by,
                        author=proposal.author, asked_by=proposal.asked_by,
                        version=version, paths=proposal.paths,
                        merged_over=head.version - proposal.base_version,
                        line_merged=sorted(line_merged))
            return new_head
        raise RuntimeError(f"Could not accept {proposal_id}: the room kept changing")

    async def reject(self, proposal_id: str, *, by: str, reason: str) -> Proposal:
        """Turn down an open proposal with a reason its author can act on."""
        self.require(by, "editor", "reject changes")
        if not self.ledger.decide_proposal(self.id, proposal_id, {
            "status": "rejected", "decided_by": by, "decided_at": time.time(),
            "reason": reason,
        }):
            raise ValueError(f"{proposal_id} is not open")
        proposal = self.proposal(proposal_id)
        self._event("proposal.rejected", proposal=proposal_id, by=by,
                    author=proposal.author, reason=reason)
        return proposal

    # ── Local copies for people ─────────────────────────────────────────────

    async def checkout(self, destination: str) -> Head:
        """Write the room's current files into an empty directory to work on by hand."""
        target = Path(destination)
        if target.exists() and any(target.iterdir()):
            raise FileExistsError(f"{destination} is not empty")
        if target.exists():
            target.rmdir()  # materialize() creates the directory itself
        head = self.head()
        snapshot = await self.store.load(head.manifest_blob_path)
        await self.store.materialize(snapshot, target)
        (target / CHECKOUT_MARKER).write_text(json.dumps({
            "room": self.id, "version": head.version,
            "files": {e.path: e.sha256 for e in snapshot.entries},
        }, indent=2))
        return head

    async def push(self, directory: str, *, author: str, title: str = "",
                   asked_by: str = "") -> Optional[Proposal]:
        """Propose what changed in a checkout since it was made. None if nothing did."""
        self.require(author, "editor", "propose changes")
        root = Path(directory)
        marker = json.loads((root / CHECKOUT_MARKER).read_text())
        if marker.get("room") != self.id:
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
        return await self.propose(changes, author=author, title=title, asked_by=asked_by,
                                  base_version=int(marker["version"]))
