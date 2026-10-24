"""
Rooms in Slack, with Slack reached through Nexus.

    agent = mesh.add(RoomAgent)
    await mesh.start()
    slack = SlackApp(agent, tenant="acme")
    slack.connect(Room.for_mesh(mesh, "launch", tenant="acme"), "C0123ABC")
    await slack.run()

One ``SlackApp`` serves every room of a tenant in its Slack workspace, each in
its own channel. People mention the bot with what they need and talk about the
work in the thread that follows; the ``RoomAgent`` works out what they mean
and acts as the Slack user who spoke. Run it in as many processes as you like:
Slack shares events between their connections, and the rooms' state is in
Redis, so each message is handled once and each update posted once.

**Who is who.** A Slack user is a person in the tenant when they are a full
member of the workspace the app is installed in; guests, people from other
organisations in shared channels, and bots are not. Each person's first
message makes them a person of their own (``Identities``); link it to the same
person on another surface with a link code. Pass ``identify`` to map Slack
users to your own people instead.

**Who sees what.** A room is only shown in a channel everyone in it may see:
a private room needs a private channel whose members are all in the room; no
room is shown in a channel shared with another organisation. When that stops
being true (someone joins the channel, someone is removed from the room) the
app stops posting there and says why, until it is true again. Work held for
the person who asked (it used their own access) goes to them in a direct
message, with Release and Discard buttons.

**Decisions** the agent prepares are confirmed by the person with one tap in
a message only they see. The Accept and Full change buttons on a proposal
act directly, for whoever presses them, with their room role.

No Slack token is held here. Web API calls go through ``nexus_call`` with the
workspace's ``slack`` connection (the bot token), and the Socket Mode
connection, which needs no public URL, uses the ``slack_app`` connection (the
app-level token). Register both once::

    jarviscore nexus register slack --auth-type api_key --api-key xoxb-... \\
        --header-name Authorization --value-prefix "Bearer "
    jarviscore nexus register slack_app --auth-type api_key --api-key xapp-... \\
        --header-name Authorization --value-prefix "Bearer "

The Slack app needs Socket Mode and Interactivity; the bot scopes
``chat:write``, ``im:write``, ``channels:read``, ``groups:read``,
``channels:history``, ``groups:history``, ``users:read`` and
``app_mentions:read``; and the events ``app_mention``, ``message.channels``,
``message.groups``, ``member_joined_channel``, ``member_left_channel``,
``channel_shared`` and ``group_unarchive``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

import aiohttp

from jarviscore.auth.people import Account, Identities, IdentityError, Person
from jarviscore.room.agent import RoomAgent
from jarviscore.room.conversation import (
    ACCEPT, CANCEL, CONFIRM, DISCARD, RELEASE, SHOW_CHANGE, ChatSurface, RoomConversation,
)
from jarviscore.room.room import Room

logger = logging.getLogger("jarviscore.room.slack")

SLACK_API = "https://slack.com/api"
_ACTIONS = {f"room.{name}": name for name in (ACCEPT, SHOW_CHANGE, RELEASE, DISCARD, CONFIRM, CANCEL)}
# Slack refuses section text over 3000 characters.
_SECTION_LIMIT = 2900
# Events that can change who is in a channel, or whether it is shared.
_AUDIENCE_EVENTS = {"member_joined_channel", "member_left_channel", "channel_shared", "channel_unshared",
                    "group_unarchive", "channel_unarchive", "channel_convert_to_public",
                    "channel_convert_to_private"}

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


def _fenced(text: str) -> str:
    body = escape(text)
    if len(body) > _SECTION_LIMIT - 8:
        body = body[: _SECTION_LIMIT - 10].rsplit("\n", 1)[0] + "\n…"
    return f"```{body}```"


def _capped(text: str, limit: int = _SECTION_LIMIT) -> str:
    """Escaped text Slack accepts in one section or message (it refuses longer)."""
    body = escape(text)
    return body if len(body) <= limit else body[: limit - 1].rstrip() + "…"


def _quoted(text: str) -> str:
    return "\n>" + escape(text[:_SECTION_LIMIT]).replace("\n", "\n>")


class SlackApi:
    """Slack's Web API and Socket Mode, through Nexus.

    ``bot_call`` and ``app_call`` are ``nexus_call`` functions bound to the
    ``slack`` and ``slack_app`` connections; ``SlackApi.through_nexus(mesh)``
    builds them the way the Mesh builds every framework call to a provider.
    """

    def __init__(self, bot_call: Callable, app_call: Callable, *, api_url: str = SLACK_API,
                 max_retries: int = 3, user_seconds: float = 300.0):
        self._bot_call = bot_call
        self._app_call = app_call
        self.api_url = api_url.rstrip("/")
        self.max_retries = max_retries
        self.user_seconds = user_seconds
        self.bot_user_id = ""
        self.team_id = ""
        self._users: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._dms: Dict[str, str] = {}

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
        # Form-encoded, which every method accepts (read methods ignore a JSON body);
        # structured arguments such as blocks go as JSON strings, as Slack expects.
        form = {k: (json.dumps(v) if isinstance(v, (list, dict)) else str(v).lower() if isinstance(v, bool)
                    else str(v)) for k, v in params.items() if v is not None}
        for attempt in range(self.max_retries + 1):
            response = await self._bot_call("POST", f"{self.api_url}/{method}", data=form)
            if response.get("status_code") == 429 and attempt < self.max_retries:
                await asyncio.sleep(float((response.get("headers") or {}).get("retry-after", 1)))
                continue
            payload = response.get("json") or {}
            if payload.get("ok"):
                return payload
            raise SlackError(method, str(payload.get("error") or f"HTTP {response.get('status_code')}"))
        raise SlackError(method, "ratelimited")

    async def start(self) -> None:
        me = await self.call("auth.test")
        self.bot_user_id = str(me.get("user_id") or "")
        self.team_id = str(me.get("team_id") or "")

    async def user(self, user_id: str, *, fresh: bool = False) -> Dict[str, Any]:
        cached = self._users.get(user_id)
        if cached and not fresh and time.monotonic() - cached[0] < self.user_seconds:
            return cached[1]
        user = (await self.call("users.info", user=user_id)).get("user") or {}
        self._users[user_id] = (time.monotonic(), user)
        return user

    def forget_user(self, user_id: str) -> None:
        self._users.pop(user_id, None)

    async def channel(self, channel: str) -> Dict[str, Any]:
        return (await self.call("conversations.info", channel=channel)).get("channel") or {}

    async def members(self, channel: str) -> List[str]:
        members, cursor = [], None
        while True:
            page = await self.call("conversations.members", channel=channel, limit=200, cursor=cursor)
            members.extend(page.get("members") or [])
            cursor = (page.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return members

    async def post(self, channel: str, text: str, *, thread_ts: Optional[str] = None,
                   blocks: Optional[List[Dict[str, Any]]] = None) -> str:
        reply = await self.call("chat.postMessage", channel=channel, text=text, thread_ts=thread_ts,
                                blocks=blocks, unfurl_links=False, unfurl_media=False)
        return str(reply.get("ts") or "")

    async def post_ephemeral(self, channel: str, user: str, text: str, *, thread_ts: Optional[str] = None,
                             blocks: Optional[List[Dict[str, Any]]] = None) -> str:
        reply = await self.call("chat.postEphemeral", channel=channel, user=user, text=text,
                                thread_ts=thread_ts, blocks=blocks)
        return str(reply.get("message_ts") or "")

    async def direct(self, user: str, text: str, *, blocks: Optional[List[Dict[str, Any]]] = None,
                     channel: str = "", thread_ts: Optional[str] = None) -> str:
        """A direct message to ``user`` from the bot; without direct messages (no
        ``im:write``), a message only they see in ``channel``."""
        if user not in self._dms:
            try:
                opened = await self.call("conversations.open", users=user)
                self._dms[user] = str((opened.get("channel") or {}).get("id") or "")
            except SlackError as exc:
                if not channel:
                    raise
                logger.info("No direct messages (%s); showing it to %s alone in %s", exc.error, user, channel)
                self._dms[user] = ""
        if not self._dms[user]:
            return await self.post_ephemeral(channel, user, text, thread_ts=thread_ts, blocks=blocks)
        return await self.post(self._dms[user], text, blocks=blocks)

    async def replies(self, channel: str, ts: str) -> List[Dict[str, Any]]:
        return list((await self.call("conversations.replies", channel=channel, ts=ts, limit=50))
                    .get("messages") or [])

    async def events(self) -> AsyncIterator[Tuple[Dict[str, Any], Callable[[], Awaitable[None]]]]:
        """Socket Mode envelopes with the function that acknowledges each.

        Acknowledge an envelope once it is safely recorded: Slack sends an
        unacknowledged event again, so nothing is lost if this process stops.
        """
        backoff = 1.0
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    opened = await self._app_call("POST", f"{self.api_url}/apps.connections.open")
                    payload = opened.get("json") or {}
                    if not payload.get("ok"):
                        raise SlackError("apps.connections.open",
                                         str(payload.get("error") or opened.get("body")))
                    async with session.ws_connect(payload["url"], heartbeat=30) as ws:
                        backoff = 1.0
                        async for message in ws:
                            if message.type != aiohttp.WSMsgType.TEXT:
                                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    break
                                continue
                            envelope = json.loads(message.data)
                            if envelope.get("type") == "disconnect":
                                break
                            if envelope.get("type") not in ("events_api", "interactive"):
                                continue

                            async def ack(envelope_id=envelope.get("envelope_id"), ws=ws) -> None:
                                if envelope_id and not ws.closed:
                                    await ws.send_json({"envelope_id": envelope_id})

                            yield envelope, ack
                except (aiohttp.ClientError, asyncio.TimeoutError, SlackError) as exc:
                    logger.warning("Slack connection lost (%s); reconnecting in %.0fs", exc, backoff)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)


class SlackSurface(ChatSurface):
    """A room's conversation in one Slack channel."""

    def __init__(self, app: "SlackApp", channel: str):
        self.app = app
        self.api = app.api
        self.channel = channel
        self.key = f"slack:{channel}"

    def _value(self, room: Room, target: str) -> str:
        return json.dumps({"r": room.key, "t": target})

    def _button(self, action: str, label: str, target: str, style: str = "") -> Dict[str, Any]:
        button = {"type": "button", "action_id": f"room.{action}",
                  "text": {"type": "plain_text", "text": label},
                  "value": self._value(self.room, target)}
        if style:
            button["style"] = style
        return button

    @property
    def room(self) -> Room:
        return self.app.rooms[self.channel].room

    async def say(self, thread, text, *, detail="", code="", to=None):
        body = _capped(text, 1500) + (_quoted(detail[:1200]) if detail else "") + ("\n" + _fenced(code) if code else "")
        if to is None:
            return await self.api.post(self.channel, body, thread_ts=thread)
        user = self.app.slack_user(to)
        if not user:
            logger.info("%s has no Slack account here; not shown to them in Slack", to.key)
            return ""
        return await self.api.direct(user, f"*{escape(self.room.id)}*: {body}", channel=self.channel,
                                     thread_ts=thread)

    async def notice(self, thread, text, *, to):
        user = self.app.slack_user(to)
        if user:
            return await self.api.post_ephemeral(self.channel, user, _capped(text), thread_ts=thread)
        return ""

    async def show_proposal(self, thread, text, diff, proposal_id, *, to=None, held=False):
        if held:
            buttons = [self._button(RELEASE, "Release to the room", proposal_id, "primary"),
                       self._button(SHOW_CHANGE, "Full change", proposal_id),
                       self._button(DISCARD, "Discard", proposal_id, "danger")]
        else:
            buttons = [self._button(ACCEPT, "Accept", proposal_id, "primary"),
                       self._button(SHOW_CHANGE, "Full change", proposal_id)]
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": _capped(text)}},
            {"type": "section", "text": {"type": "mrkdwn", "text": _fenced(diff)}},
            {"type": "actions", "elements": buttons},
        ]
        if to is None:
            return await self.api.post(self.channel, _capped(text), thread_ts=thread, blocks=blocks)
        user = self.app.slack_user(to)
        if not user:
            return ""
        note = (f"In the *{escape(self.room.id)}* room, this work used your own access, so only you "
                "see it until you release it to the room.")
        blocks.insert(0, {"type": "context", "elements": [{"type": "mrkdwn", "text": note}]})
        return await self.api.direct(user, _capped(text), blocks=blocks, channel=self.channel,
                                     thread_ts=thread)

    async def confirm(self, thread, decision, *, to):
        user = self.app.slack_user(to)
        if not user:
            return ""
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": _capped(decision["summary"] + "?")}},
            {"type": "actions", "elements": [
                self._button(CONFIRM, "Confirm", decision["id"], "primary"),
                self._button(CANCEL, "Cancel", decision["id"])]},
        ]
        return await self.api.post_ephemeral(self.channel, user, _capped(decision["summary"] + "?"),
                                             thread_ts=thread, blocks=blocks)

    async def audience(self, room):
        info = await self.api.channel(self.channel)
        if info.get("is_ext_shared") or info.get("is_shared") or info.get("is_pending_ext_shared"):
            return "this channel is shared with another organisation"
        if info.get("is_archived"):
            return "this channel is archived"
        if room.settings().get("visibility") != "tenant" and not info.get("is_private"):
            return "the room is private, and anyone in the workspace can read this channel"
        for user_id in await self.api.members(self.channel):
            if user_id == self.api.bot_user_id:
                continue
            user = await self.api.user(user_id)
            if user.get("is_bot") or user.get("deleted"):
                continue
            person = await self.app.person(user_id)
            name = user.get("real_name") or user.get("name") or user_id
            if person is None:
                return f"{name} is in this channel but is not a member of the workspace"
            if not room.can(person, "viewer"):
                return f"{name} is in this channel but not in the room"
        return None

    async def history(self, thread):
        messages = []
        for message in (await self.api.replies(self.channel, thread))[-12:]:
            if message.get("bot_id"):
                messages.append({"person": "agent", "text": unescape(message.get("text") or "")})
            elif message.get("user"):
                person = await self.app.person(message["user"])
                messages.append({"person": person.display if person else "someone",
                                 "text": _said(message.get("text") or "", self.api.bot_user_id)})
        return messages


class SlackApp:
    """Serves a tenant's rooms in its Slack workspace. See the module docstring.

    ``identify(user)`` maps a Slack user (``users.info``) to a ``Person``, or
    None to refuse them; by default a full member of the workspace is a person
    of the tenant (``Identities``), and nobody else is.
    """

    def __init__(
        self,
        agent: RoomAgent,
        *,
        tenant: str,
        api: Optional[SlackApi] = None,
        identify: Optional[Callable[[Dict[str, Any]], Optional[Person]]] = None,
        poll_interval: float = 1.0,
    ):
        self.agent = agent
        self.tenant = tenant
        self.api = api
        self.identify = identify
        self.poll_interval = poll_interval
        #: channel -> the room's conversation there
        self.rooms: Dict[str, RoomConversation] = {}
        self._pending: List[Tuple[Room, str]] = []
        self._identities: Optional[Identities] = None
        self._tasks: set = set()

    def connect(self, room: Room, channel: str) -> None:
        """Show ``room`` in ``channel``. One room per channel."""
        if room.tenant != self.tenant:
            raise ValueError(f"Room {room.key} is not in tenant {self.tenant}")
        if channel in self.rooms or any(c == channel for _, c in self._pending):
            raise ValueError(f"Channel {channel} already shows a room")
        self._pending.append((room, channel))

    async def start(self) -> None:
        """Connect to Slack through Nexus, and each room to its channel."""
        if self.api is None:
            mesh = next((getattr(r, "mesh", None) for r, _ in self._pending), None)
            self.api = await SlackApi.through_nexus(mesh)
        await self.api.start()
        for room, channel in self._pending:
            self._identities = self._identities or Identities(room.redis_store)
            conversation = RoomConversation(room, self.agent, SlackSurface(self, channel),
                                            poll_interval=self.poll_interval)
            self.rooms[channel] = conversation
            await conversation.start()
        self._pending = []

    async def run(self) -> None:
        """Serve every connected room until cancelled."""
        if self._pending or not self.rooms:
            await self.start()
        followers = [asyncio.create_task(c.follow(), name=f"slack-{c.room.key}") for c in self.rooms.values()]
        events = self.api.events()
        try:
            async for envelope, ack in events:
                await self.receive(envelope, ack)
        finally:
            await events.aclose()  # closes the Socket Mode connection now, not at garbage collection
            for task in [*followers, *self._tasks]:
                task.cancel()
            await asyncio.gather(*followers, *self._tasks, return_exceptions=True)
            for conversation in self.rooms.values():
                await conversation.close()

    def _spawn(self, coroutine) -> None:
        async def guarded():
            try:
                await coroutine
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Slack handler failed")

        task = asyncio.create_task(guarded())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ── People ──────────────────────────────────────────────────────────────

    async def person(self, user_id: str) -> Optional[Person]:
        """The person a Slack user is here, or None if they are not one of the tenant's people."""
        try:
            user = await self.api.user(user_id)
        except SlackError as exc:
            logger.warning("Could not look up Slack user %s: %s", user_id, exc.error)
            return None
        if self.identify is not None:
            return self.identify({"id": user_id, **user})
        if (user.get("is_bot") or user.get("deleted") or user.get("is_restricted")
                or user.get("is_ultra_restricted") or user.get("team_id") != self.api.team_id):
            return None  # bots, guests and people from other organisations
        name = (user.get("profile") or {}).get("display_name") or user.get("real_name") or user.get("name") or ""
        try:
            return self._identities.person_for(Account(self.tenant, f"slack:{self.api.team_id}", user_id, name))
        except IdentityError as exc:
            logger.info("Slack user %s refused: %s", user_id, exc)
            return None

    def slack_user(self, person: Person) -> str:
        """The person's Slack user id in this workspace, or ""."""
        issuer = f"slack:{self.api.team_id}|"
        for ref in self._identities.accounts(person):
            if ref.startswith(issuer):
                return ref[len(issuer):]
        if person.id.startswith(f"slack:{self.api.team_id}."):
            return person.id.split(".", 1)[1]
        return ""

    # ── Events ──────────────────────────────────────────────────────────────

    async def receive(self, envelope: Dict[str, Any], ack: Callable[[], Awaitable[None]]) -> None:
        """One Socket Mode envelope: recorded, then acknowledged, then handled."""
        payload = envelope.get("payload") or {}
        if envelope.get("type") == "interactive":
            await ack()  # presses are checked and idempotent: handle after acknowledging
            if payload.get("type") == "block_actions":
                self._spawn(self._action(payload))
            return
        event = payload.get("event") or {}
        conversation = self.rooms.get(event.get("channel") or "")
        if event.get("type") in _AUDIENCE_EVENTS:
            if event.get("user"):
                self.api.forget_user(event["user"])
            for c in ([conversation] if conversation else self.rooms.values()):
                c.recheck_audience()
            await ack()
            return
        if conversation is None or event.get("type") not in ("message", "app_mention"):
            await ack()
            return
        try:
            message_id = await self._record(conversation, event)
        except Exception:
            logger.exception("Could not record a Slack message; Slack will send it again")
            return  # not acknowledged
        await ack()
        if message_id:
            self._spawn(conversation.handle(message_id))

    async def _record(self, conversation: RoomConversation, event: Dict[str, Any]) -> str:
        if event.get("bot_id") or event.get("subtype") not in (None, "", "file_share", "thread_broadcast"):
            return ""
        user, ts = event.get("user") or "", event.get("ts") or ""
        if not user or user == self.api.bot_user_id or not ts:
            return ""
        raw = event.get("text") or ""
        addressed = self.api.bot_user_id in _MENTION.findall(raw)
        thread = event.get("thread_ts") or None
        if not addressed and not (thread and thread in conversation.threads()):
            return ""  # people talking among themselves
        person = await self.person(user)
        if person is None:
            # Slack delivers a mention more than once (app_mention and message, and
            # redeliveries): say it once per message, whichever process hears it.
            if addressed and conversation.store.take_lease(
                    f"{conversation.room.key}:slack:refused:{event['channel']}:{ts}", uuid.uuid4().hex, 86400):
                self._spawn(self.api.post_ephemeral(
                    event["channel"], user, "I can only act for members of this workspace.", thread_ts=thread))
            return ""
        # Slack sends a mention twice (app_mention and message): the same ts is recorded once.
        received = conversation.receive(person, _said(raw, self.api.bot_user_id), message_id=ts,
                                        thread=thread, addressed=addressed)
        return ts if received else ""

    async def _action(self, payload: Dict[str, Any]) -> None:
        user = (payload.get("user") or {}).get("id", "")
        container = payload.get("container") or {}
        message = payload.get("message") or {}
        thread = message.get("thread_ts") or container.get("thread_ts") or None
        for action in payload.get("actions") or []:
            kind = _ACTIONS.get(action.get("action_id", ""))
            try:
                value = json.loads(action.get("value") or "{}")
            except json.JSONDecodeError:
                continue
            conversation = next((c for c in self.rooms.values() if c.room.key == value.get("r")), None)
            if kind is None or conversation is None:
                continue
            person = await self.person(user)
            if person is None:
                continue
            channel = (payload.get("channel") or {}).get("id") or container.get("channel_id")
            in_room_channel = channel == conversation.surface.channel
            await conversation.press(person, kind, str(value.get("t") or ""),
                                     thread if in_room_channel else None)
