"""
jarviscore.memory.athena_client
================================
Async HTTP client for the Athena MemOS REST API.

Athena is a Go memory operating system (STM → Redis + MongoDB,
MTM → MongoDB + Milvus, LTM → ArangoDB) that gives agents persistent
memory and structured knowledge across sessions and restarts.

This client is the ONLY point in JarvisCore that calls Athena.
It adds zero dependencies — httpx is already in jarviscore core.

Configuration:
    ATHENA_URL=http://localhost:8080   (required to enable Athena)
    ATHENA_TENANT_ID=my-app          (default: "default")

Graceful degradation:
    If ATHENA_URL is not set, all methods return empty/None and log a
    debug message. The rest of the memory stack continues to function
    on Redis + Blob.

Athena API reference (memory.proto → HTTP gateway):
    POST   /api/v1/sessions
    GET    /api/v1/sessions/{id}
    DELETE /api/v1/sessions/{id}
    POST   /api/v1/sessions/{id}/interactions
    POST   /api/v1/sessions/{id}/events
    GET    /api/v1/sessions/{id}/context
    POST   /api/v1/sessions/{id}/context/search
    GET    /api/v1/sessions/{id}/analysis/topics
    GET    /api/v1/sessions/{id}/analysis/heat
    GET    /api/v1/sessions/{id}/segments
    GET    /api/v1/health
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Event types mirroring Athena's STMEventType
ROLE_AGENT  = "agent"
ROLE_USER   = "user"
ROLE_SYSTEM = "system"

TYPE_MESSAGE     = "message"
TYPE_THOUGHT     = "thought"
TYPE_ACTION      = "action"
TYPE_OBSERVATION = "observation"


class AthenaClient:
    """
    Async HTTP client for the Athena MemOS REST API.

    Instantiate once per process (the MemoryManager owns it).
    All methods are coroutines and safe to call concurrently.

    Example:
        client = AthenaClient("http://localhost:8080", tenant_id="my-app")
        session_id = await client.create_session("researcher-agent", {"team": "data"})
        await client.store_event(session_id, "agent", "action",
                                 "Assigned task: market analysis", {"task_id": "abc"})
        ctx = await client.get_context(session_id)
    """

    def __init__(
        self,
        base_url: str,
        tenant_id: str = "default",
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._tenant_id = tenant_id
        self._timeout = timeout
        self._client = None  # lazy-init httpx.AsyncClient

    @classmethod
    def from_env(cls) -> Optional["AthenaClient"]:
        """
        Create an AthenaClient from environment variables.

        Returns None if ATHENA_URL is not set, so callers can treat
        Athena as optional without additional checks.

        Usage:
            athena = AthenaClient.from_env()
            if athena:
                await athena.store_event(...)
        """
        url = os.getenv("ATHENA_URL", "").strip()
        if not url:
            logger.debug(
                "ATHENA_URL not set — Athena memory disabled. "
                "Set ATHENA_URL=http://localhost:8080 to enable."
            )
            return None
        tenant = os.getenv("ATHENA_TENANT_ID", "default")
        return cls(base_url=url, tenant_id=tenant)

    async def _http(self) :
        """Lazy-init httpx.AsyncClient (imported only when actually used)."""
        if self._client is None:
            import httpx  # already in jarviscore core deps
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client. Call on application shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Session Management ────────────────────────────────────────────────────

    async def create_session(
        self,
        agent_id: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Create an Athena memory session for an agent.

        Each agent should have one long-lived session so that Athena's
        heat scoring and MTM promotion work correctly across restarts.

        Args:
            agent_id:  Unique agent identifier (e.g. "researcher", "analyst")
            metadata:  Optional k/v tags (e.g. {"team": "data"})

        Returns:
            Athena session_id string, or None on failure.
        """
        try:
            http = await self._http()
            payload: Dict[str, Any] = {
                "tenant_id": self._tenant_id,
                "user_id": agent_id,
                "metadata": {
                    "agent_id": agent_id,
                    "origin_service": "jarviscore",
                    **(metadata or {}),
                },
            }
            resp = await http.post("/api/v1/sessions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            session_id = data.get("session_id") or data.get("sessionId")
            logger.info(f"[Athena] Session created for agent '{agent_id}': {session_id}")
            return session_id
        except Exception as exc:
            logger.warning(f"[Athena] create_session failed for '{agent_id}': {exc}")
            return None

    async def get_or_create_session(
        self,
        agent_id: str,
        redis_store=None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Return the existing Athena session for this agent, or create one.

        If redis_store is provided, the session_id is cached in Redis at
        key `athena_session:{agent_id}` so it survives process restarts.
        This is critical for Athena heat scoring continuity.

        Args:
            agent_id:    Unique agent identifier
            redis_store: Optional RedisContextStore for session caching
            metadata:    Tags forwarded to create_session if creating new

        Returns:
            session_id string, or None if creation fails.
        """
        redis_key = f"athena_session:{agent_id}"

        # 1. Try Redis cache
        if redis_store:
            try:
                cached = redis_store._redis.get(redis_key)
                if cached:
                    logger.debug(f"[Athena] Reusing session for '{agent_id}': {cached}")
                    return cached
            except Exception:
                pass

        # 2. Create new session
        session_id = await self.create_session(agent_id, metadata)
        if not session_id:
            return None

        # 3. Cache in Redis (TTL = 30 days so sessions are very long-lived)
        if redis_store:
            try:
                redis_store._redis.set(redis_key, session_id, ex=30 * 86400)
            except Exception:
                pass

        return session_id

    # ── Memory Writes ─────────────────────────────────────────────────────────

    async def store_event(
        self,
        session_id: str,
        role: str,
        event_type: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> bool:
        """
        Store a single typed event in Athena STM.

        This is the main write path. Use the TYPE_* constants for event_type.

        Args:
            session_id:  Athena session_id (from get_or_create_session)
            role:        Who generated this — ROLE_AGENT, ROLE_USER, ROLE_SYSTEM
            event_type:  TYPE_MESSAGE / TYPE_THOUGHT / TYPE_ACTION / TYPE_OBSERVATION
            content:     The event text content
            metadata:    Optional k/v enrichment (task_id, workflow_id, etc.)

        Returns:
            True if stored successfully, False on error.
        """
        try:
            http = await self._http()
            payload: Dict[str, Any] = {
                "session_id": session_id,
                "role": role,
                "type": event_type,
                "content": content,
                "metadata": {
                    "tenant_id": self._tenant_id,
                    "origin_service": "jarviscore",
                    **(metadata or {}),
                },
            }
            resp = await http.post(
                f"/api/v1/sessions/{session_id}/events", json=payload
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning(f"[Athena] store_event failed: {exc}")
            return False

    # ── Memory Reads ──────────────────────────────────────────────────────────

    async def get_context(
        self,
        session_id: str,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Retrieve recent STM events + relevant MTM chains from Athena.

        This is what the kernel injects into agent context before each run.
        Returns both short-term (recent turns) and mid-term (summarised chains).

        Args:
            session_id: Athena session_id
            limit:      Maximum number of STM events to return

        Returns:
            Dict with keys:
                stm_events: List[dict]  — recent turn events
                mtm_chains: List[dict]  — summarised cognitive chains
                heat_score: float       — session heat (0.0–1.0)
        """
        try:
            http = await self._http()
            resp = await http.get(
                f"/api/v1/sessions/{session_id}/context",
                params={"limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "stm_events": data.get("events", data.get("stmEvents", [])),
                "mtm_chains": data.get("chains", data.get("mtmChains", [])),
                "heat_score": data.get("heatScore", 0.0),
            }
        except Exception as exc:
            logger.debug(f"[Athena] get_context failed: {exc}")
            return {"stm_events": [], "mtm_chains": [], "heat_score": 0.0}

    async def search_memory(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
        similarity_threshold: float = 0.7,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search across the agent's memory (MTM vector store).

        Useful for agents to recall prior relevant work before starting a task.

        Args:
            session_id:           Athena session_id
            query:                Natural language query
            limit:                Max results to return
            similarity_threshold: Min cosine similarity (0.0–1.0)

        Returns:
            List of SearchResult dicts with content, similarity_score, source_type.
        """
        try:
            http = await self._http()
            payload = {
                "query": query,
                "limit": limit,
                "similarity_threshold": similarity_threshold,
            }
            resp = await http.post(
                f"/api/v1/sessions/{session_id}/context/search", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
        except Exception as exc:
            logger.debug(f"[Athena] search_memory failed: {exc}")
            return []

    async def get_heat_metrics(self, session_id: str) -> Dict[str, Any]:
        """
        Get Ebbinghaus heat metrics for a session.

        Useful for CLI diagnostics and understanding which agents have the
        warmest (most active) memory.

        Returns:
            Dict with overall_heat, breakdown, total_interactions, last_activity.
        """
        try:
            http = await self._http()
            resp = await http.get(f"/api/v1/sessions/{session_id}/analysis/heat")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug(f"[Athena] get_heat_metrics failed: {exc}")
            return {}

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Athena's health and dependency status.

        Returns dict with status + per-dependency health (Redis, MongoDB, Milvus, ArangoDB).
        Tries the REST health endpoint first (/health), then falls back to
        the gRPC gateway endpoint (/api/v1/health).
        """
        try:
            http = await self._http()
            # REST health endpoint (primary — always implemented)
            resp = await http.get("/health")
            resp.raise_for_status()
            return resp.json()
        except Exception:
            pass
        try:
            http = await self._http()
            # gRPC gateway health endpoint (fallback)
            resp = await http.get("/api/v1/health")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"status": "unreachable", "error": str(exc)}
