"""A local stand-in for Slack, for testing rooms in Slack without a workspace.

It speaks the parts of Slack's protocol a bot uses, with Slack's behaviour
where correctness depends on it:

- Web API: ``auth.test``, ``users.info``, ``conversations.info``,
  ``conversations.members`` (paginated), ``conversations.replies``,
  ``conversations.open``, ``chat.postMessage``, ``chat.postEphemeral``,
  ``chat.update`` and ``apps.connections.open``.
- Socket Mode: events go to one of the open connections in turn (Slack shares
  them out, it does not copy them), and an event not acknowledged in time is
  sent again, as Slack does.
- People: members of the workspace, guests (``guest=True``), people from
  another organisation (``team``), and bots. Channels are public or private,
  and may be shared with another organisation.

People are played with ``say``, ``click``, ``join`` and ``leave`` (or over
HTTP: POST /_say, /_click). Point the Nexus ``slack`` and ``slack_app``
connections at it with tokens ``bot_token`` and ``app_token`` and a
``base_url`` of its address, and ``SlackApi(api_url=fake.api_url)`` talks to it
as it would to Slack.

    python -m jarviscore.testing.slack 18777 alice bob carol
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from aiohttp import WSMsgType, web


_FORM_ONLY = {"users.info": "user_not_found", "conversations.info": "channel_not_found",
              "conversations.members": "channel_not_found", "conversations.replies": "channel_not_found"}


class FakeSlack:
    def __init__(
        self,
        *,
        users: Optional[Dict[str, Union[str, Dict[str, Any]]]] = None,
        channels: Optional[Dict[str, Dict[str, Any]]] = None,
        team_id: str = "T1",
        bot_token: str = "xoxb-test",
        app_token: str = "xapp-test",
        bot_user_id: str = "UBOT",
        redeliver_after: float = 2.0,
        direct_messages: bool = True,
    ):
        self.team_id = team_id
        #: user id -> {"name", "team_id", "is_restricted", "is_bot", "deleted"}
        self.users: Dict[str, Dict[str, Any]] = {}
        for user_id, spec in (users or {}).items():
            self.add_user(user_id, **({"name": spec} if isinstance(spec, str) else spec))
        #: channel id -> {"is_private", "is_ext_shared", "members": [...]}; created on first use.
        self.channels: Dict[str, Dict[str, Any]] = {}
        for channel_id, spec in (channels or {}).items():
            self.add_channel(channel_id, **spec)
        self.bot_token = bot_token
        self.app_token = app_token
        self.bot_user_id = bot_user_id
        self.redeliver_after = redeliver_after
        #: False to answer conversations.open as an app without ``im:write`` is answered.
        self.direct_messages = direct_messages
        #: Every message in every channel (and DM), in order: ts, channel, user, text, thread_ts, blocks.
        self.messages: List[Dict[str, Any]] = []
        #: Messages only one person saw: the same fields plus "to".
        self.ephemeral: List[Dict[str, Any]] = []
        self.calls: List[str] = []
        self.acked: set = set()
        #: How many times each envelope was sent.
        self.sent: Dict[str, int] = {}
        #: Answer the next N Web API calls with HTTP 429 (to exercise rate limiting).
        self.rate_limit_next = 0
        self._clock = itertools.count(1)
        self._turn = itertools.count()
        self._sockets: List[web.WebSocketResponse] = []
        self._connected = asyncio.Event()
        self._runner: Optional[web.AppRunner] = None
        self._pending: Dict[str, asyncio.Task] = {}
        self.port = 0
        self.add_user(bot_user_id, name="bot", is_bot=True)

    # ── The workspace ───────────────────────────────────────────────────────

    def add_user(self, user_id: str, *, name: str = "", team: str = "", guest: bool = False,
                 is_bot: bool = False, deleted: bool = False, **_) -> None:
        self.users[user_id] = {"id": user_id, "name": name or user_id, "team_id": team or self.team_id,
                               "is_restricted": guest, "is_bot": is_bot, "deleted": deleted,
                               "real_name": (name or user_id).title(),
                               "profile": {"display_name": name or user_id}}

    def add_channel(self, channel_id: str, *, private: bool = True, ext_shared: bool = False,
                    members: Optional[List[str]] = None, **_) -> None:
        self.channels[channel_id] = {"id": channel_id, "is_private": private, "is_ext_shared": ext_shared,
                                     "is_shared": ext_shared, "is_archived": False,
                                     "members": list(members if members is not None else self.people())
                                     + [self.bot_user_id]}

    def people(self) -> List[str]:
        return [u for u, info in self.users.items() if not info["is_bot"]]

    def _channel(self, channel_id: str) -> Dict[str, Any]:
        if channel_id not in self.channels:
            self.add_channel(channel_id)
        return self.channels[channel_id]

    # ── Server ──────────────────────────────────────────────────────────────

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> "FakeSlack":
        app = web.Application()
        app.router.add_post("/api/{method}", self._api)
        app.router.add_get("/socket", self._socket)
        app.router.add_post("/_say", self._http_say)
        app.router.add_post("/_click", self._http_click)
        app.router.add_get("/_messages", self._http_messages)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.host = host
        return self

    async def stop(self) -> None:
        for task in self._pending.values():
            task.cancel()
        for ws in list(self._sockets):
            try:
                await asyncio.wait_for(ws.close(), 2)
            except asyncio.TimeoutError:
                pass
        if self._runner is not None:
            await self._runner.cleanup()

    @property
    def api_url(self) -> str:
        return f"http://{self.host}:{self.port}/api"

    def _ts(self) -> str:
        return f"{int(time.time())}.{next(self._clock):06d}"

    async def _api(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        self.calls.append(method)
        if self.rate_limit_next > 0:
            self.rate_limit_next -= 1
            return web.json_response({"ok": False, "error": "ratelimited"}, status=429,
                                     headers={"Retry-After": "0"})
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        expected = self.app_token if method == "apps.connections.open" else self.bot_token
        if token != expected:
            return web.json_response({"ok": False, "error": "invalid_auth"})
        if request.content_type == "application/json":
            if method in _FORM_ONLY:
                # Like Slack: read methods take form-encoded arguments and ignore a JSON body.
                return web.json_response({"ok": False, "error": _FORM_ONLY[method],
                                          "warning": "missing_charset"})
            params = await request.json()
        else:
            params = dict(await request.post())
        handler = getattr(self, "_m_" + method.replace(".", "_"), None)
        if handler is None:
            return web.json_response({"ok": False, "error": "unknown_method"})
        return web.json_response(handler(params))

    def _m_auth_test(self, params):
        return {"ok": True, "user_id": self.bot_user_id, "bot_id": "B" + self.bot_user_id,
                "team_id": self.team_id}

    def _m_users_info(self, params):
        user = self.users.get(params.get("user", ""))
        if user is None:
            return {"ok": False, "error": "user_not_found"}
        return {"ok": True, "user": user}

    def _m_conversations_info(self, params):
        channel = self.channels.get(params.get("channel", ""))
        if channel is None:
            return {"ok": False, "error": "channel_not_found"}
        return {"ok": True, "channel": {k: v for k, v in channel.items() if k != "members"}}

    def _m_conversations_members(self, params):
        channel = self.channels.get(params.get("channel", ""))
        if channel is None:
            return {"ok": False, "error": "channel_not_found"}
        start = int(params.get("cursor") or 0)
        limit = min(int(params.get("limit") or 100), 2)  # small pages, so paging is exercised
        page = channel["members"][start:start + limit]
        more = start + limit < len(channel["members"])
        return {"ok": True, "members": page,
                "response_metadata": {"next_cursor": str(start + limit) if more else ""}}

    def _m_conversations_open(self, params):
        if not self.direct_messages:
            return {"ok": False, "error": "missing_scope"}
        user = params.get("users", "")
        if user not in self.users:
            return {"ok": False, "error": "user_not_found"}
        channel = f"D{user}"
        self.channels.setdefault(channel, {"id": channel, "is_im": True, "is_private": True,
                                           "members": [user, self.bot_user_id]})
        return {"ok": True, "channel": {"id": channel}}

    def _check_blocks(self, params):
        blocks = params.get("blocks")
        if isinstance(blocks, str):
            blocks = json.loads(blocks)
        for block in blocks or []:
            if len((block.get("text") or {}).get("text", "")) > 3000:
                return None, {"ok": False, "error": "invalid_blocks"}
        return blocks, None

    def _m_chat_postMessage(self, params):
        if not params.get("channel") or not (params.get("text") or params.get("blocks")):
            return {"ok": False, "error": "no_text"}
        blocks, error = self._check_blocks(params)
        if error:
            return error
        if params["channel"] not in self.channels:
            return {"ok": False, "error": "channel_not_found"}
        message = {
            "ts": self._ts(), "channel": params["channel"], "user": self.bot_user_id,
            "bot_id": "B" + self.bot_user_id, "text": params.get("text", ""),
            "thread_ts": params.get("thread_ts") or None, "blocks": blocks,
        }
        self.messages.append(message)
        if self._sockets:
            # Slack tells the bot about its own messages too; bots must ignore them.
            echo = {"type": "message", "subtype": "bot_message", "channel": message["channel"],
                    "bot_id": message["bot_id"], "user": self.bot_user_id, "text": message["text"],
                    "ts": message["ts"], **({"thread_ts": message["thread_ts"]} if message["thread_ts"] else {})}
            asyncio.get_running_loop().create_task(self._push(self._envelope(echo)))
        return {"ok": True, "channel": params["channel"], "ts": message["ts"], "message": message}

    def _m_chat_postEphemeral(self, params):
        channel = self.channels.get(params.get("channel", ""))
        if channel is None:
            return {"ok": False, "error": "channel_not_found"}
        if params.get("user") not in channel["members"]:
            return {"ok": False, "error": "user_not_in_channel"}
        blocks, error = self._check_blocks(params)
        if error:
            return error
        ts = self._ts()
        self.ephemeral.append({"ts": ts, "channel": params["channel"], "to": params["user"],
                               "text": params.get("text", ""), "thread_ts": params.get("thread_ts"),
                               "blocks": blocks})
        return {"ok": True, "message_ts": ts}

    def _m_chat_update(self, params):
        for message in self.messages:
            if message["ts"] == params.get("ts") and message["channel"] == params.get("channel"):
                message["text"] = params.get("text", message["text"])
                message["blocks"] = params.get("blocks") or message["blocks"]
                return {"ok": True, "ts": message["ts"]}
        return {"ok": False, "error": "message_not_found"}

    def _m_conversations_replies(self, params):
        ts = params.get("ts")
        thread = [m for m in self.messages if m["channel"] == params.get("channel")
                  and (m["ts"] == ts or m.get("thread_ts") == ts)]
        return {"ok": True, "messages": thread}

    def _m_apps_connections_open(self, params):
        return {"ok": True, "url": f"ws://{self.host}:{self.port}/socket"}

    async def _socket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._sockets.append(ws)
        await ws.send_json({"type": "hello", "num_connections": len(self._sockets)})
        self._connected.set()
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    envelope_id = json.loads(message.data).get("envelope_id")
                    self.acked.add(envelope_id)
                    task = self._pending.pop(envelope_id, None)
                    if task:
                        task.cancel()
        finally:
            self._sockets.remove(ws)
            if not self._sockets:
                self._connected.clear()
        return ws

    # ── Playing people ──────────────────────────────────────────────────────

    async def connected(self, timeout: float = 10.0, count: int = 1) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while len(self._sockets) < count:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("no Socket Mode connection")
            await asyncio.sleep(0.01)

    async def _push(self, envelope: Dict[str, Any], attempt: int = 0) -> None:
        await self.connected()
        envelope_id = envelope["envelope_id"]
        # Like Slack: one of the open connections gets it, in turn.
        ws = self._sockets[next(self._turn) % len(self._sockets)]
        self.sent[envelope_id] = self.sent.get(envelope_id, 0) + 1
        try:
            await ws.send_json({**envelope, "retry_attempt": attempt})
        except ConnectionResetError:
            pass
        if attempt < 3 and envelope.get("type") == "events_api":
            self._pending[envelope_id] = asyncio.get_running_loop().create_task(
                self._redeliver(envelope, attempt + 1))

    async def _redeliver(self, envelope: Dict[str, Any], attempt: int) -> None:
        await asyncio.sleep(self.redeliver_after)
        if envelope["envelope_id"] not in self.acked:
            await self._push(envelope, attempt)

    async def say(self, user: str, text: str, *, channel: str, thread_ts: Optional[str] = None) -> str:
        """``user`` posts ``text``; the bot hears it as Slack would tell it."""
        self._channel(channel)
        ts = self._ts()
        message = {"ts": ts, "channel": channel, "user": user, "text": text,
                   "thread_ts": thread_ts, "blocks": None}
        self.messages.append(message)
        event = {"type": "message", "channel": channel, "user": user, "text": text, "ts": ts,
                 "channel_type": "group" if self.channels[channel]["is_private"] else "channel",
                 "event_ts": ts}
        if thread_ts:
            event["thread_ts"] = thread_ts
        await self._push(self._envelope(event))
        if f"<@{self.bot_user_id}>" in text:
            await self._push(self._envelope({**event, "type": "app_mention"}))
        return ts

    async def click(self, user: str, action_id: str, value: str, *, message_ts: str) -> None:
        """``user`` presses a button on one of the bot's messages (or one only they saw)."""
        message = next((m for m in self.messages if m["ts"] == message_ts), None)
        ephemeral = message is None
        if ephemeral:
            message = next(m for m in self.ephemeral if m["ts"] == message_ts)
        await self._push({
            "envelope_id": uuid4().hex, "type": "interactive", "accepts_response_payload": False,
            "payload": {
                "type": "block_actions",
                "user": {"id": user, "username": self.users.get(user, {}).get("name", user),
                         "team_id": self.users.get(user, {}).get("team_id", self.team_id)},
                "channel": {"id": message["channel"]},
                "container": {"type": "message", "message_ts": message_ts, "is_ephemeral": ephemeral,
                              "channel_id": message["channel"], "thread_ts": message.get("thread_ts")},
                **({} if ephemeral else {"message": {"ts": message_ts, "thread_ts": message.get("thread_ts"),
                                                     "text": message["text"]}}),
                "actions": [{"action_id": action_id, "value": value, "type": "button"}],
            },
        })

    async def join(self, user: str, channel: str) -> None:
        self._channel(channel)["members"].append(user)
        await self._push(self._envelope({"type": "member_joined_channel", "user": user, "channel": channel}))

    async def leave(self, user: str, channel: str) -> None:
        self._channel(channel)["members"].remove(user)
        await self._push(self._envelope({"type": "member_left_channel", "user": user, "channel": channel}))

    async def disconnect(self) -> None:
        """Ask the bot to reconnect, as Slack does every few hours."""
        await self._push({"envelope_id": uuid4().hex, "type": "disconnect", "reason": "refresh_requested"})

    def _envelope(self, event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "envelope_id": uuid4().hex, "type": "events_api", "accepts_response_payload": False,
            "payload": {"type": "event_callback", "event": event, "event_id": "Ev" + uuid4().hex[:10]},
        }

    def thread(self, ts: str) -> List[Dict[str, Any]]:
        return [m for m in self.messages if m["ts"] == ts or m.get("thread_ts") == ts]

    def bot_messages(self, channel: Optional[str] = None) -> List[Dict[str, Any]]:
        return [m for m in self.messages if m["user"] == self.bot_user_id
                and (channel is None or m["channel"] == channel)]

    def seen_only_by(self, user: str) -> List[Dict[str, Any]]:
        """What only ``user`` saw: messages shown to them alone, and their DMs with the bot."""
        return ([m for m in self.ephemeral if m["to"] == user]
                + [m for m in self.messages if m["channel"] == f"D{user}"])

    # ── The same over HTTP, for driving a fake in another process ───────────

    async def _http_say(self, request: web.Request) -> web.Response:
        body = await request.json()
        ts = await self.say(body["user"], body["text"], channel=body["channel"],
                            thread_ts=body.get("thread_ts"))
        return web.json_response({"ok": True, "ts": ts})

    async def _http_click(self, request: web.Request) -> web.Response:
        body = await request.json()
        await self.click(body["user"], body["action_id"], body["value"], message_ts=body["message_ts"])
        return web.json_response({"ok": True})

    async def _http_messages(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "messages": self.messages, "ephemeral": self.ephemeral})


async def main(port: int = 0) -> None:
    """``python -m jarviscore.testing.slack PORT``: a fake Slack for manual runs."""
    import sys

    users = {f"U{i}": name for i, name in enumerate(sys.argv[2:] or ["alice", "bob"], start=1)}
    slack = await FakeSlack(users=users).start(port=port)
    print(f"Fake Slack at {slack.api_url} (SLACK_API_URL); users {users}", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    import sys

    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 0))
