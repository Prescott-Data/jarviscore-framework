"""
A room's conversation on a chat surface (Slack, Teams, your own web app).

``RoomConversation`` connects one room to one place people talk:

- What happens in the room shows up there: a request becomes a thread, and
  the plan, each step, the proposal with its change, and every decision are
  posted in it (``RoomFeed``). Work started elsewhere gets its own thread.
- When the agents need a person (a step routed to the HumanAgent that stands
  for the people here), the question is posted in the thread of the work that
  raised it.
- Every message people post there goes to the ``RoomAgent``, which works out
  what they mean and acts as them.

A surface only moves messages. Implement ``ChatSurface`` for yours, and call
``hear`` for each message and ``press`` for each button.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from jarviscore.room.agent import RoomAgent
from jarviscore.room.feed import RoomFeed
from jarviscore.room.room import Room, RoomConflict, RoomPermissionError

logger = logging.getLogger("jarviscore.room.conversation")

#: Buttons a surface may offer on a proposal.
ACCEPT = "accept"
SHOW_CHANGE = "show_change"


class ChatSurface:
    """Where a room's conversation is shown. Subclass it for your chat product.

    ``thread`` is the surface's id of the message a conversation hangs off, or
    None for the top level. ``say`` and ``show_proposal`` return the id of the
    message they post.
    """

    #: Unique per place a room is shown, e.g. "slack:C0123"; keys the saved state.
    key: str = "chat"

    async def say(self, thread: Optional[str], text: str, *, detail: str = "",
                  code: str = "") -> str:
        """Post ``text``; ``detail`` is quoted context, ``code`` is shown verbatim."""
        raise NotImplementedError

    async def show_proposal(self, thread: Optional[str], text: str, diff: str,
                            proposal_id: str) -> str:
        """Post a proposal for review: its headline, its change, ideally an Accept button."""
        return await self.say(thread, text, code=diff)

    async def history(self, thread: str) -> List[Dict[str, str]]:
        """Earlier messages in a thread, oldest first, as {"person", "text"}. Optional."""
        return []


class RoomConversation:
    """One room's conversation on one surface. See the module docstring."""

    def __init__(
        self,
        room: Room,
        agent: RoomAgent,
        surface: ChatSurface,
        *,
        people: Optional[str] = None,
        poll_interval: float = 1.0,
    ):
        self.room = room
        self.agent = agent
        self.surface = surface
        #: Role of the HumanAgent that stands for the people here; its questions are posted here.
        self.people = people
        self.poll_interval = poll_interval
        self.feed: Optional[RoomFeed] = None
        self._threads: Dict[str, str] = {}   # "wf:<workflow>" / "p:<proposal>" -> thread
        self._latest: Dict[str, str] = {}    # thread -> its latest proposal
        self._asked: Dict[str, str] = {}     # question id -> thread it was posted in
        self._lock = asyncio.Lock()

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Pick up where this surface left off; introduce the room the first time."""
        state = (self.room.redis_store.get_room_meta(self.room.id).get("chat") or {}).get(self.surface.key)
        if state:
            self.feed = RoomFeed(self.room, state.get("feed"))
            self._threads = dict(state.get("threads") or {})
            self._latest = dict(state.get("latest") or {})
            self._asked = dict(state.get("asked") or {})
            return
        self.feed = RoomFeed(self.room)
        self.feed.skip_history()
        self._save()
        head = self.room.head()
        files = len((await self.room.snapshot()).entries)
        await self.surface.say(None, (
            f"The {self.room.id} room is connected here (version {head.version}, {files} files). "
            "Mention me with what you need; the work and its review happen in a thread."))

    async def follow(self) -> None:
        """Post what happens in the room, and the agents' questions, until cancelled."""
        while True:
            try:
                await self.sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Could not post the room's progress")
            await asyncio.sleep(self.poll_interval)

    def _save(self) -> None:
        state = {"feed": self.feed.state(), "threads": dict(list(self._threads.items())[-1000:]),
                 "latest": dict(list(self._latest.items())[-500:]),
                 "asked": dict(list(self._asked.items())[-500:])}

        def change(meta):
            chat = dict(meta.get("chat") or {})
            chat[self.surface.key] = state
            return {**meta, "chat": chat}

        self.room.redis_store.update_room_meta(self.room.id, change)

    def threads(self) -> set:
        """Threads this conversation owns: messages there go to the room's agent."""
        return set(self._threads.values()) | set(self._asked.values())

    # ── Room → people ───────────────────────────────────────────────────────

    async def sync(self) -> None:
        async with self._lock:
            for item in self.feed.poll():
                try:
                    await self._post(item)
                except Exception as exc:
                    logger.warning("Could not post %s: %s", item.kind, exc)
            await self._post_questions()
            self._save()

    async def _post(self, item) -> None:
        workflow, proposal = item.workflow_id, item.proposal
        if item.kind == "proposal.opened":
            revision_of = (item.event or {}).get("revision_of", "")
            thread = (self._threads.get(f"p:{proposal}")
                      or (workflow and self._threads.get(f"wf:{workflow}"))
                      or self._threads.get(f"p:{revision_of}"))
            try:
                diff = "".join(c.unified() for c in await self.room.diff(proposal)) or "(no text changes)"
            except Exception as exc:
                diff = f"(could not show the change: {exc})"
            posted = await self.surface.show_proposal(thread, item.text, diff, proposal)
            root = thread or posted
            self._threads[f"p:{proposal}"] = root
            self._latest[root] = proposal
            return
        thread = (self._threads.get(f"wf:{workflow}") if workflow
                  else self._threads.get(f"p:{proposal}") if proposal else None)
        if item.kind == "ask.started" and thread:
            return  # the request itself is the thread
        posted = await self.surface.say(thread, item.text, detail=item.detail[:1500])
        if workflow and not thread:
            self._threads[f"wf:{workflow}"] = posted

    def _questions(self) -> List[Dict[str, Any]]:
        if not self.people or getattr(self.agent, "hitl", None) is None:
            return []
        return [q for q in self.agent.hitl.inbox(self.people) if q.get("kind") == "input_request"]

    async def _post_questions(self) -> None:
        for question in self._questions():
            if question["id"] in self._asked:
                continue
            context = question.get("context") or {}
            thread = self._threads.get(f"wf:{context.get('workflow_id')}")
            upstream = "\n".join(f"{step}: {text[:600]}" for step, text in (context.get("upstream") or {}).items())
            need = f" ({context['capability']})" if context.get("capability") not in (None, "", "human") else ""
            posted = await self.surface.say(
                thread, f"🙋 The agents need someone{need}: {question.get('title')}\nReply here.",
                detail=upstream)
            self._asked[question["id"]] = thread or posted

    # ── People → room ───────────────────────────────────────────────────────

    async def hear(self, person: str, text: str, *, thread: Optional[str] = None,
                   message_id: str = "", addressed: bool = False) -> None:
        """A message from ``person`` (as the surface authenticated them).

        ``thread`` is the thread it was posted in, if any; ``addressed`` that it
        mentions the agent. Messages elsewhere that do not mention it are not read.
        """
        in_thread = bool(thread) and thread != message_id
        root = thread if in_thread else message_id
        if not addressed and not (in_thread and root in self.threads()):
            return
        waiting = [q for q in self._questions() if self._asked.get(q["id"]) == root]

        def on_work(workflow_id: str) -> None:
            self._threads[f"wf:{workflow_id}"] = root

        def on_proposal(proposal_id: str) -> None:
            self._threads[f"p:{proposal_id}"] = root
            self._latest[root] = proposal_id

        turn = await self.agent.converse(
            self.room, person, text, thread=root, proposal=self._latest.get(root, ""),
            addressed=addressed, history=await self.surface.history(root) if in_thread else [],
            questions=waiting, on_work=on_work, on_proposal=on_proposal,
        )
        self._save()
        for reply in turn.replies:
            if reply:
                await self.surface.say(root, reply)
        await self.sync()

    async def press(self, person: str, action: str, proposal_id: str, thread: Optional[str]) -> None:
        """A button on a proposal: ``ACCEPT`` or ``SHOW_CHANGE``, pressed by ``person``."""
        root = thread or self._threads.get(f"p:{proposal_id}")
        if action == SHOW_CHANGE:
            diff = "".join(c.unified() for c in await self.room.diff(proposal_id))
            await self.surface.say(root, f"The full change in {proposal_id}:", code=diff or "(no text changes)")
            return
        if action != ACCEPT:
            return
        try:
            await self.room.accept(proposal_id, by=person)
        except RoomConflict as exc:
            await self.surface.say(root, (
                f"{proposal_id} can't be applied: {', '.join(exc.paths)} changed since it was made. "
                "Ask me to redo it on the current files."))
        except (RoomPermissionError, KeyError, ValueError, RuntimeError) as exc:
            await self.surface.say(root, str(exc).strip("'\""))
        await self.sync()
