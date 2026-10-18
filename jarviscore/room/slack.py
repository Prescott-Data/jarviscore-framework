"""A room in a Slack channel: the team asks, watches, reviews and takes over there.

    room = Room.for_mesh(mesh, "launch")
    await SlackRoom(room, channel="C0123ABC").run()

or, with the agents running elsewhere on the mesh::

    jarviscore room slack launch --channel C0123ABC

In the channel, mention the bot with what you need. The agents do it on the
room's files and your message becomes the thread where it happens: the plan,
who took which step, and the proposal with its diff. In that thread::

    accept                   merge the proposal (or press Accept)
    reject <why>             turn it down
    redo <why>               turn it down and have the agents do it again
    diff                     the whole change
    show <file>              a file as it is in the room now
    edit <file> ```...```    your own version of a file, proposed as yours
    status · help

Everyone acts as themselves: the Slack user is who asked, accepted or
rejected, so the room's roles apply and agents use the asker's own accounts.
Work done on the room anywhere else (the CLI, another channel) shows up here
too.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union

from jarviscore.chat.slack import SlackClient, SlackError, escape, mentions, unescape, without_mention
from jarviscore.human.channels import HumanAnswer, HumanChannel, WorkItem, readable
from jarviscore.room.feed import describe
from jarviscore.room.room import Room, RoomConflict, RoomPermissionError
from jarviscore.room.work import new_workflow_id

logger = logging.getLogger("jarviscore.room.slack")

ACCEPT_ACTION = "room.accept"
DIFF_ACTION = "room.diff"

_PROPOSAL_ID = re.compile(r"^(p-[0-9a-f]{8})\b\s*", re.I)
_CODE_BLOCK = re.compile(r"```(.*?)```", re.S)
_WORD = re.compile(r"(\S+)\s*(.*)", re.S)
_ANSWERS = {"approve": "approved", "approved": "approved", "lgtm": "approved",
            "reject": "rejected", "decline": "declined"}
# Slack rejects section text over 3000 characters.
_SECTION_LIMIT = 2900

HELP = """\
Mention me with what you need and the agents do it on this room's files, in a thread.
In that thread:
• `accept` · merge the proposal
• `reject <why>` · turn it down
• `redo <why>` · turn it down and have it done again with your reason
• `diff` · the whole change
• `show <file>` · a file as it is now
• `edit <file>` and your version in a code block · propose your own change
• `status` · the room's version and open proposals"""


def _fenced(text: str, limit: int = _SECTION_LIMIT) -> str:
    body = escape(text)
    if len(body) > limit - 8:
        body = body[: limit - 10].rsplit("\n", 1)[0] + "\n…"
    return f"```{body}```"


class SlackPeopleChannel(HumanChannel):
    """A ``HumanAgent`` channel: the agents' questions go to the room's Slack channel.

    The question lands in the thread of the work that raised it, and whoever
    answers there answers it: a person hops into the work in progress.

        people = SlackPeopleChannel()
        mesh.add(HumanAgent("team", ["review"], channel=people))
        ...
        await SlackRoom(room, "C0123ABC", people_channel=people).run()
    """

    def __init__(self):
        self._bridge: Optional["SlackRoom"] = None
        self._attached = asyncio.Event()

    def attach(self, bridge: "SlackRoom") -> None:
        self._bridge = bridge
        self._attached.set()

    async def ask(self, item: WorkItem) -> HumanAnswer:
        await self._attached.wait()
        return await self._bridge.ask_people(item)

    async def notify(self, sender: str, message: Any) -> None:
        await self._attached.wait()
        await self._bridge._post(f"*{escape(sender)}*: {escape(readable(message, 1500))}")


class SlackRoom:
    """Connects one room to one Slack channel. See the module docstring."""

    def __init__(
        self,
        room: Room,
        channel: str,
        *,
        client: Optional[SlackClient] = None,
        people: Optional[Union[Mapping[str, str], Callable[[Dict[str, Any]], str]]] = None,
        poll_interval: float = 1.0,
        ask_options: Optional[Dict[str, Any]] = None,
        people_channel: Optional[SlackPeopleChannel] = None,
    ):
        self.room = room
        self.channel = channel
        self.client = client or SlackClient()
        self.people = people
        self.poll_interval = poll_interval
        self.ask_options = dict(ask_options or {})
        self.key = f"slack:{channel}"
        self._threads: Dict[str, str] = {}   # "wf:<workflow>" / "p:<proposal>" -> thread ts
        self._latest: Dict[str, str] = {}    # thread ts -> its latest proposal
        self._seq: Optional[int] = None
        self._seen: deque = deque(maxlen=500)
        self._tasks: set = set()
        self._feed_lock = asyncio.Lock()
        self._questions: Dict[str, deque] = {}  # thread ts -> futures awaiting a person
        if people_channel is not None:
            people_channel.attach(self)

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Check the token, load where this channel left off, and say hello the first time."""
        await self.client.start()
        self._load()
        if self._seq is None:
            events = self.room.events()
            self._seq = events[-1]["seq"] if events else 0
            self._save()
            head = self.room.head()
            files = len((await self.room.snapshot()).entries)
            await self.client.post(
                self.channel,
                f"Room *{escape(self.room.id)}* (v{head.version}, {files} files) is connected here. "
                "Mention me with what you need; review and decide in its thread. Say `help` for more.",
            )

    async def run(self) -> None:
        """Serve the channel until cancelled."""
        await self.start()
        follower = asyncio.create_task(self._follow(), name=f"slack-{self.room.id}-feed")
        try:
            async for envelope in self.client.events():
                self._spawn(self.handle_envelope(envelope))
        finally:
            follower.cancel()
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(follower, *self._tasks, return_exceptions=True)
            await self.client.close()

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(self._guarded(coroutine))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    @staticmethod
    async def _guarded(coroutine) -> None:
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Slack room handler failed")

    # ── State kept with the room, so a restart picks up where it left off ───

    def _load(self) -> None:
        state = (self.room.ledger.get_meta(self.room.id).get("chat") or {}).get(self.key) or {}
        self._seq = state.get("seq")
        self._threads = dict(state.get("threads") or {})
        self._latest = dict(state.get("latest") or {})

    def _save(self) -> None:
        # Keep the most recent threads; old ones are rarely answered in.
        threads = dict(list(self._threads.items())[-1000:])
        latest = dict(list(self._latest.items())[-500:])
        state = {"seq": self._seq, "threads": threads, "latest": latest}

        def change(meta):
            chat = dict(meta.get("chat") or {})
            chat[self.key] = state
            return {**meta, "chat": chat}

        self.room.ledger.update_meta(self.room.id, change)

    # ── Room → Slack ────────────────────────────────────────────────────────

    async def _follow(self) -> None:
        while True:
            try:
                await self.sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Could not post room events to Slack")
            await asyncio.sleep(self.poll_interval)

    async def sync(self) -> None:
        """Post every room event since the last one posted."""
        async with self._feed_lock:
            for event in self.room.events(self._seq or 0):
                try:
                    await self._render(event)
                except SlackError as exc:
                    logger.warning("Slack refused room event %s: %s", event.get("type"), exc.error)
                self._seq = event["seq"]
                self._save()

    async def _post(self, text: str, thread: Optional[str] = None, blocks=None) -> str:
        return await self.client.post(self.channel, text, thread_ts=thread, blocks=blocks)

    async def _render(self, event: Dict[str, Any]) -> None:
        kind = event.get("type", "")
        workflow = event.get("workflow_id") or ""
        proposal = event.get("proposal") or ""
        line = escape(describe(event))

        if kind == "proposal.opened":
            thread = (self._threads.get(f"p:{proposal}")
                      or (workflow and self._threads.get(f"wf:{workflow}"))
                      or self._threads.get(f"p:{event.get('revision_of')}"))
            text, blocks = await self._proposal_message(event, line)
            ts = await self._post(text, thread, blocks)
            root = thread or ts
            self._threads[f"p:{proposal}"] = root
            self._latest[root] = proposal
            return

        if workflow:
            thread = self._threads.get(f"wf:{workflow}")
        elif proposal:
            thread = self._threads.get(f"p:{proposal}")
        else:
            thread = None

        if kind == "ask.started" and thread:
            return  # the person's own message is the thread
        if kind == "ask.finished":
            summary = str(event.get("summary") or "").strip()
            if summary:
                line += "\n>" + escape(summary[:1500]).replace("\n", "\n>")
        ts = await self._post(line, thread)
        if workflow and not thread:
            self._threads[f"wf:{workflow}"] = ts

    async def _proposal_message(self, event: Dict[str, Any], line: str) -> Tuple[str, list]:
        proposal = event.get("proposal") or ""
        try:
            diff = "".join(change.unified() for change in await self.room.diff(proposal))
        except Exception as exc:  # the proposal is still worth announcing
            diff = f"(could not show the diff: {exc})"
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": line}},
            {"type": "section", "text": {"type": "mrkdwn", "text": _fenced(diff or "(no text changes)")}},
            {"type": "actions", "elements": [
                {"type": "button", "action_id": ACCEPT_ACTION, "style": "primary",
                 "text": {"type": "plain_text", "text": "Accept"}, "value": proposal},
                {"type": "button", "action_id": DIFF_ACTION,
                 "text": {"type": "plain_text", "text": "Full diff"}, "value": proposal},
            ]},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": (
                "Reply `accept`, `reject <why>`, `redo <why>`, or `edit <file>` with your own version.")}]},
        ]
        return line, blocks

    # ── Slack → room ────────────────────────────────────────────────────────

    async def person(self, user_id: str) -> str:
        """The room member a Slack user is (their Slack handle unless ``people`` says otherwise)."""
        if isinstance(self.people, Mapping) and user_id in self.people:
            return self.people[user_id]
        user = await self.client.user(user_id)
        if callable(self.people):
            return self.people({"id": user_id, **user})
        return str(user.get("name") or user_id)

    async def handle_envelope(self, envelope: Dict[str, Any]) -> None:
        payload = envelope.get("payload") or {}
        if envelope.get("type") == "events_api":
            await self.handle_message(payload.get("event") or {})
        elif envelope.get("type") == "interactive" and payload.get("type") == "block_actions":
            await self.handle_action(payload)

    async def handle_message(self, event: Dict[str, Any]) -> None:
        if event.get("type") not in ("message", "app_mention") or event.get("channel") != self.channel:
            return
        if event.get("bot_id") or event.get("subtype") not in (None, "", "file_share", "thread_broadcast"):
            return
        user, ts = event.get("user") or "", event.get("ts") or ""
        if not user or user == self.client.bot_user_id or ts in self._seen:
            return
        # Slack sends a mention twice (app_mention and message); act once.
        self._seen.append(ts)

        raw = event.get("text") or ""
        addressed = self.client.bot_user_id in mentions(raw)
        text = unescape(without_mention(raw, self.client.bot_user_id))
        thread = event.get("thread_ts") or ""
        in_thread = bool(thread) and thread != ts
        root = thread if in_thread else ts
        if in_thread and self._questions.get(root):
            await self._answer(root, user, text)
            return
        ours = in_thread and root in set(self._threads.values())
        if not addressed and not ours:
            return

        match = _WORD.match(text)
        command = match.group(1).lower().rstrip(":,.!") if match else ""
        rest = match.group(2).strip() if match else ""
        person = await self.person(user)
        if await self._is_command(command, rest, root, in_thread):
            await getattr(self, f"_cmd_{command}")(person, rest, root)
        elif addressed and text:
            await self._ask(person, text, root)
        elif addressed:
            await self._reply(root, HELP)

    async def _is_command(self, command: str, rest: str, root: str, in_thread: bool) -> bool:
        """Commands only when they read like one: "edit the plan to add a FAQ" is a request."""
        if command in ("help", "status"):
            return not rest
        if command in ("accept", "reject", "redo", "diff"):
            return in_thread or bool(_PROPOSAL_ID.match(rest))
        if command == "show":
            return not rest or rest.split("\n", 1)[0].strip().strip("`") in await self.room.files()
        if command == "edit":
            match = _WORD.match(rest)
            return bool(match and _CODE_BLOCK.search(rest) and not match.group(1).startswith("```"))
        return False

    async def handle_action(self, payload: Dict[str, Any]) -> None:
        channel = (payload.get("channel") or {}).get("id") or (payload.get("container") or {}).get("channel_id")
        if channel != self.channel:
            return
        message = payload.get("message") or {}
        root = message.get("thread_ts") or (payload.get("container") or {}).get("thread_ts") or message.get("ts", "")
        person = await self.person((payload.get("user") or {}).get("id", ""))
        for action in payload.get("actions") or []:
            proposal = str(action.get("value") or "")
            if action.get("action_id") == ACCEPT_ACTION:
                await self._cmd_accept(person, proposal, root)
            elif action.get("action_id") == DIFF_ACTION:
                await self._cmd_diff(person, proposal, root)

    # ── Agents asking people ────────────────────────────────────────────────

    async def ask_people(self, item: WorkItem) -> HumanAnswer:
        """Put a question from the agents in the channel and wait for someone's answer."""
        root = self._threads.get(f"wf:{item.workflow_id}") if item.workflow_id else None
        need = f" for {escape(item.capability)}" if item.capability not in ("", "human") else ""
        source = f", from {escape(item.asked_by)}" if item.asked_by not in ("", "workflow") else ""
        lines = [f":raising_hand: *A person is needed{need}*{source}:", escape(item.task)]
        for step, summary in item.upstream.items():
            lines.append(f">*{escape(step)}*: " + escape(summary[:600]).replace("\n", "\n>"))
        lines.append("Answer in this thread, or reply `approve`, `reject <why>` or `decline <why>`.")
        ts = await self._post("\n".join(lines), root)
        key = root or ts
        future = asyncio.get_running_loop().create_future()
        self._questions.setdefault(key, deque()).append(future)
        try:
            return await future
        finally:
            waiting = self._questions.get(key)
            if waiting is not None:
                if future in waiting:
                    waiting.remove(future)
                if not waiting:
                    self._questions.pop(key, None)

    async def _answer(self, root: str, user_id: str, text: str) -> None:
        person = await self.person(user_id)
        match = _WORD.match(text)
        word = match.group(1).lower().rstrip(":,.!") if match else ""
        if word in _ANSWERS:
            answer = HumanAnswer(_ANSWERS[word], match.group(2).strip(), by=person)
        else:
            answer = HumanAnswer("answered", text, by=person)
        waiting = self._questions.get(root)
        while waiting:
            future = waiting.popleft()
            if not future.done():
                future.set_result(answer)
                await self._reply(root, f"Thanks {escape(person)}, passed on to the agents.")
                return

    async def _reply(self, root: str, text: str) -> str:
        return await self._post(text, root)

    def _target(self, root: str, rest: str) -> Tuple[str, str]:
        """The proposal a command is about: one named first, else the thread's latest."""
        match = _PROPOSAL_ID.match(rest)
        if match:
            return match.group(1).lower(), rest[match.end():].strip()
        return self._latest.get(root, ""), rest

    async def _ask(self, person: str, goal: str, root: str, revision_of: str = "") -> None:
        if getattr(self.room, "mesh", None) is None:
            await self._reply(root, "No agents are connected to this room here.")
            return
        try:
            self.room.require(person, "editor", "ask for work")
        except RoomPermissionError as exc:
            await self._reply(root, escape(str(exc)))
            return
        workflow_id = new_workflow_id(self.room.id)
        self._threads[f"wf:{workflow_id}"] = root
        self._save()
        await self._reply(root, f"On it, {escape(person)}. Progress shows up here.")
        self._spawn(self._run_ask(person, goal, revision_of, workflow_id))

    async def _run_ask(self, person: str, goal: str, revision_of: str, workflow_id: str) -> None:
        try:
            await self.room.ask(goal, asked_by=person, revision_of=revision_of,
                                workflow_id=workflow_id, **self.ask_options)
        except Exception:
            # The room recorded ask.failed with the reason; the feed posts it.
            logger.exception("Room ask %s failed", workflow_id)
        await self.sync()

    async def _cmd_accept(self, person: str, rest: str, root: str) -> None:
        proposal, _ = self._target(root, rest)
        if not proposal:
            await self._reply(root, "There is no proposal here to accept.")
            return
        try:
            await self.room.accept(proposal, by=person)
        except RoomConflict as exc:
            await self._reply(root, (
                f"Not accepted: {escape(', '.join(exc.paths))} changed since {proposal} was made. "
                "Say `redo` to have it done again on the current files."))
            return
        except (RoomPermissionError, KeyError, ValueError, RuntimeError) as exc:
            await self._reply(root, escape(str(exc).strip("'\"")))
            return
        await self.sync()

    async def _cmd_reject(self, person: str, rest: str, root: str) -> None:
        proposal, reason = self._target(root, rest)
        if not proposal:
            await self._reply(root, "There is no proposal here to reject.")
            return
        if not reason:
            await self._reply(root, "Say why, so whoever picks it up knows: `reject <why>`.")
            return
        try:
            await self.room.reject(proposal, by=person, reason=reason)
        except (RoomPermissionError, KeyError, ValueError) as exc:
            await self._reply(root, escape(str(exc).strip("'\"")))
            return
        await self.sync()

    async def _cmd_redo(self, person: str, rest: str, root: str) -> None:
        proposal_id, reason = self._target(root, rest)
        if not proposal_id:
            await self._reply(root, "There is nothing here to redo. Mention me with what you need.")
            return
        try:
            proposal = self.room.proposal(proposal_id)
            if proposal.status == "open":
                if not reason:
                    await self._reply(root, "Say what to do differently: `redo <why>`.")
                    return
                proposal = await self.room.reject(proposal_id, by=person, reason=reason)
            elif proposal.status not in ("rejected", "conflicted"):
                await self._reply(root, f"{proposal_id} is {proposal.status}; mention me with what to do next.")
                return
        except (RoomPermissionError, KeyError, ValueError) as exc:
            await self._reply(root, escape(str(exc).strip("'\"")))
            return
        await self.sync()
        await self._ask(person, proposal.title or reason or "Redo it", root, revision_of=proposal_id)

    async def _cmd_diff(self, person: str, rest: str, root: str) -> None:
        proposal, _ = self._target(root, rest)
        if not proposal:
            await self._reply(root, "There is no proposal here.")
            return
        try:
            changes = await self.room.diff(proposal)
        except KeyError as exc:
            await self._reply(root, escape(str(exc).strip("'\"")))
            return
        diff = "".join(change.unified() for change in changes)
        tail = ""
        if len(escape(diff)) > _SECTION_LIMIT:
            tail = f"\nThe rest: `jarviscore room diff {self.room.id} {proposal}`"
        await self._reply(root, _fenced(diff or "(no text changes)") + tail)

    async def _cmd_show(self, person: str, rest: str, root: str) -> None:
        path = rest.split("\n", 1)[0].strip().strip("`")
        files = await self.room.files()
        if not path or path not in files:
            listing = ", ".join(f"`{escape(p)}`" for p in sorted(files)) or "none yet"
            prefix = f"No file `{escape(path)}` in the room. " if path else ""
            await self._reply(root, f"{prefix}Files: {listing}")
            return
        try:
            content = files[path].decode("utf-8")
        except UnicodeDecodeError:
            await self._reply(root, f"`{escape(path)}` is binary ({len(files[path])} bytes).")
            return
        version = self.room.head().version
        await self._reply(root, f"`{escape(path)}` at v{version}:\n" + _fenced(content or "(empty)"))

    async def _cmd_edit(self, person: str, rest: str, root: str) -> None:
        match = _WORD.match(rest)
        block = _CODE_BLOCK.search(rest)
        if not match or not block or match.group(1).startswith("```"):
            await self._reply(root, "Say `edit <file>` and put your version of it in a code block.")
            return
        path = match.group(1).strip("`")
        content = block.group(1)
        if content.startswith("\n"):
            content = content[1:]
        current = await self.room.read(path)
        if current is not None and current.endswith(b"\n") and not content.endswith("\n"):
            content += "\n"
        replacing = self._latest.get(root, "")
        if replacing and self.room.proposal(replacing).status != "open":
            replacing = ""
        try:
            self.room.require(person, "editor", "propose changes")
            proposal = await self.room.propose(
                {path: content}, author=person, asked_by=person, title=f"{person} edited {path}",
                revision_of=replacing)
        except (RoomPermissionError, ValueError) as exc:
            await self._reply(root, escape(str(exc).strip("'\"")))
            return
        if proposal is None:
            await self._reply(root, f"`{escape(path)}` already reads exactly like that.")
            return
        self._threads[f"p:{proposal.id}"] = root
        self._latest[root] = proposal.id
        self._save()
        await self.sync()

    async def _cmd_status(self, person: str, rest: str, root: str) -> None:
        head = self.room.head()
        files = len((await self.room.snapshot()).entries)
        lines = [f"*{escape(self.room.id)}* v{head.version}, {files} files, last change by "
                 f"{escape(head.updated_by or 'unknown')}"]
        for p in self.room.proposals("open"):
            lines.append(f"▲ {p.id} by {escape(p.author)}"
                         + (f" for {escape(p.asked_by)}" if p.asked_by else "")
                         + f": {escape(p.title)} ({len(p.changes)} files, on v{p.base_version})")
        if len(lines) == 1:
            lines.append("No open proposals.")
        await self._reply(root, "\n".join(lines))

    async def _cmd_help(self, person: str, rest: str, root: str) -> None:
        await self._reply(root, HELP)


async def serve_slack(room: Room, channel: str, **options) -> None:
    """Connect ``room`` to a Slack channel until cancelled. Options as for ``SlackRoom``."""
    await SlackRoom(room, channel, **options).run()
