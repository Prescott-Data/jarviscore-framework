"""
jarviscore.integrations.connectors.slack
==========================================
SlackConnector — post messages, send DMs, read channels.

All calls go through Nexus credentials. The connection_id is an opaque
handle issued by the AuthManager — never raw Slack tokens in code.

Usage (in CoderSubAgent sandbox):
    from jarviscore.integrations.connectors.slack import SlackConnector
    slack = SlackConnector(connection_id=ctx["_nexus_connection_id"])
    result = slack.post_message(channel="#founders", text="Shift complete. See report.")
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SlackConnector:
    """
    Slack workspace connector.

    Reads SLACK_BOT_TOKEN from environment when connection_id = "env"
    (dev mode) or resolves credentials via NexusCallProxy in production.
    """

    def __init__(
        self,
        connection_id: Optional[str] = None,
        token: Optional[str] = None,
    ) -> None:
        self.connection_id = connection_id
        self._token = token or os.environ.get("SLACK_BOT_TOKEN")

    def _client(self):
        """Return a slack_sdk WebClient. Raises ImportError if not installed."""
        try:
            from slack_sdk import WebClient
        except ImportError:
            raise ImportError(
                "slack_sdk not installed. Install with: pip install slack-sdk"
            )
        return WebClient(token=self._token)

    # ── Write operations ──────────────────────────────────────────────────────

    def post_message(self, channel: str, text: str, blocks: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Post a message to a Slack channel.

        Args:
            channel: Channel name (e.g., "#founders") or channel ID
            text:    Message text (also used as fallback for blocks)
            blocks:  Optional Block Kit blocks for rich formatting

        Returns:
            {"status": "success", "ts": message_timestamp, "channel": channel_id}
        """
        try:
            client = self._client()
            kwargs: Dict[str, Any] = {"channel": channel, "text": text}
            if blocks:
                kwargs["blocks"] = blocks

            response = client.chat_postMessage(**kwargs)
            logger.info("[Slack] Posted to %s: %s", channel, text[:60])
            return {
                "status": "success",
                "ts": response.get("ts"),
                "channel": response.get("channel"),
            }
        except Exception as exc:
            logger.error("[Slack] post_message failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def send_dm(self, user_id: str, text: str) -> Dict[str, Any]:
        """
        Send a direct message to a Slack user.

        Args:
            user_id: Slack user ID (e.g., "U0123456789")
            text:    Message text

        Returns:
            {"status": "success", "ts": message_timestamp}
        """
        try:
            client = self._client()
            # Open DM channel then post
            dm = client.conversations_open(users=[user_id])
            dm_channel = dm["channel"]["id"]
            response = client.chat_postMessage(channel=dm_channel, text=text)
            return {"status": "success", "ts": response.get("ts")}
        except Exception as exc:
            logger.error("[Slack] send_dm failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def upload_file(self, channel: str, content: str, filename: str, title: str = "") -> Dict[str, Any]:
        """
        Upload a text file (e.g., a report or draft) to a Slack channel.

        Args:
            channel:  Channel name or ID
            content:  Text content of the file
            filename: Filename shown in Slack (e.g., "shift_report.md")
            title:    Optional file title shown in Slack

        Returns:
            {"status": "success", "file_id": str}
        """
        try:
            client = self._client()
            response = client.files_upload_v2(
                channel=channel,
                content=content,
                filename=filename,
                title=title or filename,
            )
            return {"status": "success", "file_id": response.get("file", {}).get("id")}
        except Exception as exc:
            logger.error("[Slack] upload_file failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    # ── Read operations ───────────────────────────────────────────────────────

    def read_channel(self, channel: str, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Read recent messages from a Slack channel.

        Args:
            channel: Channel name or ID
            limit:   Max number of messages to return (default 20)

        Returns:
            List of message dicts with {ts, text, user, type}
        """
        try:
            client = self._client()
            response = client.conversations_history(channel=channel, limit=limit)
            messages = response.get("messages", [])
            return [
                {
                    "ts": m.get("ts"),
                    "text": m.get("text", ""),
                    "user": m.get("user"),
                    "type": m.get("type"),
                }
                for m in messages
            ]
        except Exception as exc:
            logger.error("[Slack] read_channel failed: %s", exc)
            return []

    def get_channel_id(self, channel_name: str) -> Optional[str]:
        """Resolve a channel name like '#founders' to a channel ID."""
        name = channel_name.lstrip("#")
        try:
            client = self._client()
            for page in client.conversations_list(types="public_channel,private_channel"):
                for ch in page.get("channels", []):
                    if ch.get("name") == name:
                        return ch["id"]
        except Exception as exc:
            logger.error("[Slack] get_channel_id failed: %s", exc)
        return None
