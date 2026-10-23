"""
A room's conversation on a chat surface (Slack, Teams, your own product).

``RoomConversation`` connects one room to one place people talk and owns
everything multiplayer about it, so a surface only moves messages:

- **People to the room.** A message is received durably and exactly once
  (``receive``) before the surface acknowledges it, then handled in order per
  thread, across processes (``handle``). It is added to the thread's
  transcript, which JarvisCore keeps, and goes to the ``RoomAgent``, which acts
  as the person who sent it.
- **Decisions are confirmed.** The agent never accepts, rejects or answers for
  the team from text. It prepares the decision and the surface asks that
  person to confirm with one tap; only their confirmation carries it out.
- **The room to people.** What happens in the room is posted in the right
  thread: requests, the plan, each step, proposals and decisions. Delivery is
  at least once and never lost: one process holds the surface's delivery
  lease, and the place in the feed is saved only after each post succeeds.
- **Who sees what.** Before posting, the surface's audience is checked against
  the room: a room is only shown where everyone who can see it may. Work held
  for its asker (it used their private access) is shown to them alone until
  they release it.
- **Agents asking people.** When the room's work needs a person (a step
  routed to people, or an agent asking for sign-off), it is asked in the
  thread of that work, and the room's editors answer it there.

Implement ``ChatSurface`` for your product and drive the conversation with
``receive``/``handle`` (or ``hear``) and ``press``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from jarviscore.auth.people import Person
from jarviscore.room.agent import RoomAgent
from jarviscore.room.feed import FeedItem, RoomFeed
from jarviscore.room.room import Room, RoomConflict, RoomPermissionError

logger = logging.getLogger("jarviscore.room.conversation")

#: Buttons on a proposal, for whoever presses them.
ACCEPT = "accept"
SHOW_CHANGE = "show_change"
#: Buttons on held work, for the person it is held for.
RELEASE = "release"
DISCARD = "discard"
#: Buttons on a prepared decision, for the person who must confirm it.
CONFIRM = "confirm"
CANCEL = "cancel"

#: Decisions the room agent may prepare for a person to confirm.
DECISIONS = ("accept", "reject", "release", "discard", "answer")


class ChatSurface:
    """Where a room's conversation is shown. Subclass it for your product.

    ``thread`` is the surface's id of the message a conversation hangs off, or
    None for the top level. ``to`` is a person to show something to privately
    (an ephemeral message, a direct message, their own view). Every method
    returns the id of what it posted.
    """

    #: Unique per place a room is shown, e.g. "slack:C0123"; keys the saved state.
    key: str = "chat"

    async def say(self, thread: Optional[str], text: str, *, detail: str = "", code: str = "",
                  to: Optional[Person] = None) -> str:
        """Post ``text`` (``detail`` is quoted context, ``code`` is shown verbatim)."""
        raise NotImplementedError

    async def notice(self, thread: Optional[str], text: str, *, to: Person) -> str:
        """A short private note to ``to`` (a refusal, "Cancelled."); it may be
        transient, such as a Slack ephemeral message. By default, ``say(to=)``."""
        return await self.say(thread, text, to=to)

    async def show_proposal(self, thread: Optional[str], text: str, diff: str, proposal_id: str,
                            *, to: Optional[Person] = None, held: bool = False) -> str:
        """Post a proposal with its change and buttons: ACCEPT and SHOW_CHANGE, or, when
        ``held`` (shown only ``to`` the person it is held for), RELEASE and DISCARD."""
        raise NotImplementedError

    async def confirm(self, thread: Optional[str], decision: Dict[str, Any], *, to: Person) -> str:
        """Ask ``to`` alone to confirm a prepared decision, with CONFIRM and CANCEL buttons
        whose value is ``decision["id"]``. ``decision["summary"]`` says what it will do."""
        raise NotImplementedError

    async def audience(self, room: Room) -> Optional[str]:
        """Why this surface may not show ``room`` now, or None if it may.

        A shared space (a channel) must only include people who can see the
        room. A surface that shows each person their own view, checking
        ``RoomConversation.can_see`` for each, returns None.
        """
        return None

    async def history(self, thread: str) -> List[Dict[str, str]]:
        """Optional: earlier messages in a thread that never reached the room
        (such as people talking among themselves), as {"person", "text"}."""
        return []


async def _cancellable(coro):
    """Await ``coro`` so that cancelling the caller always stops the caller, even when
    a library inside ``coro`` (an HTTP client, say) catches the cancellation and
    carries on. The work runs as its own task behind a shield: the caller's
    cancellation is raised in the caller, and the work is cancelled as well."""
    inner = asyncio.ensure_future(coro)
    try:
        return await asyncio.shield(inner)
    except asyncio.CancelledError:
        inner.cancel()
        raise


class RoomConversation:
    """One room's conversation on one surface. See the module docstring."""

    def __init__(
        self,
        room: Room,
        agent: RoomAgent,
        surface: ChatSurface,
        *,
        poll_interval: float = 1.0,
        decision_seconds: int = 600,
        retention_days: int = 90,
        audience_seconds: float = 30.0,
    ):
        self.room = room
        self.agent = agent
        self.surface = surface
        self.poll_interval = poll_interval
        self.decision_seconds = decision_seconds
        self.retention_days = retention_days
        self.audience_seconds = audience_seconds
        self.store = room.redis_store
        self.instance = uuid.uuid4().hex[:12]
        self._threads: Dict[str, str] = {}   # "wf:<workflow>" / "p:<proposal>" -> thread
        self._latest: Dict[str, str] = {}    # thread -> its latest proposal
        self._asked: Dict[str, str] = {}     # question id -> thread it was asked in
        self._paused: str = ""
        self._audience_checked = 0.0
        self._tasks: set = set()
        self._closing = False
        self._lease = ""                     # the delivery lease, while follow() runs
        self._lease_seconds = max(10.0, poll_interval * 10)
        self._failures: Dict[str, int] = {}  # item -> failed posts in a row
        self._memory_task: Optional[asyncio.Task] = None

    # ── Saved state ─────────────────────────────────────────────────────────
    #
    # The maps (which thread each piece of work and proposal is in, the latest
    # proposal per thread, where each question was asked) are added to field by
    # field by every process; the delivery cursor is written only by the process
    # holding the delivery lease.

    _MAPS = ("threads", "latest", "asked")

    def _remember(self, name: str, field: str, value: str) -> None:
        getattr(self, f"_{name}")[field] = value
        self.store.surface_map_put(self.room.key, self.surface.key, name, field, value,
                                   retention_days=self.retention_days)

    def _reload_maps(self) -> None:
        # Another process may have started threads (it handled a message, or posted).
        for name in self._MAPS:
            getattr(self, f"_{name}").update(self.store.surface_map(self.room.key, self.surface.key, name))
        flags = self.store.surface_map(self.room.key, self.surface.key, "flags")
        self._paused = flags.get("paused", self._paused)

    def _saved_cursor(self) -> Optional[Dict[str, Any]]:
        state = self.store.surface_state(self.room.key, self.surface.key) or {}
        return state.get("feed")

    def _save_cursor(self, cursor: Dict[str, Any]) -> None:
        self.store.save_surface_state(self.room.key, self.surface.key, {"feed": cursor})

    def threads(self) -> set:
        """Threads this conversation owns: messages there go to the room's agent."""
        self._reload_maps()
        return set(self._threads.values()) | set(self._asked.values())

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Pick up where this surface left off, or introduce the room the first time,
        and handle any message that was received but not handled before a restart."""
        self._reload_maps()
        fresh = RoomFeed(self.room)
        fresh.skip_history()
        # The first process to connect this surface starts it from now and says hello.
        if self.store.save_surface_state(self.room.key, self.surface.key, {"feed": fresh.state()}, first=True):
            reason = await self.surface.audience(self.room)
            if not reason:
                head = self.room.head()
                files = len((await self.room.snapshot()).entries)
                await self.surface.say(None, (
                    f"The {self.room.id} room is connected here (version {head.version}, {files} files). "
                    "Mention me with what you need; the work and its review happen in a thread."))
        for record in self.store.pending_messages(self.room.key, self.surface.key):
            self._spawn(self.handle(record["message_id"]))
        # Work started before a restart is followed to its end and filed here.
        self.agent.resume_work(self.room)

    async def follow(self) -> None:
        """Post what happens in the room, and the agents' questions, until cancelled.

        Only one process at a time posts for a surface (it holds the delivery
        lease); others wait and take over if it stops.
        """
        lease = self._lease = f"{self.room.key}:surface:{self.surface.key}:delivery"
        seconds = self._lease_seconds
        try:
            while True:
                try:
                    if self.store.take_lease(lease, self.instance, seconds):
                        await _cancellable(self.sync())
                    if self.room.memory is not None and not self._memory_task:
                        # Its own loop: a slow Athena never holds back what is posted.
                        self._memory_task = self._spawn(self._keep_memory())
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Could not post the room's progress")
                if self._closing:
                    raise asyncio.CancelledError
                await asyncio.sleep(self.poll_interval)
        finally:
            try:
                self.store.release_lease(lease, self.instance)
            except Exception:
                pass

    async def _keep_memory(self) -> None:
        while True:
            try:
                await _cancellable(self.room.memory.sync())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Room %s: team memory is behind (%s); will retry", self.room.key, exc)
                await asyncio.sleep(30)
            await asyncio.sleep(max(self.poll_interval, 2.0))

    async def close(self) -> None:
        self._closing = True
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ── Room → people ───────────────────────────────────────────────────────

    def can_see(self, person: Person, item: FeedItem) -> bool:
        """Whether ``person`` may see this item in full (for surfaces that show each person their own view)."""
        return self.room.can(person, "viewer") and (not item.held_for or item.held_for == person.id)

    def recheck_audience(self) -> None:
        """Check who can see this surface again before the next post (someone
        joined or left it, or the room's members changed)."""
        self._audience_checked = 0.0

    async def _audience_reason(self) -> str:
        """Why the room may not be shown here now ("" if it may), checked at most
        every ``audience_seconds`` unless ``recheck_audience`` was called."""
        now = time.monotonic()
        if self._audience_checked and now - self._audience_checked <= self.audience_seconds:
            return self._paused
        self._audience_checked = now
        try:
            reason = await self.surface.audience(self.room) or ""
        except Exception as exc:
            reason = f"I could not check who can see this ({exc})"
        if reason != self._paused:
            was = self._paused
            self._paused = reason
            self.store.surface_map_put(self.room.key, self.surface.key, "flags", "paused", reason,
                                       retention_days=self.retention_days)
            if reason:
                logger.warning("Room %s paused on %s: %s", self.room.key, self.surface.key, reason)
                await self.surface.say(None, f"I've stopped posting the {self.room.id} room here: {reason}.")
            elif was:
                await self.surface.say(None, f"Everyone here can see the {self.room.id} room again; "
                                             "carrying on.")
        return reason

    #: Posts of one item that may fail in a row before it is skipped, so one
    #: update the surface refuses cannot hold back everything after it.
    max_post_failures = 5

    async def sync(self) -> None:
        """Post every room event and question since the last delivered one.

        Each item is posted once and its place saved only after it was posted:
        a failure stops here, and the next sync retries from that item. An item
        the surface keeps refusing is skipped after ``max_post_failures`` tries.
        """
        if await self._audience_reason():
            return  # never post to an audience that may not see the room
        self._reload_maps()
        # Always from the saved place: another process may have posted since.
        feed = RoomFeed(self.room, self._saved_cursor())
        items = feed.poll()
        if any(i.kind in ("member.changed", "room.visibility") for i in items):
            self.recheck_audience()
            if await self._audience_reason():
                return
        for item in items:
            if self._lease and not self.store.take_lease(self._lease, self.instance, self._lease_seconds):
                return  # another process took over delivery
            key = self._item_key(item)
            if self.store.delivered(self.room.key, self.surface.key, key) is None:
                try:
                    posted = await self._post(item, key)
                except Exception as exc:
                    failures = self._failures[key] = self._failures.get(key, 0) + 1
                    if failures < self.max_post_failures:
                        logger.warning("Could not post %s to %s (will retry): %s",
                                       item.kind, self.surface.key, exc)
                        return
                    logger.error("Skipping %s on %s after %d failed posts: %s",
                                 item.kind, self.surface.key, failures, exc)
                    posted = ""
                self._failures.pop(key, None)
                self.store.mark_delivered(self.room.key, self.surface.key, key, posted or "")
            self._save_cursor(item.cursor)
        await self._post_questions()

    async def _once(self, key: str, part: str, post) -> str:
        """Post one part of an item once, even when the item is retried."""
        done = f"{key}#{part}"
        previous = self.store.delivered(self.room.key, self.surface.key, done)
        if previous is not None:
            return previous
        posted = await post()
        self.store.mark_delivered(self.room.key, self.surface.key, done, posted or "")
        return posted

    @staticmethod
    def _item_key(item: FeedItem) -> str:
        entry = item.event or {}
        if item.kind == "progress":
            return f"progress:{item.workflow_id}:{entry.get('_id')}"
        return f"event:{entry.get('seq')}"

    def _thread_for(self, item: FeedItem) -> Optional[str]:
        if item.workflow_id and f"wf:{item.workflow_id}" in self._threads:
            return self._threads[f"wf:{item.workflow_id}"]
        follows = (item.event or {}).get("follows", "") if item.kind == "ask.started" else ""
        if follows and f"wf:{follows}" in self._threads:
            return self._threads[f"wf:{follows}"]
        if item.proposal:
            return self._threads.get(f"p:{item.proposal}")
        return None

    async def _post(self, item: FeedItem, key: str) -> str:
        thread = self._thread_for(item)
        if item.kind == "proposal.opened":
            revision_of = (item.event or {}).get("revision_of", "")
            thread = thread or self._threads.get(f"p:{revision_of}")
            diff = await self._diff(item.proposal)
            if item.held_for:
                asker = self._person(item.held_for)
                posted = await self._once(key, "withheld", lambda: self.surface.say(thread, item.withheld))
                if asker is not None:
                    await self._once(key, "held", lambda: self.surface.show_proposal(
                        thread or posted, item.text, diff, item.proposal, to=asker, held=True))
            else:
                posted = await self.surface.show_proposal(thread, item.text, diff, item.proposal)
            root = thread or posted
            self._remember("threads", f"p:{item.proposal}", root)
            self._remember("latest", root, item.proposal)
            return posted
        if item.kind == "proposal.released":
            diff = await self._diff(item.proposal)
            posted = await self.surface.show_proposal(thread, item.text, diff, item.proposal)
            self._remember("latest", thread or posted, item.proposal)
            return posted
        if item.kind == "ask.started" and thread:
            if item.workflow_id:
                self._remember("threads", f"wf:{item.workflow_id}", thread)
            if (item.event or {}).get("follows"):
                return await self.surface.say(thread, item.text)
            return thread  # the request itself is the thread
        if item.held_for:
            posted = await self._once(key, "withheld", lambda: self.surface.say(thread, item.withheld))
            asker = self._person(item.held_for)
            if asker is not None:
                await self._once(key, "held", lambda: self.surface.say(
                    thread or posted, item.text, detail=item.detail[:1500], to=asker))
        else:
            posted = await self.surface.say(thread, item.text, detail=item.detail[:1500])
        if item.workflow_id and not thread:
            self._remember("threads", f"wf:{item.workflow_id}", posted)
        return posted

    async def _diff(self, proposal_id: str) -> str:
        try:
            return "".join(c.unified() for c in await self.room.diff(proposal_id)) or "(no text changes)"
        except Exception as exc:
            return f"(could not show the change: {exc})"

    def _person(self, person_id: str) -> Optional[Person]:
        return self.room.identities.get(self.room.tenant, person_id) or Person(
            self.room.tenant, person_id, self.room.name_of(person_id))

    def _questions(self) -> List[Dict[str, Any]]:
        """What the room's own work is waiting on people for: questions routed to
        people, and agents asking for sign-off. Nothing from other rooms or tenants."""
        hitl = getattr(self.agent, "hitl", None)
        if hitl is None:
            return []
        workflows = {e.get("workflow_id") for e in self.room.events()
                     if e.get("type") == "ask.started" and e.get("workflow_id")}
        return [q for q in hitl.inbox(tenant=self.room.tenant)
                if q.get("kind") in ("input_request", "approval")
                and ((q.get("context") or {}).get("mesh_workflow_id")
                     or (q.get("context") or {}).get("workflow_id")) in workflows]

    def _asker(self, question: Dict[str, Any]) -> str:
        context = question.get("context") or {}
        workflow = context.get("mesh_workflow_id") or context.get("workflow_id", "")
        started = next((e for e in self.room.events() if e.get("type") == "ask.started"
                        and e.get("workflow_id") == workflow), None)
        return str((started or {}).get("by") or "")

    def _private_question(self, question: Dict[str, Any]) -> bool:
        context = question.get("context") or {}
        workflow = context.get("mesh_workflow_id") or context.get("workflow_id", "")
        return bool(workflow) and bool(self.room.private_sources(workflow))

    async def _post_questions(self) -> None:
        for question in self._questions():
            key = f"question:{question['id']}"
            if self.store.delivered(self.room.key, self.surface.key, key) is not None:
                continue
            context = question.get("context") or {}
            workflow = context.get("mesh_workflow_id") or context.get("workflow_id", "")
            thread = self._threads.get(f"wf:{workflow}")
            private = bool(workflow) and bool(self.room.private_sources(workflow))
            detail = "" if private else "\n".join(
                f"{step}: {text[:600]}" for step, text in (context.get("upstream") or {}).items())
            need = f" ({context['capability']})" if context.get("capability") not in (None, "", "human") else ""
            note = "\n(The work so far used private access, so its details are not shown here.)" if private else ""
            if question.get("kind") == "approval" and not private:
                detail = "\n".join(filter(None, [detail, str(context.get("evaluator_note") or "")]))
            asks = "sign-off" if question.get("kind") == "approval" else f"someone{need}"
            posted = await self.surface.say(
                thread, f"🙋 The agents need {asks}: {question.get('title')}{note}", detail=detail)
            self._remember("asked", question["id"], thread or posted)
            self.store.mark_delivered(self.room.key, self.surface.key, key, posted or "")

    # ── People → room ───────────────────────────────────────────────────────

    def receive(self, person: Person, text: str, *, message_id: str, thread: Optional[str] = None,
                addressed: bool = False) -> bool:
        """Record a message from ``person`` (as the surface authenticated them), once.

        Call this before acknowledging the message to the surface: once it
        returns, the message will be handled even if this process stops.
        Returns False for a message already received (a redelivery).
        """
        if not isinstance(person, Person) or person.tenant != self.room.tenant:
            raise RoomPermissionError(f"{person!r} is not a person in tenant {self.room.tenant}")
        if not message_id:
            raise ValueError("Every message needs the surface's id for it, so it is handled once")
        return self.store.receive_message(self.room.key, self.surface.key, message_id, {
            "person": person.to_record(), "text": text, "thread": thread or "",
            "addressed": bool(addressed), "at": time.time()})

    async def hear(self, person: Person, text: str, *, message_id: str, thread: Optional[str] = None,
                   addressed: bool = False) -> None:
        """``receive`` and ``handle`` in one call."""
        if self.receive(person, text, message_id=message_id, thread=thread, addressed=addressed):
            await self.handle(message_id)

    @staticmethod
    def _root(record: Dict[str, Any]) -> Tuple[str, bool]:
        thread, message_id = record.get("thread") or "", record["message_id"]
        in_thread = bool(thread) and thread != message_id
        return (thread if in_thread else message_id), in_thread

    async def handle(self, message_id: str) -> None:
        """Handle a received message: in order within its thread, once, as its sender.

        Whoever holds a thread handles its waiting messages oldest first, so a
        message is never handled before an earlier one in the same thread.
        """
        record = next((m for m in self.store.pending_messages(self.room.key, self.surface.key)
                       if m.get("message_id") == message_id), None)
        if record is None:
            return
        root, _ = self._root(record)
        lock, holder = f"{self.room.key}:surface:{self.surface.key}:thread:{root}", uuid.uuid4().hex
        while not self.store.take_lease(lock, holder, 90):
            await asyncio.sleep(0.05)
        keep = asyncio.create_task(self._keep(lock, holder, 90))
        try:
            while True:
                # Re-read every time: another process may have handled some meanwhile.
                waiting = [m for m in self.store.pending_messages(self.room.key, self.surface.key)
                           if self._root(m)[0] == root]
                if not any(m["message_id"] == message_id for m in waiting):
                    return
                oldest = waiting[0]
                await self._handle(oldest, *self._root(oldest))
                self.store.message_handled(self.room.key, self.surface.key, oldest["message_id"])
        finally:
            keep.cancel()
            self.store.release_lease(lock, holder)

    async def _keep(self, lease: str, holder: str, seconds: float) -> None:
        # Held while the turn runs; if this process stops, it lapses and another takes over.
        while True:
            await asyncio.sleep(seconds / 3)
            self.store.take_lease(lease, holder, seconds)

    async def _handle(self, record: Dict[str, Any], root: str, in_thread: bool) -> None:
        self._reload_maps()
        person = Person.from_record(record["person"])
        text = record.get("text", "")
        if not record.get("addressed") and not (in_thread and root in self.threads()):
            return  # not for the room: people talking elsewhere in the channel
        if await self._audience_reason():
            await self.surface.notice(root, f"I'm not working on the {self.room.id} room here right now: "
                                            f"{self._paused}.", to=person)
            return
        history = [{"person": e.get("name", ""), "text": e.get("text", "")}
                   for e in self.store.transcript(self.room.key, self.surface.key, root, limit=40)
                   if not e.get("to") or e.get("to") == person.id][-20:]
        self.store.append_transcript(self.room.key, self.surface.key, root, {
            "kind": "person", "person": person.id, "name": person.display, "text": text,
            "message_id": record["message_id"], "at": record.get("at", time.time())},
            retention_days=self.retention_days)
        memory = self.room.memory
        if memory is not None:
            memory.said_later(person, text, thread=root)   # queued: never delays the turn
        if in_thread and not history:
            history = await self.surface.history(root)
        waiting, private = [], False
        for question in self._questions():
            if self._asked.get(question["id"]) != root:
                continue
            asker = self._asker(question)
            if asker and self._private_question(question):
                if asker != person.id:
                    # Its details came from someone else's private access.
                    question = {"id": question["id"], "kind": question.get("kind"),
                                "title": f"(a question from {self.room.name_of(asker)}'s work; "
                                         "its details are private to them)"}
                else:
                    private = True
            waiting.append(question)

        def on_work(workflow_id: str) -> None:
            self._remember("threads", f"wf:{workflow_id}", root)

        def on_proposal(proposal_id: str) -> None:
            self._remember("threads", f"p:{proposal_id}", root)
            self._remember("latest", root, proposal_id)

        decisions: List[Dict[str, Any]] = []

        turn = await self.agent.converse(
            self.room, person, text, thread=root, message_id=record["message_id"],
            proposal=self._latest.get(root, ""), addressed=bool(record.get("addressed")),
            private=private,
            history=history, questions=waiting, on_work=on_work, on_proposal=on_proposal,
            on_decision=decisions.append,
        )
        for decision in decisions:
            await self._ask_to_confirm(decision, root, person)
        # A reply that may draw on private material goes to the person who asked alone.
        to = person if (private or turn.private) else None
        for reply in turn.replies:
            if reply:
                await self.surface.say(root, reply, to=to)
                if to is None and memory is not None:
                    memory.replied_later(reply, thread=root)
                self.store.append_transcript(self.room.key, self.surface.key, root, {
                    "kind": "agent", "name": "agent", "text": reply, "at": time.time(),
                    **({"to": person.id} if to else {})},
                    retention_days=self.retention_days)

    async def _ask_to_confirm(self, decision: Dict[str, Any], root: str, person: Person) -> None:
        decision = {**decision, "id": uuid.uuid4().hex, "tenant": person.tenant, "room": self.room.key,
                    "person": person.id, "thread": root,
                    "expires_at": time.time() + self.decision_seconds}
        self.store.put_decision(self.room.key, decision, self.decision_seconds)
        await self.surface.confirm(root, decision, to=person)

    async def press(self, person: Person, action: str, target: str, thread: Optional[str]) -> None:
        """A button pressed by ``person`` (as the surface authenticated them).

        ACCEPT and SHOW_CHANGE take a proposal; RELEASE and DISCARD a proposal
        held for that person; CONFIRM and CANCEL a prepared decision's id.
        """
        root = thread or self._threads.get(f"p:{target}")
        try:
            if action in (CONFIRM, CANCEL):
                await self._decide(person, action, target, root)
            elif action == ACCEPT:
                await self.room.accept(target, by=person)
            elif action == SHOW_CHANGE:
                proposal = self.room.proposal(target)
                if not self.room.visible_to(person, proposal):
                    raise RoomPermissionError(f"{person.display} cannot see {target}")
                # Only to them while the room is paused here, or when the work is held for them.
                private = bool(proposal.held_for) or bool(await self._audience_reason())
                await self.surface.say(root, f"The full change in {target}:", code=await self._diff(target),
                                       to=person if private else None)
            elif action == RELEASE:
                self.room.release(target, by=person)
            elif action == DISCARD:
                proposal = self.room.proposal(target)
                if proposal.held_for != person.id:
                    raise RoomPermissionError(f"Only the person it is held for can discard {target}")
                await self.room.reject(target, by=person, reason="discarded by the person it was held for")
        except RoomConflict as exc:
            await self.surface.say(root, (
                f"{exc.proposal_id} can't be applied: {', '.join(exc.paths)} changed since it was made. "
                "Ask me to redo it on the current files."))
        except (RoomPermissionError, KeyError, ValueError, RuntimeError) as exc:
            await self.surface.notice(root, str(exc).strip("'\""), to=person)

    async def _decide(self, person: Person, action: str, decision_id: str, root: Optional[str]) -> None:
        decision = self.store.get_decision(self.room.key, decision_id)
        if decision is None:
            raise ValueError("That decision has expired or was already made")
        if decision.get("person") != person.id or decision.get("tenant") != person.tenant:
            raise RoomPermissionError(f"Only {self.room.name_of(decision.get('person', ''))} can confirm that")
        if self.store.take_decision(self.room.key, decision_id) is None:
            raise ValueError("That decision was already made")
        if action == CANCEL:
            await self.surface.notice(root, "Cancelled.", to=person)
            return
        kind, target = decision.get("action"), decision.get("target", "")
        if kind == "accept":
            await self.room.accept(target, by=person)
        elif kind == "reject":
            await self.room.reject(target, by=person, reason=decision.get("reason") or "no reason given")
        elif kind == "release":
            self.room.release(target, by=person)
        elif kind == "discard":
            await self.room.reject(target, by=person, reason="discarded by the person it was held for")
        elif kind == "stop":
            if self.agent.stop(self.room, target, by=person, reason=decision.get("reason") or "stopped"):
                await self.surface.say(root, f"{person.display} stopped the work.")
        elif kind == "answer":
            await self._answer(person, target, decision.get("decision", "answered"),
                               decision.get("response", ""), root)

    async def _answer(self, person: Person, question_id: str, decision: str, response: str,
                      root: Optional[str]) -> None:
        from jarviscore.human.channels import to_hitl_decision

        self.room.require(person, "editor", "answer for the team")
        if question_id not in {q["id"] for q in self._questions()}:
            raise RoomPermissionError("That question is not waiting on this room's work")
        if not self.agent.hitl.resolve(question_id, to_hitl_decision(decision), response, by=person.key):
            raise ValueError("That question is no longer waiting")
        await self.surface.say(root, f"{person.display} answered the agents ({decision}).")

    async def answer_now(self, person: Person, question_id: str, response: str,
                         root: Optional[str]) -> None:
        """An informational answer, in the person's own words: passed on at once."""
        await self._answer(person, question_id, "answered", response, root)
