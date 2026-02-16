"""
Natural Language Mailboxes for JarvisCore v1.0.0.

High-level API for agent-to-agent messaging with capability-based
routing. Built on top of RedisContextStore mailbox primitives (Phase 1).

No separate CapabilityRouter — MailboxManager uses Mesh's existing
get_agents_by_capability() and _agent_registry directly.
"""

from .mailbox import MailboxManager

__all__ = ["MailboxManager"]
