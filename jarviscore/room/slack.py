"""
A room in a Slack channel, with Slack reached through Nexus.

    agent = mesh.add(RoomAgent)
    mesh.add(HumanAgent("team", ["approval"], channel=None))
    await mesh.start()
    room = Room.for_mesh(mesh, "launch")
    await SlackRoom(room, agent, "C0123ABC", people="team").run()

People mention the bot with what they need and talk about the work in the
thread that follows; the ``RoomAgent`` works out what they mean and acts as
the Slack user who spoke. The Accept and Full change buttons on a proposal
act directly. Questions the agents have for the people in the channel (steps
routed to the ``people`` HumanAgent) are asked in the work's thread.

No Slack token is held here. Web API calls go through ``nexus_call`` with the
workspace's ``slack`` connection (the bot token), and the Socket Mode
connection, which needs no public URL, is opened by the ``slack_app`` atom
with the app-level token. Register both once::

    jarviscore nexus register slack --auth-type api_key --api-key xoxb-...
    jarviscore nexus register slack_app --auth-type api_key --api-key xapp-...

(or connect them through your Nexus gateway). The Slack app needs Socket Mode,
the bot scopes ``chat:write``, ``channels:history``, ``groups:history``,
``users:read`` and ``app_mentions:read``, the events ``app_mention``,
``message.channels`` and ``message.groups``, and Interactivity for the buttons.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from typing import Any, AsyncIterator, Callable, Dict, List, Mapping, Optional, Union

import aiohttp

from jarviscore.room.agent import RoomAgent
from jarviscore.room.conversation import ACCEPT, SHOW_CHANGE, ChatSurface, RoomConversation
from jarviscore.room.room import Room

logger = logging.getLogger("jarviscore.room.slack")

SLACK_API = "https://slack.com/api"
ACCEPT_ACTION = "room.accept"
CHANGE_ACTION = "room.show_change"
_ACTIONS = {ACCEPT_ACTION: ACCEPT, CHANGE_ACTION: SHOW_CHANGE}
# Slack refuses section text over 3000 characters.
_SECTION_LIMIT = 2900

_LINK = re.compile(r"<((?:https?|mailto|tel):[^|>]+)(?:\|([^>]+))?>")
_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]+)?>")


class SlackError(RuntimeError):
    """Slack answered ``ok: false``."""

    def __init__(self, method: str, error: str):
        super().__init__(f"Slack {method} failed: {error}")
        self.method = method
        self.error = error


def escape(text: str) -> str:
    """Text as Slack shows it literally (it reads &, < and > as markup)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unescape(text: str) -> str:
    """What the person typed, from Slack's markup of it."""
    text = _LINK.sub(lambda m: m.group(2) or m.group(1), text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _said(raw: str, bot_user_id: str) -> str:
    """A message's text without the mention of the bot it was addressed to."""
    if bot_user_id:
        raw = re.sub(rf"<@{re.escape(bot_user_id)}(?:\|[^>]+)?>", "", raw)
    return unescape(raw.strip())


class SlackApi:
    """Slack's Web API and Socket Mode, through Nexus.

    ``bot_call`` and ``app_call`` are ``nexus_call`` functions bound to the
    ``slack`` and ``slack_app`` connections; ``SlackApi.through_nexus(mesh)``
    builds them the way the Mesh builds every framework call to a provider.
    """

    def __init__(self, bot_call: Callable, app_call: Callable, *, api_url: str = SLACK_API,
                 max_retries: int = 3):
        self._bot_call = bot_call
        self._app_call = app_call
        self.api_url = api_url.rstrip("/")
        self.max_retries = max_retries
        self.bot_user_id = ""
        self._users: Dict[str, Dict[str, Any]] = {}

    @classmethod
    async def through_nexus(cls, mesh=None, *, api_url: str = SLACK_API) -> "SlackApi":
        from jarviscore.nexus.call_proxy import NexusCallProxy

        auth = getattr(mesh, "_auth_manager", None)
        proxy = NexusCallProxy(auth)

        async def handle(provider: str) -> str:
            found = await auth.discover(provider) if auth is not None else None
            return found or provider  # without a gateway, the local vault holds it by name

        return cls(NexusCallProxy.make_nexus_call_fn(proxy, await handle("slack")),
                   NexusCallProxy.make_nexus_call_fn(proxy, await handle("slack_app")),
                   api_url=api_url)

    async def call(self, method: str, **params) -> Dict[str, Any]:
        """A Web API method as the bot; waits out rate limits."""
        params = {k: v for k, v in params.items() if v is not None}
        for attempt in range(self.max_retries + 1):
            response = await self._bot_call("POST", f"{self.api_url}/{method}", json=params,
                                             headers={"Content-Type": "application/json; charset=utf-8"})
            if response.get("status_code") == 429 and attempt < self.max_retries:
                await asyncio.sleep(float((response.get("headers") or {}).get("retry-after", 1)))
                continue
            payload = response.get("json") or {}
            if payload.get("ok"):
                return payload
            raise SlackError(method, str(payload.get("error") or f"HTTP {response.get('status_code')}"))
        raise SlackError(method, "ratelimited")

    async def start(self) -> None:
        self.bot_user_id = str((await self.call("auth.test")).get("user_id") or "")

    async def user(self, user_id: str) -> Dict[str, Any]:
        if user_id not in self._users:
            try:
                self._users[user_id] = (await self.call("users.info", user=user_id)).get("user") or {}
            except SlackError as exc:
                logger.warning("Could not look up Slack user %s: %s", user_id, exc.error)
                return {}
        return self._users[user_id]

    async def post(self, channel: str, text: str, *, thread_ts: Optional[str] = None,
                   blocks: Optional[List[Dict[str, Any]]] = None) -> str:
        reply = await self.call("chat.postMessage", channel=channel, text=text, thread_ts=thread_ts,
                                blocks=blocks, unfurl_links=False, unfurl_media=False)
        return str(reply.get("ts") or "")

    async def replies(self, channel: str, ts: str) -> List[Dict[str, Any]]:
        return list((await self.call("conversations.replies", channel=channel, ts=ts, limit=50))
                    .get("messages") or [])

    async def events(self) -> AsyncIterator[Dict[str, Any]]:
        """Socket Mode envelopes, acknowledged as they arrive, reconnecting as Slack asks."""
        backoff = 1.0
        async with aiohttp.ClientSession() as session:
            while True:
                opened = await self._app_call("POST", f"{self.api_url}/apps.connections.open")
                payload = opened.get("json") or {}
                if not payload.get("ok"):
                    raise SlackError("apps.connections.open", str(payload.get("error") or opened.get("body")))
                try:
                    async with session.ws_connect(payload["url"], heartbeat=30) as ws:
                        backoff = 1.0
                        async for message in ws:
                            if message.type != aiohttp.WSMsgType.TEXT:
                                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    break
                                continue
                            envelope = json.loads(message.data)
                            if envelope.get("envelope_id"):
                                await ws.send_json({"envelope_id": envelope["envelope_id"]})
                            if envelope.get("type") == "disconnect":
                                break
                            if envelope.get("type") in ("events_api", "interactive"):
                                yield envelope
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    logger.warning("Slack connection lost (%s); reconnecting in %.0fs", exc, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)


def _fenced(text: str) -> str:
    body = escape(text)
    if len(body) > _SECTION_LIMIT - 8:
        body = body[: _SECTION_LIMIT - 10].rsplit("\n", 1)[0] + "\n…"
    return f"```{body}```"


class SlackSurface(ChatSurface):
    """Posts a room's conversation to one Slack channel."""

    def __init__(self, api: SlackApi, channel: str, people: Callable[[str], Any]):
        self.api = api
        self.channel = channel
        self.key = f"slack:{channel}"
        self._person = people

    async def say(self, thread, text, *, detail="", code=""):
        body = escape(text)
        if detail:
            body += "\n>" + escape(detail[:_SECTION_LIMIT]).replace("\n", "\n>")
        if code:
            body += "\n" + _fenced(code)
        return await self.api.post(self.channel, body, thread_ts=thread)

    async def show_proposal(self, thread, text, diff, proposal_id):
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": escape(text)}},
            {"type": "section", "text": {"type": "mrkdwn", "text": _fenced(diff)}},
            {"type": "actions", "elements": [
                {"type": "button", "action_id": ACCEPT_ACTION, "style": "primary",
                 "text": {"type": "plain_text", "text": "Accept"}, "value": proposal_id},
                {"type": "button", "action_id": CHANGE_ACTION,
                 "text": {"type": "plain_text", "text": "Full change"}, "value": proposal_id},
            ]},
        ]
        return await self.api.post(self.channel, escape(text), thread_ts=thread, blocks=blocks)

    async def history(self, thread):
        messages = []
        for message in (await self.api.replies(self.channel, thread))[-12:]:
            if message.get("bot_id"):
                messages.append({"person": "you", "text": unescape(message.get("text") or "")})
            elif message.get("user"):
                messages.append({"person": await self._person(message["user"]),
                                 "text": _said(message.get("text") or "", self.api.bot_user_id)})
        return messages


class SlackRoom:
    """Serves one room in one Slack channel. See the module docstring.

    ``members`` maps Slack user ids to room members (``{"U0123": "alice@acme.com"}``)
    or is a function of the Slack user; by default a member is their Slack handle.
    """

    def __init__(
        self,
        room: Room,
        agent: RoomAgent,
        channel: str,
        *,
        people: Optional[str] = None,
        members: Optional[Union[Mapping[str, str], Callable[[Dict[str, Any]], str]]] = None,
        api: Optional[SlackApi] = None,
        poll_interval: float = 1.0,
    ):
        self.room = room
        self.agent = agent
        self.channel = channel
        self.members = members
        self.people = people
        self.poll_interval = poll_interval
        self.api = api
        self.conversation: Optional[RoomConversation] = None
        self._seen: deque = deque(maxlen=500)
        self._tasks: set = set()

    async def start(self) -> None:
        """Connect to Slack through Nexus and the room to the channel."""
        if self.api is None:
            self.api = await SlackApi.through_nexus(getattr(self.room, "mesh", None))
        await self.api.start()
        self.conversation = RoomConversation(
            self.room, self.agent, SlackSurface(self.api, self.channel, self.person),
            people=self.people, poll_interval=self.poll_interval)
        await self.conversation.start()

    async def run(self) -> None:
        """Serve the channel until cancelled."""
        if self.conversation is None:
            await self.start()
        follower = asyncio.create_task(self.conversation.follow(), name=f"slack-{self.room.id}")
        try:
            async for envelope in self.api.events():
                task = asyncio.create_task(self._guarded(self.handle(envelope)))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        finally:
            follower.cancel()
            for task in list(self._tasks):
                task.cancel()
            await asyncio.gather(follower, *self._tasks, return_exceptions=True)

    @staticmethod
    async def _guarded(coroutine) -> None:
        try:
            await coroutine
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Slack room handler failed")

    async def person(self, user_id: str) -> str:
        """The room member a Slack user is."""
        if isinstance(self.members, Mapping) and user_id in self.members:
            return self.members[user_id]
        user = await self.api.user(user_id)
        if callable(self.members):
            return self.members({"id": user_id, **user})
        return str(user.get("name") or user_id)

    async def handle(self, envelope: Dict[str, Any]) -> None:
        payload = envelope.get("payload") or {}
        if envelope.get("type") == "events_api":
            await self._message(payload.get("event") or {})
        elif envelope.get("type") == "interactive" and payload.get("type") == "block_actions":
            await self._action(payload)

    async def _message(self, event: Dict[str, Any]) -> None:
        if event.get("type") not in ("message", "app_mention") or event.get("channel") != self.channel:
            return
        if event.get("bot_id") or event.get("subtype") not in (None, "", "file_share", "thread_broadcast"):
            return
        user, ts = event.get("user") or "", event.get("ts") or ""
        if not user or user == self.api.bot_user_id or ts in self._seen:
            return
        self._seen.append(ts)  # Slack sends a mention twice (app_mention and message)
        raw = event.get("text") or ""
        addressed = self.api.bot_user_id in _MENTION.findall(raw)
        thread = event.get("thread_ts") or None
        if not addressed and not (thread and thread in self.conversation.threads()):
            return
        text = _said(raw, self.api.bot_user_id)
        await self.conversation.hear(await self.person(user), text, thread=thread, message_id=ts,
                                     addressed=addressed)

    async def _action(self, payload: Dict[str, Any]) -> None:
        container = payload.get("container") or {}
        if ((payload.get("channel") or {}).get("id") or container.get("channel_id")) != self.channel:
            return
        message = payload.get("message") or {}
        thread = message.get("thread_ts") or container.get("thread_ts") or message.get("ts")
        person = await self.person((payload.get("user") or {}).get("id", ""))
        for action in payload.get("actions") or []:
            if action.get("action_id") in _ACTIONS:
                await self.conversation.press(person, _ACTIONS[action["action_id"]],
                                              str(action.get("value") or ""), thread)
