"""
Natural Language Mailbox Manager for JarvisCore v1.0.1.

High-level API for agent-to-agent messaging with capability-based
routing. Wraps RedisContextStore mailbox primitives (Phase 1) with:
- Message envelopes (sender, timestamp, workflow context)
- Capability/role-based routing via Mesh indexes
- Broadcast to all mesh agents
- LLM context formatting with sensitive data scrubbing

Ported from IA/CA patterns:
- IA: kernel._ingest_mailbox() injects messages into scratchpad
- CA: _sanitize_mailbox_text() strips credentials before LLM sees them
- Both: Redis-backed durable FIFO queues per agent

We use Mesh.get_agents_by_capability() and Mesh._agent_registry
directly for routing — no separate router class needed since Mesh,
PeerClient, and StepClaimer already provide capability discovery.
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger("jarviscore.mailbox")


class MailboxManager:
    """
    High-level mailbox API for agent-to-agent messaging.

    Wraps RedisContextStore mailbox primitives with message envelopes,
    capability-based routing, and LLM context formatting.

    Example:
        # Direct send
        manager = MailboxManager("analyst-1", redis_store)
        manager.send("scraper-2", {"task": "scrape website"})

        # Capability-based send
        manager.send_by_capability("web_scraping", {"url": "..."}, mesh)

        # Read messages
        messages = manager.read()
        for msg in messages:
            print(f"From {msg['sender']}: {msg['message']}")

        # Format for LLM context
        context = manager.format_for_context(messages)
    """

    def __init__(self, agent_id: str, redis_store):
        """
        Initialize mailbox manager.

        Args:
            agent_id: This agent's unique ID (used as sender in envelopes)
            redis_store: RedisContextStore instance for persistence
        """
        self.agent_id = agent_id
        self.redis = redis_store
        self._logger = logging.getLogger(f"jarviscore.mailbox.{agent_id}")

    def send(
        self,
        target_agent_id: str,
        message: dict,
        workflow_id: str = None,
        step_id: str = None,
        context: dict = None,
    ) -> bool:
        """
        Send message to a specific agent by ID.

        Wraps message in an envelope with sender metadata before
        persisting to the target's Redis mailbox queue.

        Args:
            target_agent_id: Target agent's unique ID
            message: Message payload (dict)
            workflow_id: Optional workflow context
            step_id: Optional step context
            context: Optional additional metadata to share

        Returns:
            True if sent successfully
        """
        envelope = {
            "sender": self.agent_id,
            "message": message,
        }
        if workflow_id is not None:
            envelope["workflow_id"] = workflow_id
        if step_id is not None:
            envelope["step_id"] = step_id
        if context is not None:
            envelope["context"] = context

        self._logger.debug(
            f"Sending message to {target_agent_id}"
        )
        return self.redis.send_mailbox_message(target_agent_id, envelope)

    def send_by_capability(
        self,
        capability: str,
        message: dict,
        mesh,
        workflow_id: str = None,
        step_id: str = None,
        context: dict = None,
    ) -> bool:
        """
        Send message to first agent with a specific capability.

        Uses Mesh.get_agents_by_capability() for discovery — the same
        index used by StepClaimer and WorkflowEngine.

        Args:
            capability: Required capability (e.g., "analysis")
            message: Message payload
            mesh: Mesh instance for capability lookup
            workflow_id: Optional workflow context
            step_id: Optional step context
            context: Optional additional metadata

        Returns:
            True if agent found and message sent, False if no agent
            has the capability
        """
        agents = mesh.get_agents_by_capability(capability)
        if not agents:
            self._logger.warning(
                f"No agent found with capability: {capability}"
            )
            return False

        target_id = agents[0].agent_id
        return self.send(
            target_id, message,
            workflow_id=workflow_id,
            step_id=step_id,
            context=context,
        )

    def send_by_role(
        self,
        role: str,
        message: dict,
        mesh,
        workflow_id: str = None,
        step_id: str = None,
        context: dict = None,
    ) -> bool:
        """
        Send message to first agent with a specific role.

        Uses Mesh._agent_registry for lookup.

        Args:
            role: Target agent role (e.g., "analyst")
            message: Message payload
            mesh: Mesh instance for role lookup
            workflow_id: Optional workflow context
            step_id: Optional step context
            context: Optional additional metadata

        Returns:
            True if agent found and message sent, False if no agent
            has the role
        """
        agents = mesh._agent_registry.get(role, [])
        if not agents:
            self._logger.warning(f"No agent found with role: {role}")
            return False

        target_id = agents[0].agent_id
        return self.send(
            target_id, message,
            workflow_id=workflow_id,
            step_id=step_id,
            context=context,
        )

    def broadcast(
        self,
        message: dict,
        mesh,
        workflow_id: str = None,
        step_id: str = None,
        context: dict = None,
    ) -> int:
        """
        Broadcast message to all agents in mesh (excluding self).

        Args:
            message: Message payload
            mesh: Mesh instance for agent discovery
            workflow_id: Optional workflow context
            step_id: Optional step context
            context: Optional additional metadata

        Returns:
            Number of agents message was sent to
        """
        count = 0
        for agent in mesh.agents:
            if agent.agent_id != self.agent_id:
                if self.send(
                    agent.agent_id, message,
                    workflow_id=workflow_id,
                    step_id=step_id,
                    context=context,
                ):
                    count += 1
        return count

    def read(self, max_messages: int = 5) -> List[dict]:
        """
        Read and consume messages from mailbox (FIFO, destructive).

        Messages are removed from the queue after reading. Returns
        flattened envelopes with timestamp promoted from Redis wrapper.

        Args:
            max_messages: Maximum number of messages to read

        Returns:
            List of message envelopes with keys:
            sender, message, timestamp, and optional workflow_id/step_id/context
        """
        raw = self.redis.read_mailbox(self.agent_id, max_messages)
        return self._flatten(raw)

    def peek(self, limit: int = 10) -> List[dict]:
        """
        Peek at mailbox without consuming messages (non-destructive).

        Args:
            limit: Maximum number of messages to peek

        Returns:
            List of message envelopes (messages remain in mailbox)
        """
        raw = self.redis.peek_mailbox(self.agent_id, limit)
        return self._flatten(raw)

    def format_for_context(
        self,
        messages: List[dict],
        scrub: bool = True,
    ) -> str:
        """
        Format mailbox messages for LLM context injection.

        Creates markdown-formatted message list suitable for
        scratchpad/prompt injection. Optionally scrubs sensitive
        data (tokens, passwords, API keys) before formatting.

        Follows IA/CA pattern: kernel._ingest_mailbox() injects
        messages into agent scratchpad as structured text.

        Args:
            messages: List of message envelopes from read() or peek()
            scrub: If True, remove sensitive data before formatting

        Returns:
            Markdown-formatted string, or "" if no messages
        """
        if not messages:
            return ""

        lines = ["## MAILBOX MESSAGES", ""]

        for msg in messages:
            sender = msg.get("sender", "unknown")
            timestamp = msg.get("timestamp", 0)
            payload = msg.get("message", {})
            workflow_id = msg.get("workflow_id")
            step_id = msg.get("step_id")

            # Scrub sensitive data before LLM sees it
            if scrub and isinstance(payload, dict):
                from jarviscore.context.distillation import scrub_sensitive
                payload = scrub_sensitive(payload)

            # Format timestamp
            try:
                dt = datetime.fromtimestamp(timestamp)
                time_str = dt.strftime("%H:%M:%S")
            except (OSError, ValueError, OverflowError):
                time_str = "??:??:??"

            # Build header
            header = f"**[{time_str}] From: {sender}**"
            if workflow_id:
                header += f" (workflow: {workflow_id})"
            if step_id:
                header += f" (step: {step_id})"

            lines.append(header)

            # Format payload
            if isinstance(payload, dict):
                lines.append("```json")
                lines.append(json.dumps(payload, indent=2, default=str))
                lines.append("```")
            else:
                lines.append(str(payload))

            lines.append("")

        return "\n".join(lines)

    def _flatten(self, raw_messages: List[dict]) -> List[dict]:
        """
        Flatten Redis mailbox entries into clean envelopes.

        Redis stores: {"message": <envelope>, "timestamp": <float>}
        We return the envelope with timestamp promoted into it.
        """
        result = []
        for entry in raw_messages:
            envelope = entry.get("message", {})
            if isinstance(envelope, dict):
                # Promote Redis-level timestamp into envelope
                if "timestamp" not in envelope:
                    envelope["timestamp"] = entry.get("timestamp", 0)
                result.append(envelope)
            else:
                # Non-dict message — wrap it
                result.append({
                    "sender": "unknown",
                    "message": envelope,
                    "timestamp": entry.get("timestamp", 0),
                })
        return result
