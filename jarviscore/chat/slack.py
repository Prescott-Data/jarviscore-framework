"""A small Slack client: Web API calls and Socket Mode events, on aiohttp.

Socket Mode needs no public URL: the app opens a websocket to Slack and Slack
pushes events down it, so a room's Slack bridge runs anywhere, a laptop
included. The Slack app needs:

* Socket Mode on, and an app-level token (``xapp-…``) with ``connections:write``
* a bot token (``xoxb-…``) with ``chat:write``, ``channels:history``,
  ``groups:history``, ``users:read`` and ``app_mentions:read``
* event subscriptions ``app_mention``, ``message.channels`` and ``message.groups``
* Interactivity on, for the Accept button

Tokens come from ``SLACK_BOT_TOKEN`` and ``SLACK_APP_TOKEN`` unless given.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional

import aiohttp

API_URL = "https://slack.com/api"

# Methods that take a JSON body; the rest take form fields.
_JSON_METHODS = {"chat.postMessage", "chat.update", "chat.postEphemeral"}

_LINK = re.compile(r"<((?:https?|mailto|tel):[^|>]+)(?:\|([^>]+))?>")
_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]+)?>")

logger = logging.getLogger("jarviscore.chat.slack")


class SlackError(RuntimeError):
    """Slack answered ``ok: false``."""

    def __init__(self, method: str, error: str, response: Optional[Dict[str, Any]] = None):
        super().__init__(f"Slack {method} failed: {error}")
        self.method = method
        self.error = error
        self.response = response or {}


def escape(text: str) -> str:
    """Text as Slack shows it literally (it reads &, < and > as markup)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unescape(text: str) -> str:
    """What the person typed, from Slack's markup of it."""
    # Slack turns typed links into <url|what they typed> or <url>.
    text = _LINK.sub(lambda m: m.group(2) or m.group(1), text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def mentions(text: str) -> List[str]:
    return _MENTION.findall(text or "")


def without_mention(text: str, user_id: str) -> str:
    return re.sub(rf"<@{re.escape(user_id)}(?:\|[^>]+)?>", "", text or "").strip()


class SlackClient:
    """Slack Web API plus Socket Mode, enough for a bot that works in channels."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        app_token: Optional[str] = None,
        *,
        api_url: Optional[str] = None,
        max_retries: int = 3,
    ):
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN", "")
        self.app_token = app_token or os.environ.get("SLACK_APP_TOKEN", "")
        if not self.bot_token:
            raise ValueError("Slack needs a bot token: set SLACK_BOT_TOKEN (xoxb-…)")
        self.api_url = (api_url or os.environ.get("SLACK_API_URL") or API_URL).rstrip("/")
        self.max_retries = max_retries
        self.bot_user_id = ""
        self._session: Optional[aiohttp.ClientSession] = None
        self._users: Dict[str, Dict[str, Any]] = {}

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # No session-wide timeout: the Socket Mode websocket stays open for hours.
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def call(self, method: str, *, token: Optional[str] = None, **params) -> Dict[str, Any]:
        """Call a Web API method; waits out rate limits."""
        session = await self._http()
        headers = {"Authorization": f"Bearer {token or self.bot_token}"}
        params = {k: v for k, v in params.items() if v is not None}
        if method in _JSON_METHODS:
            body: Dict[str, Any] = {"json": params}
        else:
            body = {"data": {k: v if isinstance(v, str) else json.dumps(v) for k, v in params.items()}}
        for attempt in range(self.max_retries + 1):
            async with session.post(f"{self.api_url}/{method}", headers=headers,
                                    timeout=aiohttp.ClientTimeout(total=30), **body) as resp:
                if resp.status == 429 and attempt < self.max_retries:
                    await asyncio.sleep(float(resp.headers.get("Retry-After", "1")))
                    continue
                payload = await resp.json(content_type=None)
            if payload.get("ok"):
                return payload
            if payload.get("error") == "ratelimited" and attempt < self.max_retries:
                await asyncio.sleep(1)
                continue
            raise SlackError(method, str(payload.get("error") or f"HTTP {resp.status}"), payload)
        raise SlackError(method, "ratelimited")

    async def start(self) -> Dict[str, Any]:
        """Check the bot token and learn the bot's own user id."""
        auth = await self.call("auth.test")
        self.bot_user_id = str(auth.get("user_id") or "")
        return auth

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
        """Post a message; returns its ts (the id threads hang off)."""
        reply = await self.call("chat.postMessage", channel=channel, text=text,
                                thread_ts=thread_ts, blocks=blocks, unfurl_links=False,
                                unfurl_media=False)
        return str(reply.get("ts") or "")

    async def update(self, channel: str, ts: str, text: str,
                     blocks: Optional[List[Dict[str, Any]]] = None) -> None:
        await self.call("chat.update", channel=channel, ts=ts, text=text, blocks=blocks)

    async def replies(self, channel: str, ts: str, oldest: Optional[str] = None) -> List[Dict[str, Any]]:
        """Messages in a thread, the parent first."""
        reply = await self.call("conversations.replies", channel=channel, ts=ts, oldest=oldest,
                                limit=200)
        return list(reply.get("messages") or [])

    async def events(self) -> AsyncIterator[Dict[str, Any]]:
        """Socket Mode envelopes, acknowledged as they arrive, for as long as you iterate.

        Reconnects when Slack asks (it refreshes connections every few hours)
        or the network drops.
        """
        if not self.app_token:
            raise ValueError("Slack Socket Mode needs an app-level token: set SLACK_APP_TOKEN (xapp-…)")
        backoff = 1.0
        while True:
            opened = await self.call("apps.connections.open", token=self.app_token)
            session = await self._http()
            try:
                async with session.ws_connect(opened["url"], heartbeat=30) as ws:
                    backoff = 1.0
                    async for message in ws:
                        if message.type != aiohttp.WSMsgType.TEXT:
                            if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                            continue
                        envelope = json.loads(message.data)
                        if envelope.get("envelope_id"):
                            await ws.send_json({"envelope_id": envelope["envelope_id"]})
                        kind = envelope.get("type")
                        if kind == "disconnect":
                            break
                        if kind in ("events_api", "interactive"):
                            yield envelope
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                logger.warning("Slack connection lost (%s); reconnecting in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
