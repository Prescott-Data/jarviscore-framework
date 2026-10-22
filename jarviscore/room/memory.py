"""
A room's team memory, in Athena.

What a team says and decides about its work is the memory every agent working
in the room should have: "Sam owns support", "the board fixed Tuesday", "we
dropped the venue risk because the contract covers it". ``RoomMemory`` writes
it to the room's shared Athena scope (the room's tenant, the room as the
scope, one ``room`` session), where Athena does what it is built for: it
follows the conversation, splits it where the topic changes, summarises each
part and makes it searchable. Every agent that later works in the room recalls
it through the Kernel's ordinary ``recall``.

Written:

- what people say to the room's agent, as their messages (``said``), and the
  agent's replies to everyone (``replied``);
- what the room records: requests, finished work and its summary, decisions
  with their reasons, who joined (``sync``, once per room, from where it left off).

Never written: anything shown to one person only (work held for its asker,
private replies), and work held for its asker until it is released (its
summary stays out even then: it came from their access). Athena keeps no
access control inside a scope, so what is not for everyone is not written.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("jarviscore.room.memory")

#: The agent id of a room's team session in Athena.
TEAM_AGENT = "room"


class RoomMemory:
    """Writes a room's team memory to Athena. See the module docstring."""

    def __init__(self, room, client):
        self.room = room
        self.client = client
        self.store = room.redis_store
        self._session: Optional[str] = None
        self._holder = uuid.uuid4().hex

    @classmethod
    def from_env(cls, room) -> Optional["RoomMemory"]:
        """The room's memory when Athena is configured (``ATHENA_URL``), else None."""
        from jarviscore.memory.athena_client import AthenaClient

        client = AthenaClient.from_env()
        return cls(room, client) if client is not None else None

    async def session(self) -> Optional[str]:
        if self._session is None:
            self._session = await self.client.get_or_create_session(
                TEAM_AGENT, redis_store=self.store, user_id=self.room.key, tenant_id=self.room.tenant,
                metadata={"room": self.room.key, "kind": "team"})
        return self._session

    async def _write(self, role: str, kind: str, content: str, metadata: Dict[str, Any]) -> None:
        session = await self.session()
        if not session:
            raise RuntimeError("Athena has no session for this room")
        await self.client.write_event(session_id=session, role=role, event_type=kind, content=content,
                                      metadata={k: str(v) for k, v in metadata.items() if v not in (None, "")})

    # ── Forgetting ──────────────────────────────────────────────────────────

    def private_scope(self, person) -> str:
        """The Athena scope holding what work for ``person`` learned from their own access."""
        return f"{self.room.key}#private:{person.id}"

    async def erase(self) -> Dict[str, int]:
        """Erase everything the room remembers in Athena: the team's memory and the
        private memory of everyone who had private work in it. Raises if Athena
        did not confirm it; safe to retry."""
        # What is still queued goes first, so it is erased rather than written after.
        if not await self.flush(timeout=30.0):
            raise RuntimeError(f"room {self.room.key}: memory writes are still queued; retry the erasure")
        lease = f"{self.room.key}:memory"
        if self.store is not None and not self.store.take_lease(lease, self._holder, 300):
            raise RuntimeError(f"room {self.room.key}: its memory is being written elsewhere; retry the erasure")
        try:
            totals: Dict[str, int] = {}
            for scope in self._scopes():
                for name, n in (await self.client.erase_memory(self.room.tenant, scope)).items():
                    if isinstance(n, int) and not isinstance(n, bool):
                        totals[name] = totals.get(name, 0) + n
                if scope != self.room.key and self.store is not None:
                    self.store.forget_room_memory_scope(self.room.key, scope)
            self._session = None
            return totals
        finally:
            if self.store is not None:
                self.store.release_lease(lease, self._holder)

    def _scopes(self) -> list:
        """Every Athena scope that may hold this room's memory: the team's, the private
        scopes recorded when first used, and (for memory kept before they were
        recorded) a private scope for everyone the room has known."""
        scopes = {self.room.key}
        people = set(self.room.members())
        if self.store is not None:
            scopes.update(self.store.room_memory_scopes(self.room.key))
            people.update((self.store.get_room_meta(self.room.key) or {}).get("names") or {})
        for event in self.room.events():
            for field in ("by", "person"):
                if event.get(field):
                    people.add(str(event[field]))
        scopes.update(f"{self.room.key}#private:{pid}" for pid in people)
        return [self.room.key] + sorted(scopes - {self.room.key})

    async def erase_person(self, person) -> Dict[str, Any]:
        """Erase one person's private memory in this room."""
        scope = self.private_scope(person)
        result = await self.client.erase_memory(self.room.tenant, scope)
        if self.store is not None:
            self.store.forget_room_memory_scope(self.room.key, scope)
        return result

    # ── The conversation ────────────────────────────────────────────────────

    def said_later(self, person, text: str, *, thread: str = "") -> None:
        """Queue a person's message to be kept, in order, without waiting for Athena."""
        self._queue().submit(self._send, role="user", kind="message", content=f"{person.display}: {text}",
                             metadata={"person": person.id, "thread": thread})

    def replied_later(self, text: str, *, thread: str = "") -> None:
        self._queue().submit(self._send, role="agent", kind="message", content=text,
                             metadata={"thread": thread})

    async def _send(self, *, role: str, kind: str, content: str, metadata: Dict[str, Any]) -> None:
        await self._write(role, kind, content, metadata)

    def _queue(self):
        if getattr(self, "_outbox", None) is None:
            from jarviscore.memory.delivery import Outbox

            # Ordered, bounded, and dropping (and counting) rather than blocking when Athena is down.
            self._outbox = Outbox()
        return self._outbox

    async def flush(self, timeout: float = 5.0) -> bool:
        """Wait for queued messages to reach Athena (False if some are still queued)."""
        return True if getattr(self, "_outbox", None) is None else await self._outbox.flush(timeout=timeout)

    async def said(self, person, text: str, *, thread: str = "", workflow_id: str = "") -> bool:
        """A person's message to the room, as they wrote it. False if it was not kept."""
        try:
            await self._write("user", "message", f"{person.display}: {text}",
                              {"person": person.id, "thread": thread, "workflow_id": workflow_id})
            return True
        except Exception as exc:
            logger.warning("Room %s: a message was not kept in team memory: %s", self.room.key, exc)
            return False

    async def replied(self, text: str, *, thread: str = "") -> bool:
        try:
            await self._write("agent", "message", text, {"thread": thread})
            return True
        except Exception as exc:
            logger.warning("Room %s: a reply was not kept in team memory: %s", self.room.key, exc)
            return False

    # ── What the room records ───────────────────────────────────────────────

    def _cursor_key(self) -> str:
        return f"room:{{{self.room.key}}}:memory:after"

    async def sync(self, *, lease_seconds: float = 30.0) -> int:
        """Write what the room recorded since the last sync; returns how many events.

        Safe to call from every process: one writes at a time, from where the
        last one stopped. An event is written at least once (Athena keeps no
        de-duplication key, so a process stopping right after a write can repeat it).
        """
        lease = f"{self.room.key}:memory"
        if not self.store.take_lease(lease, self._holder, lease_seconds):
            return 0
        written = 0
        try:
            after = self.store._redis.get(self._cursor_key()) or ""
            for event in self.room.events(after):
                if not self.store.take_lease(lease, self._holder, lease_seconds):
                    break
                line = self.describe(event)
                if line:
                    await self._write("system", "observation", line, {
                        "event": event.get("type"), "workflow_id": event.get("workflow_id"),
                        "proposal": event.get("proposal"), "person": event.get("by")})
                    written += 1
                self.store._redis.set(self._cursor_key(), event["seq"])
        finally:
            self.store.release_lease(lease, self._holder)
        return written

    def describe(self, event: Dict[str, Any]) -> str:
        """The line a room event becomes in team memory, or "" for events not kept."""
        kind = event.get("type", "")
        who = event.get("by_name") or event.get("by") or "someone"
        if event.get("held_for"):
            return ""  # used someone's own access: never in the shared memory
        title = ""
        if event.get("proposal"):
            proposal = self.store.get_room_proposal(self.room.key, event["proposal"]) or {}
            if proposal.get("held_for") or (proposal.get("sources") and kind != "proposal.released"
                                            and self._private(proposal)):
                return ""
            title = f' ("{(proposal.get("title") or "").splitlines()[0][:200]}")' if proposal.get("title") else ""
        if kind == "ask.started":
            return f"{who} asked the agents: {event.get('goal', '')}"
        if kind == "ask.finished":
            summary = str(event.get("summary") or "").strip()
            outcome = f" ({event.get('status')})" if event.get("status") not in ("completed", None) else ""
            return f"The agents finished {who}'s request{outcome}." + (f" {summary[:2000]}" if summary else "")
        if kind == "ask.failed":
            return f"{who}'s request could not be done: {event.get('error', '')}"
        if kind == "proposal.accepted":
            return f"{who} accepted {event.get('proposal')}{title}; the room is now at version {event.get('version')}."
        if kind == "proposal.rejected":
            return f"{who} turned down {event.get('proposal')}{title}: {event.get('reason', '')}"
        if kind == "proposal.released":
            return f"{who} shared {event.get('proposal')}{title} with the room."
        if kind == "member.changed":
            role = event.get("role", "")
            name = event.get("person_name") or event.get("person", "")
            return f"{who} removed {name} from the room." if role == "removed" else f"{who} made {name} {role}."
        if kind == "room.created":
            return f"{who} opened the room at {time.strftime('%Y-%m-%d', time.gmtime(float(event.get('at') or 0)))}."
        return ""

    def _private(self, proposal: Dict[str, Any]) -> bool:
        shared = set(self.room.settings().get("shared_connectors") or [])
        return any(str(s.get("provider", "")).lower() not in shared for s in proposal.get("sources") or [])


class LocalRoomMemory:
    """Erases what agents kept for a room in the local store (``.jarviscore/memory``).

    Without Athena, agents working in a room remember in local files scoped to the
    room, and to each person's private memory in it. They live on the machine
    and in the working directory where the work ran; run every worker of a room
    there, or use Athena, for ``forget`` to reach all of it.
    """

    def __init__(self, room, base_dir: Optional[str] = None):
        self.room = room
        self.store = room.redis_store
        self.base_dir = base_dir

    def private_scope(self, person) -> str:
        return f"{self.room.key}#private:{person.id}"

    _scopes = RoomMemory._scopes

    async def erase(self) -> Dict[str, int]:
        from jarviscore.memory.local import LocalMemory

        removed = 0
        for scope in self._scopes():
            removed += LocalMemory.erase_scope(scope, self.base_dir)
            if scope != self.room.key and self.store is not None:
                self.store.forget_room_memory_scope(self.room.key, scope)
        return {"local_facts": removed}

    async def erase_person(self, person) -> Dict[str, Any]:
        from jarviscore.memory.local import LocalMemory

        scope = self.private_scope(person)
        removed = LocalMemory.erase_scope(scope, self.base_dir)
        if self.store is not None:
            self.store.forget_room_memory_scope(self.room.key, scope)
        return {"local_facts": removed}
