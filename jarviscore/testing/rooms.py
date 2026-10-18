"""Test a room's conversation without a chat product or a model.

``MemorySurface`` keeps what the conversation posts. ``ScriptedRoomAgent``
runs the real room tools from a script instead of a model, so a test decides
what each message means and checks what the room and the surface do::

    async def accepts(tools, turn):
        await tools._tool_accept()
        return "Accepted."            # the agent's final answer, posted as its reply

    surface = MemorySurface()
    conversation = RoomConversation(room, ScriptedRoomAgent(accepts), surface)
    await conversation.start()
    await conversation.hear("bob", "ship it", thread="m1", message_id="m2")
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, List, Optional

from jarviscore.auth.principal import act_for
from jarviscore.room.agent import RoomAgent, RoomSubAgent, Turn, _turn
from jarviscore.room.conversation import ChatSurface


@dataclass
class Posted:
    id: str
    thread: Optional[str]
    text: str
    detail: str = ""
    code: str = ""
    proposal: str = ""


class MemorySurface(ChatSurface):
    """Keeps everything a room's conversation posts, in order."""

    def __init__(self, key: str = "memory"):
        self.key = key
        self.posts: List[Posted] = []
        self.said: Dict[str, List[Dict[str, str]]] = {}
        self._ids = itertools.count(1)

    async def say(self, thread, text, *, detail="", code=""):
        post = Posted(f"bot-{next(self._ids)}", thread, text, detail, code)
        self.posts.append(post)
        return post.id

    async def show_proposal(self, thread, text, diff, proposal_id):
        post = Posted(f"bot-{next(self._ids)}", thread, text, code=diff, proposal=proposal_id)
        self.posts.append(post)
        return post.id

    async def history(self, thread):
        return list(self.said.get(thread, []))

    def thread(self, root: str) -> List[Posted]:
        """What was posted in ``root``'s thread (or as ``root`` itself)."""
        return [p for p in self.posts if p.thread == root or p.id == root]

    def texts(self, root: str) -> List[str]:
        return [p.text for p in self.thread(root)]


class ScriptedRoomAgent(RoomAgent):
    """The real room tools, driven by scripts instead of a model: one script per message.

    A script is ``async (tools, turn) -> reply``: it calls tools as the model
    would, and what it returns is the agent's final answer (None to say nothing).
    """

    def __init__(self, *scripts):
        super().__init__()
        self.scripts = list(scripts)
        self.briefs: List[str] = []

    async def converse(self, room, person, message, **fields):
        turn = Turn(room=room, person=person, message=message, **fields)
        self.briefs.append(self._brief(turn))
        tools = RoomSubAgent("room-1", llm_client=None, room_agent=self)
        token = _turn.set(turn)
        try:
            with act_for(person):
                answer = await self.scripts.pop(0)(tools, turn)
        finally:
            _turn.reset(token)
        if answer and not turn.quiet:
            turn.replies.append(answer)
        return turn
