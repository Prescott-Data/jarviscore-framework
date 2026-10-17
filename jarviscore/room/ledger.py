"""
Where a room keeps its head, proposals and event log.

File bytes live in BlobStorage like every other workspace. The ledger holds
the small mutable part: which snapshot is the room's current state, the
proposals against it, and the append-only history. Moving the head is a
compare-and-swap on its version, so two people accepting at once cannot both
win.

``RedisRoomLedger`` is for meshes that share Redis across nodes.
``FileRoomLedger`` is for one machine with no infrastructure.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional


class RoomLedger:
    """Storage contract for a room's mutable state. All values are JSON-safe dicts."""

    def create_room(self, room_id: str, head: Dict[str, Any]) -> bool:
        """Store the first head; False if the room already exists."""
        raise NotImplementedError

    def get_head(self, room_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def swap_head(self, room_id: str, expected_version: int, head: Dict[str, Any]) -> bool:
        """Replace the head only if it is still at ``expected_version``."""
        raise NotImplementedError

    def put_proposal(self, room_id: str, proposal: Dict[str, Any]) -> None:
        raise NotImplementedError

    def get_proposal(self, room_id: str, proposal_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def list_proposals(self, room_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def decide_proposal(self, room_id: str, proposal_id: str, fields: Dict[str, Any]) -> bool:
        """Close an open proposal; False if it is no longer open."""
        raise NotImplementedError

    def append_event(self, room_id: str, event: Dict[str, Any]) -> int:
        """Append and return the event's sequence number, starting at 1."""
        raise NotImplementedError

    def events(self, room_id: str, since: int = 0) -> List[Dict[str, Any]]:
        """Events with a sequence number greater than ``since``, oldest first."""
        raise NotImplementedError


class FileRoomLedger(RoomLedger):
    """One directory per room, serialised with an exclusive file lock."""

    def __init__(self, root: str = ".jarviscore/rooms"):
        self.root = Path(root)

    def _dir(self, room_id: str) -> Path:
        if not room_id or "/" in room_id or "\\" in room_id or room_id.startswith("."):
            raise ValueError(f"Invalid room id: {room_id!r}")
        return self.root / room_id

    @contextmanager
    def _locked(self, room_id: str):
        directory = self._dir(room_id)
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield directory
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    @staticmethod
    def _read(path: Path, default):
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return default

    @staticmethod
    def _write(path: Path, value) -> None:
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value, indent=2, default=str))
        os.replace(tmp, path)

    def create_room(self, room_id, head):
        with self._locked(room_id) as directory:
            if (directory / "head.json").exists():
                return False
            self._write(directory / "head.json", head)
            return True

    def get_head(self, room_id):
        return self._read(self._dir(room_id) / "head.json", None)

    def swap_head(self, room_id, expected_version, head):
        with self._locked(room_id) as directory:
            current = self._read(directory / "head.json", None)
            if not current or int(current["version"]) != int(expected_version):
                return False
            self._write(directory / "head.json", head)
            return True

    def put_proposal(self, room_id, proposal):
        with self._locked(room_id) as directory:
            proposals = self._read(directory / "proposals.json", {})
            proposals[proposal["id"]] = proposal
            self._write(directory / "proposals.json", proposals)

    def get_proposal(self, room_id, proposal_id):
        return self._read(self._dir(room_id) / "proposals.json", {}).get(proposal_id)

    def list_proposals(self, room_id):
        proposals = self._read(self._dir(room_id) / "proposals.json", {})
        return sorted(proposals.values(), key=lambda p: p.get("created_at", 0))

    def decide_proposal(self, room_id, proposal_id, fields):
        with self._locked(room_id) as directory:
            proposals = self._read(directory / "proposals.json", {})
            proposal = proposals.get(proposal_id)
            if not proposal or proposal.get("status") != "open":
                return False
            proposal.update(fields)
            self._write(directory / "proposals.json", proposals)
            return True

    def append_event(self, room_id, event):
        with self._locked(room_id) as directory:
            path = directory / "events.jsonl"
            seq = 1
            if path.exists():
                with open(path) as handle:
                    seq = sum(1 for _ in handle) + 1
            with open(path, "a") as handle:
                handle.write(json.dumps({**event, "seq": seq}, default=str) + "\n")
            return seq

    def events(self, room_id, since=0):
        path = self._dir(room_id) / "events.jsonl"
        if not path.exists():
            return []
        with open(path) as handle:
            return [e for e in (json.loads(line) for line in handle if line.strip())
                    if e["seq"] > since]


class RedisRoomLedger(RoomLedger):
    """Room state in Redis, so every node of a mesh sees the same room."""

    def __init__(self, client):
        self.redis = client

    @staticmethod
    def _key(room_id: str, part: str) -> str:
        return f"room:{room_id}:{part}"

    def create_room(self, room_id, head):
        return bool(self.redis.set(self._key(room_id, "head"), json.dumps(head), nx=True))

    def get_head(self, room_id):
        raw = self.redis.get(self._key(room_id, "head"))
        return json.loads(raw) if raw else None

    def swap_head(self, room_id, expected_version, head):
        from redis.exceptions import WatchError

        key = self._key(room_id, "head")
        with self.redis.pipeline() as pipe:
            try:
                pipe.watch(key)
                raw = pipe.get(key)
                if not raw or int(json.loads(raw)["version"]) != int(expected_version):
                    pipe.unwatch()
                    return False
                pipe.multi()
                pipe.set(key, json.dumps(head))
                pipe.execute()
                return True
            except WatchError:
                return False  # the head moved under us; the caller re-reads it

    def put_proposal(self, room_id, proposal):
        self.redis.hset(self._key(room_id, "proposals"), proposal["id"], json.dumps(proposal))

    def get_proposal(self, room_id, proposal_id):
        raw = self.redis.hget(self._key(room_id, "proposals"), proposal_id)
        return json.loads(raw) if raw else None

    def list_proposals(self, room_id):
        values = self.redis.hvals(self._key(room_id, "proposals"))
        return sorted((json.loads(v) for v in values), key=lambda p: p.get("created_at", 0))

    def decide_proposal(self, room_id, proposal_id, fields):
        from redis.exceptions import WatchError

        key = self._key(room_id, "proposals")
        while True:
            with self.redis.pipeline() as pipe:
                try:
                    pipe.watch(key)
                    raw = pipe.hget(key, proposal_id)
                    proposal = json.loads(raw) if raw else None
                    if not proposal or proposal.get("status") != "open":
                        pipe.unwatch()
                        return False
                    proposal.update(fields)
                    pipe.multi()
                    pipe.hset(key, proposal_id, json.dumps(proposal))
                    pipe.execute()
                    return True
                except WatchError:
                    continue  # another proposal changed; check this one again

    def append_event(self, room_id, event):
        seq = int(self.redis.incr(self._key(room_id, "seq")))
        self.redis.zadd(self._key(room_id, "events"), {json.dumps({**event, "seq": seq}): seq})
        return seq

    def events(self, room_id, since=0):
        raw = self.redis.zrangebyscore(self._key(room_id, "events"), f"({int(since)}", "+inf")
        return [json.loads(e) for e in raw]
