"""Test a room's conversation without a chat product or a model.

``MemorySurface`` keeps what the conversation posts, including what was shown
to one person privately and the confirmations it asked for. ``ScriptedRoomAgent``
runs the real room tools from a script instead of a model, so a test decides
what each message means and checks what the room and the surface do::

    async def ship_it(tools, turn):
        await tools.prepare_decision(action="accept")
        return "Confirm it and it's in."      # the agent's reply

    surface = MemorySurface()
    conversation = RoomConversation(room, ScriptedRoomAgent(ship_it), surface)
    await conversation.start()
    await conversation.hear(bob, "ship it", thread="m1", message_id="m2")
    await conversation.press(bob, CONFIRM, surface.confirmations[-1]["id"], "m1")
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from jarviscore.auth.people import Person
from jarviscore.room.agent import RoomAgent, RoomSubAgent
from jarviscore.room.conversation import ChatSurface


@dataclass
class Posted:
    id: str
    thread: Optional[str]
    text: str
    detail: str = ""
    code: str = ""
    proposal: str = ""
    #: Shown only to this person (their id), or "" for everyone here.
    to: str = ""
    held: bool = False
    #: A transient private note (a refusal, "Cancelled.").
    notice: bool = False


class MemorySurface(ChatSurface):
    """Keeps everything a room's conversation posts, in order.

    ``audience_problem`` is returned by ``audience`` (set it to pause the room here).
    """

    def __init__(self, key: str = "memory"):
        self.key = key
        self.posts: List[Posted] = []
        self.confirmations: List[Dict[str, Any]] = []
        self.said: Dict[str, List[Dict[str, str]]] = {}
        self.audience_problem: Optional[str] = None
        #: Make the next N posts fail (to test delivery retries).
        self.fail_next = 0
        self._ids = itertools.count(1)

    def _add(self, post: Posted) -> str:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("the surface is unavailable")
        self.posts.append(post)
        return post.id

    def _id(self) -> str:
        return f"bot-{next(self._ids)}"

    async def say(self, thread, text, *, detail="", code="", to=None):
        return self._add(Posted(self._id(), thread, text, detail, code, to=to.id if to else ""))

    async def notice(self, thread, text, *, to):
        return self._add(Posted(self._id(), thread, text, to=to.id, notice=True))

    async def show_proposal(self, thread, text, diff, proposal_id, *, to=None, held=False):
        return self._add(Posted(self._id(), thread, text, code=diff, proposal=proposal_id,
                                to=to.id if to else "", held=held))

    async def confirm(self, thread, decision, *, to):
        self.confirmations.append(decision)
        return self._add(Posted(self._id(), thread, decision["summary"] + "?", to=to.id))

    async def audience(self, room):
        return self.audience_problem

    async def history(self, thread):
        return list(self.said.get(thread, []))

    def thread(self, root: str) -> List[Posted]:
        """What was posted in ``root``'s thread (or as ``root`` itself)."""
        return [p for p in self.posts if p.thread == root or p.id == root]

    def texts(self, root: str) -> List[str]:
        """What everyone in ``root``'s thread sees."""
        return [p.text for p in self.thread(root) if not p.to]

    def seen_by(self, person: Person) -> List[Posted]:
        """Everything ``person`` can see here: what everyone sees, and what was shown only to them."""
        return [p for p in self.posts if not p.to or p.to == person.id]

    def public(self) -> List[Posted]:
        return [p for p in self.posts if not p.to]


class RoomTools:
    """The room agent's tools by the names the model calls them:
    ``await tools.prepare_decision(action="accept")``."""

    def __init__(self, subagent: RoomSubAgent):
        self._subagent = subagent

    def __getattr__(self, name: str):
        tool = getattr(self._subagent, f"_tool_{name}", None)
        return tool if tool is not None else getattr(self._subagent, name)


class ScriptedRoomAgent(RoomAgent):
    """The real room tools, driven by scripts instead of a model: one script per message.

    A script is ``async (tools, turn) -> reply``: it calls tools as the model
    would, and what it returns is the agent's final answer (None to say nothing).
    """

    def __init__(self, *scripts):
        super().__init__()
        self.scripts = list(scripts)
        self.briefs: List[str] = []

    async def _handle(self, turn):
        self.briefs.append(self._brief(turn))
        tools = RoomTools(RoomSubAgent("room-1", llm_client=None, room_agent=self))
        answer = await self.scripts.pop(0)(tools, turn)
        if answer and not turn.quiet:
            turn.replies.append(answer)
