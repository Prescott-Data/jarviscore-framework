"""
jarviscore.memory.athena_memory
=================================
AthenaMemory — plugs into UnifiedMemory as an optional fourth tier.

When an AthenaClient is wired in, every log_turn() write goes to BOTH
the Redis EpisodicLedger AND Athena STM. The kernel's rehydrate_bundle()
call also pulls Athena MTM chains (summarised cognitive chains) as
additional context, giving agents cross-session, semantically searchable
memory instead of just the raw Redis stream.

Integration with UnifiedMemory:
    mem = UnifiedMemory(
        workflow_id="wf-1",
        step_id="step2",
        agent_id="compass",
        redis_store=redis_store,
        blob_storage=blob_storage,
        athena_client=AthenaClient.from_env(),   # ← new optional kwarg
    )

When ATHENA_URL is not set, athena_client is None and this module
is never imported — zero performance cost for users without Athena.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .athena_client import (
    AthenaClient,
    ROLE_AGENT,
    ROLE_SYSTEM,
    TYPE_ACTION,
    TYPE_OBSERVATION,
    TYPE_THOUGHT,
)

logger = logging.getLogger(__name__)


class AthenaMemory:
    """
    Bridges a JarvisCore agent session to Athena MemOS.

    Responsibilities:
      - Maintain a stable Athena session_id per agent (cached in Redis)
      - Write every kernel turn as a typed STM event
      - Provide enriched context (STM + MTM) for kernel injection
      - Emit domain-level observations (task assigned, meeting noted, HITL resolved)

    Lifecycle:
        am = await AthenaMemory.create("compass", athena_client, redis_store)
        await am.record_thought("Analysing SEO gaps on prescottdata.io")
        await am.record_action("Assigned task: SEO audit", {"task_id": "xyz"})
        ctx = await am.get_memory_context()
        # ctx["stm_events"] and ctx["mtm_chains"] injected into agent run
    """

    def __init__(
        self,
        agent_id: str,
        session_id: str,
        client: AthenaClient,
    ) -> None:
        self._agent_id = agent_id
        self._session_id = session_id
        self._client = client

    @classmethod
    async def create(
        cls,
        agent_id: str,
        client: AthenaClient,
        redis_store=None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> "AthenaMemory":
        """
        Factory: creates or reuses an Athena session for this agent.

        Args:
            agent_id:    Unique stable agent name (e.g. "compass")
            client:      Initialised AthenaClient
            redis_store: Optional — caches session_id so it survives restarts
            metadata:    Tags forwarded to Athena session on creation

        Returns:
            AthenaMemory instance, ready to write/read.
        """
        merged_meta = {
            "agent_id": agent_id,
            "origin_service": "jarviscore",
            **(metadata or {}),
        }
        session_id = await client.get_or_create_session(
            agent_id, redis_store=redis_store, metadata=merged_meta
        )
        if not session_id:
            raise RuntimeError(
                f"[Athena] Could not create or retrieve session for agent '{agent_id}'. "
                f"Is Athena running at {client._base_url}?"
            )
        logger.info(f"[Athena] AthenaMemory ready: agent={agent_id} session={session_id}")
        return cls(agent_id=agent_id, session_id=session_id, client=client)

    # ── Write helpers ─────────────────────────────────────────────────────────

    async def record_thought(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        """Record an internal agent reasoning step (maps to Athena TYPE_THOUGHT)."""
        await self._client.store_event(
            self._session_id, ROLE_AGENT, TYPE_THOUGHT, content,
            metadata={"agent_id": self._agent_id, **(metadata or {})},
        )

    async def record_action(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a concrete agent action (task assignment, tool call)."""
        await self._client.store_event(
            self._session_id, ROLE_AGENT, TYPE_ACTION, content,
            metadata={"agent_id": self._agent_id, **(metadata or {})},
        )

    async def record_observation(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        """Record the outcome of an action (task completed, meeting noted, HITL resolved)."""
        await self._client.store_event(
            self._session_id, ROLE_AGENT, TYPE_OBSERVATION, content,
            metadata={"agent_id": self._agent_id, **(metadata or {})},
        )

    # ── Domain event helpers (called by the kernel at lifecycle points) ────────

    async def on_task_assigned(self, task_id: str, title: str, assignee: str) -> None:
        """Emit an action event when a task is assigned to this agent."""
        await self.record_action(
            f"Task assigned: {title}",
            metadata={"task_id": task_id, "assignee": assignee, "event": "task_assigned"},
        )

    async def on_task_completed(
        self, task_id: str, title: str, output_summary: str = ""
    ) -> None:
        """Emit an observation event when a task is completed."""
        content = f"Task completed: {title}"
        if output_summary:
            content += f" — {output_summary[:300]}"
        await self.record_observation(
            content,
            metadata={"task_id": task_id, "event": "task_completed"},
        )

    async def on_meeting_noted(
        self, meeting_id: str, title: str, summary: str = ""
    ) -> None:
        """Emit an observation event when a meeting note is created."""
        content = f"Meeting recorded: {title}"
        if summary:
            content += f" — {summary[:300]}"
        await self.record_observation(
            content,
            metadata={"meeting_id": meeting_id, "event": "meeting_noted"},
        )

    async def on_hitl_resolved(
        self, request_id: str, decision: str, note: str = ""
    ) -> None:
        """Emit an observation event when a HITL request is resolved."""
        content = f"HITL resolved: {decision.upper()} — request {request_id}"
        if note:
            content += f" (note: {note[:200]})"
        await self.record_observation(
            content,
            metadata={"request_id": request_id, "decision": decision, "event": "hitl_resolved"},
        )

    async def on_task_deleted(self, task_id: str, title: str) -> None:
        """Emit an observation when a task is deleted (retraction signal)."""
        await self.record_observation(
            f"Task deleted: {title}",
            metadata={"task_id": task_id, "event": "task_deleted"},
        )

    # ── Read helpers ──────────────────────────────────────────────────────────

    async def get_memory_context(self, limit: int = 20) -> Dict[str, Any]:
        """
        Fetch the full memory context for this agent from Athena.

        The kernel merges this into the agent's run context so agents
        have awareness of their own recent actions and prior summaries.

        Returns:
            {
              "stm_events": [...],   # recent turns (STM)
              "mtm_chains": [...],   # summarised cognitive chains (MTM)
              "heat_score": float,   # overall memory heat
            }
        """
        return await self._client.get_context(self._session_id, limit=limit)

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Semantic search across this agent's memory.

        Useful for agents to ask "what do I know about X before I start this task?"

        Returns:
            List of SearchResult dicts with content and similarity_score.
        """
        return await self._client.search_memory(self._session_id, query, limit=limit)

    async def get_heat(self) -> Dict[str, Any]:
        """Return Ebbinghaus heat metrics for this agent's session."""
        return await self._client.get_heat_metrics(self._session_id)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def agent_id(self) -> str:
        return self._agent_id
