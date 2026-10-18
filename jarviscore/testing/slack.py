"""A local stand-in for Slack, for testing a room's Slack bridge without a workspace.

It speaks the parts of the real protocol a bot uses: the Web API methods
(``auth.test``, ``users.info``, ``chat.postMessage``, ``chat.update``,
``conversations.replies``, ``apps.connections.open``) and a Socket Mode
websocket that pushes envelopes and expects them acknowledged. People are
played through ``say`` and ``click``.

    slack = FakeSlack(users={"U1": "alice"})
    await slack.start()
    client = SlackClient("xoxb-test", "xapp-test", api_url=slack.api_url)
    ...
    await slack.say("U1", f"<@{slack.bot_user_id}> draft the launch email", channel="C1")
"""

from __future__ import annotations

import asyncio
import itertools
import json
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from aiohttp import WSMsgType, web


class FakeSlack:
    def __init__(
        self,
        *,
        users: Optional[Dict[str, str]] = None,
        bot_token: str = "xoxb-test",
        app_token: str = "xapp-test",
        bot_user_id: str = "UBOT",
    ):
        self.users = dict(users or {})
        self.bot_token = bot_token
        self.app_token = app_token
        self.bot_user_id = bot_user_id
        #: Every message in every channel, in order: dicts with ts, channel, user, text, thread_ts, blocks.
        self.messages: List[Dict[str, Any]] = []
        self.calls: List[str] = []
        self.acked: set = set()
        #: Answer the next N Web API calls with HTTP 429 (to exercise rate limiting).
        self.rate_limit_next = 0
        self._clock = itertools.count(1)
        self._sockets: List[web.WebSocketResponse] = []
        self._connected = asyncio.Event()
        self._runner: Optional[web.AppRunner] = None
        self.port = 0

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
        for ws in list(self._sockets):
            await ws.close()
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
            params = await request.json()
        else:
            params = dict(await request.post())
        handler = getattr(self, "_m_" + method.replace(".", "_"), None)
        if handler is None:
            return web.json_response({"ok": False, "error": "unknown_method"})
        return web.json_response(handler(params))

    def _m_auth_test(self, params):
        return {"ok": True, "user_id": self.bot_user_id, "bot_id": "B" + self.bot_user_id}

    def _m_users_info(self, params):
        user = params.get("user", "")
        if user not in self.users:
            return {"ok": False, "error": "user_not_found"}
        name = self.users[user]
        return {"ok": True, "user": {"id": user, "name": name,
                                     "profile": {"display_name": name, "real_name": name.title()}}}

    def _m_chat_postMessage(self, params):
        if not params.get("channel") or not (params.get("text") or params.get("blocks")):
            return {"ok": False, "error": "no_text"}
        blocks = params.get("blocks")
        if isinstance(blocks, str):
            blocks = json.loads(blocks)
        for block in blocks or []:
            text = (block.get("text") or {}).get("text", "")
            if len(text) > 3000:
                return {"ok": False, "error": "invalid_blocks"}
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
                    self.acked.add(json.loads(message.data).get("envelope_id"))
        finally:
            self._sockets.remove(ws)
            if not self._sockets:
                self._connected.clear()
        return ws

    # ── Playing people ──────────────────────────────────────────────────────

    async def connected(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout)

    async def _push(self, envelope: Dict[str, Any]) -> None:
        await self.connected()
        await self._sockets[-1].send_json(envelope)

    async def say(self, user: str, text: str, *, channel: str, thread_ts: Optional[str] = None) -> str:
        """``user`` posts ``text``; the bot hears it as Slack would tell it."""
        ts = self._ts()
        message = {"ts": ts, "channel": channel, "user": user, "text": text,
                   "thread_ts": thread_ts, "blocks": None}
        self.messages.append(message)
        event = {"type": "message", "channel": channel, "user": user, "text": text, "ts": ts,
                 "channel_type": "channel", "event_ts": ts}
        if thread_ts:
            event["thread_ts"] = thread_ts
        await self._push(self._envelope(event))
        if f"<@{self.bot_user_id}>" in text:
            await self._push(self._envelope({**event, "type": "app_mention"}))
        return ts

    async def click(self, user: str, action_id: str, value: str, *, message_ts: str) -> None:
        """``user`` presses a button on one of the bot's messages."""
        message = next(m for m in self.messages if m["ts"] == message_ts)
        await self._push({
            "envelope_id": uuid4().hex, "type": "interactive", "accepts_response_payload": False,
            "payload": {
                "type": "block_actions",
                "user": {"id": user, "username": self.users.get(user, user)},
                "channel": {"id": message["channel"]},
                "container": {"type": "message", "message_ts": message_ts,
                              "channel_id": message["channel"], "thread_ts": message.get("thread_ts")},
                "message": {"ts": message_ts, "thread_ts": message.get("thread_ts"),
                            "text": message["text"]},
                "actions": [{"action_id": action_id, "value": value, "type": "button"}],
            },
        })

    async def disconnect(self) -> None:
        """Ask the bot to reconnect, as Slack does every few hours."""
        await self._push({"type": "disconnect", "reason": "refresh_requested"})

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
        return web.json_response({"ok": True, "messages": self.messages})


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
