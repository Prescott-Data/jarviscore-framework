"""
RoomAgent: the agent a team talks to about a room's work.

People talk about work in their own words: "looks good, ship it", "too long,
and name Sam for support", "why Wednesday?". A RoomAgent reads each message
with the thread it is in and does what the person means with the room's own
actions: it asks the mesh's agents for work, requests changes to a proposal
with the person's feedback, accepts or rejects it, files a person's own
version of a file, answers a question the agents asked people, or simply
replies. It is an ordinary AutoAgent with one extra Kernel role, ``room``, so
it reasons, remembers and is traced like every other agent.

Every action is taken as the person who spoke. Who that is comes from the
chat surface's own authentication (``acting_for``), never from the model, so
the room's roles apply and nobody can act as someone else by saying so.

    agent = mesh.add(RoomAgent)
    await mesh.start()
    reply = await agent.converse(room, "alice", "Fill in the risks from Dana's brief")

Chat surfaces (``RoomConversation``, ``SlackRoom``) call ``converse`` for each
message; subclass RoomAgent to change how it speaks (``system_prompt``) or
give it more tools (``RoomSubAgent``).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from jarviscore.auth.principal import act_for, acting_for
from jarviscore.kernel.kernel import Kernel
from jarviscore.kernel.subagent import BaseSubAgent
from jarviscore.profiles.autoagent import AutoAgent
from jarviscore.room.room import Room, RoomConflict, RoomPermissionError

logger = logging.getLogger("jarviscore.room.agent")

ROOM_ROLE = "room"

_CODE_BLOCK = re.compile(r"```[^\n`]*\n?(.*?)```", re.S)


@dataclass
class Turn:
    """One message to a RoomAgent and what it is part of."""

    room: Room
    person: str
    message: str
    #: The surface's id of the thread the message belongs to ("" for none).
    thread: str = ""
    #: The proposal this thread is about, if any.
    proposal: str = ""
    #: The person mentioned the agent (rather than replying in a thread).
    addressed: bool = False
    #: Earlier messages in the thread, oldest first: {"person", "text"}.
    history: List[Dict[str, str]] = field(default_factory=list)
    #: Questions the agents asked the people here that are not answered yet (HITL items).
    questions: List[Dict[str, Any]] = field(default_factory=list)
    #: Called with the workflow id when this turn starts work, so the surface
    #: can show the work's progress in this thread.
    on_work: Optional[Callable[[str], None]] = None
    #: Called with each proposal this turn opens, likewise.
    on_proposal: Optional[Callable[[str], None]] = None
    #: What the agent said back: its final answer, unless it chose to stay quiet.
    replies: List[str] = field(default_factory=list)
    #: The agent decided the message was not for it.
    quiet: bool = False


_turn: contextvars.ContextVar[Optional[Turn]] = contextvars.ContextVar("room_turn", default=None)


def _error(exc: Exception) -> Dict[str, Any]:
    return {"status": "error", "error": str(exc).strip("'\"")}


class RoomSubAgent(BaseSubAgent):
    """The ``room`` Kernel role: understands a message about a room's work and acts on it."""

    SYSTEM_PROMPT = """\
You are the agent a team talks to about its shared work, held in a room: a set of files that \
the team and its agents change together. You do not do the work on the files yourself. The \
team's agents do it when asked, and every change arrives as a proposal that people review: \
they accept it, ask for changes, turn it down, or write their own version.

Your task each turn is one message from one person in the team's chat, with the thread it \
belongs to. Work out what they mean, act on it with your tools as that person, and end the \
turn. Your task is handling the message, not finishing the work it asks for:
- a request for new work, or a question for the agents about the work: ask_agents, passing \
the request on in the person's own words with whatever from the thread makes it clear. The \
agents read the files and do the work; do not do it for them in the request.
- feedback on a proposal that should change it: request_changes, with their feedback
- a clear decision to take a proposal: accept; a clear decision to drop it: reject
- their own complete version of a file: propose_version
- an answer to a question the agents asked the people here: answer_question
- a question you can answer from the room itself (what a file says, what a change does, \
where things stand): look with room_status, read_file or show_change, and answer it
Work you start goes on after your turn: its progress and the proposal appear in the thread \
on their own, and the people review it there. Do not wait for it, check on it, or start it again.

Your final answer is posted in the thread as your reply, so write it to the people there: \
briefly what you did, the answer to their question, or one short question back when you are \
unsure what they want. Accepting and rejecting are decisions people make; when a message \
only leans one way, ask before acting. People also talk to each other in these threads; when \
a message is not for you, call stay_quiet and finish without acting.
Speak plainly and briefly, as a colleague would in chat. When a tool refuses (for example \
the person's role does not allow it), tell them why.
Finish as soon as you have acted, or decided to stay quiet."""

    def __init__(self, agent_id: str, llm_client, room_agent: "RoomAgent",
                 redis_store=None, blob_storage=None):
        self.room_agent = room_agent
        super().__init__(agent_id=agent_id, role=ROOM_ROLE, llm_client=llm_client,
                         redis_store=redis_store, blob_storage=blob_storage)

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    def setup_tools(self) -> None:
        self.register_tool("room_status", self._tool_room_status,
                           "Where the room stands: version, files, open proposals, work in progress. "
                           "Params: {}", phase="thinking")
        self.register_tool("read_file", self._tool_read_file,
                           "A file as it is in the room now. Params: {\"path\": \"plan.md\"}",
                           phase="thinking")
        self.register_tool("show_change", self._tool_show_change,
                           "What a proposal changes, as a diff. Params: {\"proposal\": \"p-1a2b3c4d\"} "
                           "(default: the thread's proposal)", phase="thinking")
        self.register_tool("ask_agents", self._tool_ask_agents,
                           "Ask the team's agents to do work on the room's files; their changes come "
                           "back as a proposal in this thread. Params: {\"goal\": \"<the request, "
                           "complete enough to act on alone>\"}", phase="action")
        self.register_tool("request_changes", self._tool_request_changes,
                           "Turn a proposal down with the person's feedback and have the agents redo "
                           "it. Params: {\"feedback\": \"<what to change>\", \"proposal\": \"p-...\" "
                           "(default: the thread's)}", phase="action")
        self.register_tool("accept", self._tool_accept,
                           "Accept a proposal into the room. Params: {\"proposal\": \"p-...\" "
                           "(default: the thread's)}", phase="action")
        self.register_tool("reject", self._tool_reject,
                           "Turn a proposal down for good. Params: {\"reason\": \"<why>\", "
                           "\"proposal\": \"p-...\" (default: the thread's)}", phase="action")
        self.register_tool("propose_version", self._tool_propose_version,
                           "File the person's own version of a file as their proposal. Params: "
                           "{\"path\": \"plan.md\", \"pasted_block\": 1} to use the first ``` block "
                           "of their message exactly, or {\"path\": ..., \"content\": \"<file>\"}",
                           phase="action")
        self.register_tool("answer_question", self._tool_answer_question,
                           "Answer a question the agents asked the people here. Params: {\"question\": "
                           "\"<its id>\", \"answer\": \"<the person's answer>\", \"decision\": "
                           "\"answered|approved|rejected|declined\"}", phase="action")
        self.register_tool("stay_quiet", self._tool_stay_quiet,
                           "The message is not for you (people talking to each other): nothing is "
                           "posted. Params: {}", phase="action")

    # ── The turn ────────────────────────────────────────────────────────────

    @staticmethod
    def _turn() -> Turn:
        turn = _turn.get()
        if turn is None:
            raise RuntimeError("Room tools run inside RoomAgent.converse")
        return turn

    @staticmethod
    def _person() -> str:
        # Who acts comes from the surface's authentication, never from the model.
        return acting_for.get() or RoomSubAgent._turn().person

    def _proposal(self, proposal: str = "") -> str:
        chosen = proposal or self._turn().proposal
        if not chosen:
            raise ValueError("There is no proposal in this thread; name one, such as p-1a2b3c4d.")
        return chosen

    # ── Looking ─────────────────────────────────────────────────────────────

    async def _tool_room_status(self, **_) -> Dict[str, Any]:
        room = self._turn().room
        head = room.head()
        return {
            "status": "success",
            "room": room.id, "version": head.version, "last_changed_by": head.updated_by,
            "files": sorted(await room.files()),
            "open_proposals": [{"id": p.id, "title": p.title, "by": p.author, "for": p.asked_by,
                                "files": p.paths, "on_version": p.base_version}
                               for p in room.proposals("open")],
        }

    async def _tool_read_file(self, path: str, **_) -> Dict[str, Any]:
        room = self._turn().room
        data = await room.read(path)
        if data is None:
            return {"status": "error", "error": f"No file {path!r}; files: {sorted(await room.files())}"}
        try:
            return {"status": "success", "path": path, "version": room.head().version,
                    "content": data.decode("utf-8")}
        except UnicodeDecodeError:
            return {"status": "success", "path": path, "binary": True, "bytes": len(data)}

    async def _tool_show_change(self, proposal: str = "", **_) -> Dict[str, Any]:
        try:
            chosen = self._proposal(proposal)
            room = self._turn().room
            record = room.proposal(chosen)
            diff = "".join(change.unified() for change in await room.diff(chosen))
        except (KeyError, ValueError) as exc:
            return _error(exc)
        return {"status": "success", "proposal": chosen, "title": record.title,
                "state": record.status, "by": record.author, "for": record.asked_by,
                "reason": record.reason, "diff": diff[:12000]}

    # ── Acting ──────────────────────────────────────────────────────────────

    async def _tool_ask_agents(self, goal: str, **_) -> Dict[str, Any]:
        return self.room_agent._start_work(self._turn(), self._person(), goal)

    async def _tool_request_changes(self, feedback: str, proposal: str = "", **_) -> Dict[str, Any]:
        turn, person = self._turn(), self._person()
        try:
            chosen = self._proposal(proposal)
            record = turn.room.proposal(chosen)
            goal = record.title or feedback
            if record.status == "open":
                await turn.room.reject(chosen, by=person, reason=feedback)
            elif record.status in ("rejected", "conflicted"):
                goal = f"{goal}\n\n{person} now asks: {feedback}"
            else:
                return {"status": "error", "error": f"{chosen} is {record.status}; ask_agents for new work instead."}
        except (KeyError, ValueError, RoomPermissionError) as exc:
            return _error(exc)
        return self.room_agent._start_work(turn, person, goal, revision_of=chosen)

    async def _tool_accept(self, proposal: str = "", **_) -> Dict[str, Any]:
        turn, person = self._turn(), self._person()
        try:
            chosen = self._proposal(proposal)
            head = await turn.room.accept(chosen, by=person)
        except RoomConflict as exc:
            return {"status": "error", "error": (
                f"{', '.join(exc.paths)} changed since {exc.proposal_id} was made, so it cannot be "
                "applied. It can be redone on the current files (request_changes).")}
        except (KeyError, ValueError, RuntimeError, RoomPermissionError) as exc:
            return _error(exc)
        return {"status": "success", "accepted": chosen, "version": head.version}

    async def _tool_reject(self, reason: str, proposal: str = "", **_) -> Dict[str, Any]:
        turn, person = self._turn(), self._person()
        try:
            chosen = self._proposal(proposal)
            await turn.room.reject(chosen, by=person, reason=reason)
        except (KeyError, ValueError, RoomPermissionError) as exc:
            return _error(exc)
        return {"status": "success", "rejected": chosen}

    async def _tool_propose_version(self, path: str, content: str = "", pasted_block: int = 0,
                                    **_) -> Dict[str, Any]:
        turn, person = self._turn(), self._person()
        if pasted_block:
            blocks = _CODE_BLOCK.findall(turn.message)
            if not 0 < pasted_block <= len(blocks):
                return {"status": "error", "error": f"The message has {len(blocks)} ``` blocks."}
            content = blocks[pasted_block - 1]
        if not content:
            return {"status": "error", "error": "Give the file's content or the pasted block to use."}
        current = await turn.room.read(path)
        if current is not None and current.endswith(b"\n") and not content.endswith("\n"):
            content += "\n"
        replacing = turn.proposal if turn.proposal and turn.room.proposal(turn.proposal).status == "open" else ""
        try:
            turn.room.require(person, "editor", "propose changes")
            proposal = await turn.room.propose({path: content}, author=person, asked_by=person,
                                               title=f"{person}'s version of {path}",
                                               revision_of=replacing)
        except (ValueError, RoomPermissionError) as exc:
            return _error(exc)
        if proposal is None:
            return {"status": "success", "note": f"{path} already reads exactly like that."}
        if turn.on_proposal:
            turn.on_proposal(proposal.id)
        return {"status": "success", "proposed": proposal.id,
                "replaces": replacing or None}

    async def _tool_answer_question(self, question: str, answer: str, decision: str = "answered",
                                    **_) -> Dict[str, Any]:
        turn, person = self._turn(), self._person()
        if question not in {q["id"] for q in turn.questions}:
            return {"status": "error", "error": "That is not a question waiting for the people here."}
        from jarviscore.human.channels import to_hitl_decision

        try:
            stored = self.room_agent.hitl.resolve(question, to_hitl_decision(decision), answer, by=person)
        except ValueError as exc:
            return _error(exc)
        if not stored:
            return {"status": "error", "error": "The question is no longer waiting."}
        turn.questions = [q for q in turn.questions if q["id"] != question]
        return {"status": "success", "answered": question}

    async def _tool_stay_quiet(self, **_) -> Dict[str, Any]:
        self._turn().quiet = True
        return {"status": "success", "note": "Nothing will be posted. Finish now."}


class RoomKernel(Kernel):
    """A Kernel that can also run the ``room`` role."""

    def __init__(self, *args, room_agent: "RoomAgent", **kwargs):
        super().__init__(*args, **kwargs)
        self._room_agent = room_agent

    def _create_subagent(self, role: str, agent_id: str):
        if role != ROOM_ROLE:
            return super()._create_subagent(role, agent_id)
        subagent = RoomSubAgent(agent_id=agent_id, llm_client=self.llm_client,
                                room_agent=self._room_agent, redis_store=self.redis_store,
                                blob_storage=self.blob_storage)
        self._attach_mesh_tools(subagent)
        return subagent


class RoomAgent(AutoAgent):
    """The agent a team talks to about a room's work. See the module docstring."""

    role = "room"
    capabilities = ["room-conversation"]
    # People reach it through a chat surface; it is never a step in the work it starts.
    mesh_worker = False
    description = "Talks with a team about the work in its rooms and acts on it for them."
    system_prompt = "You help a team get its shared work done."
    default_kernel_role = ROOM_ROLE

    #: Options passed to ``Room.ask`` when someone asks for work (timeout, plan_template).
    ask_options: Dict[str, Any] = {}

    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(agent_id)
        self._work: set = set()

    def _create_kernel(self):
        config = self._mesh.config if self._mesh else {}
        profiles = dict(config.get("kernel_role_profiles") or {})
        profiles.setdefault(ROOM_ROLE, {
            "thinking_budget": 40_000, "action_budget": 30_000, "max_total_tokens": 80_000,
            "wall_clock_ms": 180_000, "emergency_turn_fuse": 12,
            "model_tier": "task", "complexity": "standard",
        })
        catalog = dict(config.get("kernel_role_catalog") or {})
        catalog.setdefault(ROOM_ROLE, "Talks with a team about a room's work and acts on it for them.")
        return RoomKernel(
            llm_client=self.llm, sandbox=self.sandbox, code_registry=self.code_registry,
            search_client=self.search, redis_store=getattr(self, "_redis_store", None),
            blob_storage=getattr(self, "_blob_storage", None),
            decision_client=getattr(self, "decisions", None),
            config={**config, "kernel_role_profiles": profiles, "kernel_role_catalog": catalog},
            room_agent=self,
        )

    async def converse(self, room: Room, person: str, message: str, **turn_fields) -> Turn:
        """Handle one message from ``person``; returns the turn with what was replied.

        ``person`` must come from the surface's own authentication: it is who the
        agent acts as. Other fields are those of ``Turn``.
        """
        turn = Turn(room=room, person=person, message=message, **turn_fields)
        token = _turn.set(turn)
        try:
            with act_for(person):
                result = await self.execute_task({"task": self._brief(turn), "context": {
                    # One conversation per room: the Kernel's memory carries it across messages.
                    "workflow_id": f"room-{room.id}-conversation",
                    "room_id": room.id,
                    "acting_for": person,
                }})
        finally:
            _turn.reset(token)
        if turn.quiet:
            return turn
        if result.get("status") == "success":
            answer = str(result.get("result_summary") or "").strip()
            if answer:
                turn.replies.append(answer)
        else:
            logger.warning("Room %s: could not handle %s's message: %s", room.id, person, result.get("error"))
            turn.replies.append("Sorry, I couldn't handle that just now. Could you say it again?")
        return turn

    @staticmethod
    def _brief(turn: Turn) -> str:
        situation: Dict[str, Any] = {"room": turn.room.id, "version": turn.room.head().version}
        if turn.proposal:
            try:
                p = turn.room.proposal(turn.proposal)
                situation["proposal_in_this_thread"] = {
                    "id": p.id, "title": p.title, "state": p.status, "by": p.author,
                    "for": p.asked_by, "files": p.paths}
            except KeyError:
                pass
        if turn.questions:
            situation["questions_from_the_agents_waiting_for_people_here"] = [
                {"id": q["id"], "question": q.get("content") or q.get("title")} for q in turn.questions]
        if turn.history:
            situation["thread_so_far"] = turn.history[-12:]
        how = "mentioning you" if turn.addressed else "in a thread you are part of"
        return (f"Handle this message from {turn.person}, posted {how}:\n\"\"\"\n{turn.message}\n\"\"\"\n\n"
                f"What is going on:\n{json.dumps(situation, ensure_ascii=False, default=str)}")

    def _start_work(self, turn: Turn, person: str, goal: str, revision_of: str = "") -> Dict[str, Any]:
        """Ask the mesh's agents for work on the room, in the background."""
        room = turn.room
        try:
            room.require(person, "editor", "ask for work")
        except RoomPermissionError as exc:
            return _error(exc)
        if getattr(room, "mesh", None) is None:
            return {"status": "error", "error": "No agents are connected to this room here."}
        from jarviscore.room.work import new_workflow_id

        workflow_id = new_workflow_id(room.id)
        if turn.on_work:
            turn.on_work(workflow_id)
        task = asyncio.create_task(self._work_on(room, person, goal, revision_of, workflow_id))
        self._work.add(task)
        task.add_done_callback(self._work.discard)
        return {"status": "success", "started": workflow_id,
                "note": ("The agents have the request and work on it after this turn; their progress "
                         "and proposal appear in the thread by themselves. Tell the person, then finish.")}

    async def _work_on(self, room: Room, person: str, goal: str, revision_of: str,
                       workflow_id: str) -> None:
        try:
            await room.ask(goal, asked_by=person, revision_of=revision_of,
                           workflow_id=workflow_id, **self.ask_options)
        except Exception:
            # The room recorded ask.failed with the reason; whoever follows the room sees it.
            logger.exception("Room work %s failed", workflow_id)

    async def teardown(self) -> None:
        for task in list(self._work):
            task.cancel()
        await asyncio.gather(*self._work, return_exceptions=True)
        await super().teardown()
