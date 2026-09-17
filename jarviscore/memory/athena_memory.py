"""
jarviscore.memory.athena_memory
=================================
AthenaMemory — plugs into UnifiedMemory as an optional fourth tier.

When an AthenaClient is wired in, every log_turn() write goes to BOTH
the Redis EpisodicLedger AND Athena STM. The kernel's rehydrate_bundle()
                            "segments": [...],     # memory segments when requested/available
                            "user_persona": {...}, # inferred persona when available
                            "ltpm": {...},         # long-term persistent-memory status
call also pulls Athena MTM chains (summarised cognitive chains) as
additional context, giving agents cross-session, semantically searchable
memory instead of just the raw Redis stream.

Integration with UnifiedMemory:
    mem = UnifiedMemory(
        workflow_id="wf-1",
        step_id="step2",
        agent_id="my-agent",
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
    TYPE_ACTION,
    TYPE_OBSERVATION,
    TYPE_THOUGHT,
)
from .delivery import CircuitBreaker, Outbox

logger = logging.getLogger(__name__)


def _outbox_from_settings() -> Outbox:
    """Build the write outbox from the Athena settings block.

    Retries default off. Athena has no client-supplied deduplication key today,
    so replaying a write that actually landed would store it twice — and a
    memory tier with invented corroboration is worse than one with a counted
    gap. Turning ``athena_deduplicates_writes`` on is a claim about the
    deployment, which only an operator can make.
    """
    from jarviscore.config import settings

    return Outbox(
        max_queue=settings.athena_outbox_max_events,
        max_attempts=settings.athena_write_max_attempts,
        deduplicates=settings.athena_deduplicates_writes,
        breaker=CircuitBreaker(
            threshold=settings.athena_breaker_threshold,
            cooldown=settings.athena_breaker_cooldown_seconds,
        ),
    )


class AthenaMemory:
    """
    Bridges a JarvisCore agent session to Athena MemOS.

    Responsibilities:
      - Maintain a stable Athena session_id per agent (cached in Redis)
      - Write every kernel turn as a typed STM event
      - Provide enriched context (STM + MTM) for kernel injection
      - Emit domain-level observations (task assigned, meeting noted, HITL resolved)

    Lifecycle:
        am = await AthenaMemory.create("my-agent", athena_client, redis_store)
        await am.record_thought("Analysing SEO gaps on example.com/docs")
        await am.record_action("Assigned task: SEO audit", {"task_id": "xyz"})
        ctx = await am.get_memory_context()
        # ctx["stm_events"] and ctx["mtm_chains"] injected into agent run
    """

    def __init__(
        self,
        agent_id: str,
        session_id: str,
        client: AthenaClient,
        outbox: Optional[Outbox] = None,
    ) -> None:
        self._agent_id = agent_id
        self._session_id = session_id
        self._client = client
        # Writes are this tier's problem, not the caller's: a turn should not
        # wait on Athena, and a write it loses should be countable (#128).
        self._outbox = outbox if outbox is not None else Outbox()

    @classmethod
    async def create(
        cls,
        agent_id: str,
        client: AthenaClient,
        redis_store=None,
        metadata: Optional[Dict[str, str]] = None,
        *,
        user_id: Optional[str] = None,
        outbox: Optional[Outbox] = None,
    ) -> "AthenaMemory":
        """
        Factory: creates or reuses an Athena session for this agent.

        Args:
            agent_id:    Unique stable agent name (e.g. "researcher")
            client:      Initialised AthenaClient
            redis_store: Optional — caches session_id so it survives restarts
            metadata:    Tags forwarded to Athena session on creation
            user_id:     Athena user scope. Defaults to ``agent_id``.

        Returns:
            AthenaMemory instance, ready to write/read.
        """
        merged_meta = {
            "agent_id": agent_id,
            "origin_service": "jarviscore",
            **(metadata or {}),
        }
        session_id = await client.get_or_create_session(
            agent_id,
            redis_store=redis_store,
            metadata=merged_meta,
            user_id=user_id,
        )
        if not session_id:
            raise RuntimeError(
                f"[Athena] Could not create or retrieve session for agent '{agent_id}'. "
                f"Is Athena running at {client._base_url}?"
            )
        logger.info(f"[Athena] AthenaMemory ready: agent={agent_id} session={session_id}")
        return cls(
            agent_id=agent_id,
            session_id=session_id,
            client=client,
            outbox=outbox if outbox is not None else _outbox_from_settings(),
        )

    # ── Write helpers ─────────────────────────────────────────────────────────
    #
    # These return once the event is queued. They use the client's raising write
    # path, because the outbox has to see a failure in order to count or retry it.

    def _submit(
        self, event_type: str, content: str, metadata: Optional[Dict[str, str]]
    ) -> None:
        self._outbox.submit(
            self._client.write_event,
            session_id=self._session_id,
            role=ROLE_AGENT,
            event_type=event_type,
            content=content,
            metadata={"agent_id": self._agent_id, **(metadata or {})},
        )

    async def record_thought(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        """Record an internal agent reasoning step (maps to Athena TYPE_THOUGHT)."""
        self._submit(TYPE_THOUGHT, content, metadata)

    async def record_action(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a concrete agent action (task assignment, tool call)."""
        self._submit(TYPE_ACTION, content, metadata)

    async def record_observation(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        """Record the outcome of an action (task completed, meeting noted, HITL resolved)."""
        self._submit(TYPE_OBSERVATION, content, metadata)

    # ── Delivery ──────────────────────────────────────────────────────────────

    @property
    def delivery_stats(self) -> Dict[str, Any]:
        """Shipped, retried, dropped, queue depth, breaker state, last success.

        A tier that is configured and silently storing nothing reads exactly
        like a healthy one from the outside. These are how you tell.
        """
        return self._outbox.stats.to_dict()

    async def flush(self, timeout: float = 5.0) -> bool:
        """Wait for queued writes to reach Athena. False if any are still queued."""
        return await self._outbox.flush(timeout=timeout)

    async def close(self, timeout: float = 5.0) -> bool:
        """Ship what is queued and stop the shipper."""
        return await self._outbox.close(timeout=timeout)

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
            content += f" — {output_summary}"
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
            content += f" — {summary}"
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
            content += f" (note: {note})"
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
