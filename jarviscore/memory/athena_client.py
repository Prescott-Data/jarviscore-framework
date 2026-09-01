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
    ATHENA_TENANT_ID=my-app            (default: "default")
    ATHENA_API_KEY=...                 (optional X-API-Key authentication)
    ATHENA_JWT_TOKEN=...               (optional X-JWT-Token authentication)

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

import base64
import logging
import os
from datetime import datetime, timezone
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
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._tenant_id = tenant_id
        self._timeout = timeout
        self._api_key = api_key
        self._jwt_token = jwt_token
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
        timeout = float(os.getenv("ATHENA_HTTP_TIMEOUT", "10.0"))
        return cls(
            base_url=url,
            tenant_id=tenant,
            timeout=timeout,
            api_key=os.getenv("ATHENA_API_KEY") or None,
            jwt_token=os.getenv("ATHENA_JWT_TOKEN") or None,
        )

    async def _http(self):
        """Lazy-init httpx.AsyncClient (imported only when actually used)."""
        is_closed = getattr(self._client, "is_closed", False)
        if self._client is None or is_closed is True:
            import httpx  # already in jarviscore core deps

            headers = {"Content-Type": "application/json"}
            if self._api_key:
                headers["X-API-Key"] = self._api_key
            if self._jwt_token:
                headers["X-JWT-Token"] = self._jwt_token
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client. Call on application shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Session Management ────────────────────────────────────────────────────

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return one Athena session, or ``None`` when it cannot be read."""
        try:
            http = await self._http()
            resp = await http.get(f"/api/v1/sessions/{session_id}")
            resp.raise_for_status()
            data = resp.json()
            return data.get("session") or data
        except Exception as exc:
            logger.debug(f"[Athena] get_session failed for '{session_id}': {exc}")
            return None

    async def delete_session(self, session_id: str) -> bool:
        """Delete one Athena session."""
        try:
            http = await self._http()
            resp = await http.delete(f"/api/v1/sessions/{session_id}")
            resp.raise_for_status()
            return bool(resp.json().get("success", False))
        except Exception as exc:
            logger.warning(f"[Athena] delete_session failed for '{session_id}': {exc}")
            return False

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

    async def store_interaction(
        self,
        session_id: str,
        user_message: str,
        agent_response: str,
        metadata: Optional[Dict[str, str]] = None,
        timestamp: Optional[datetime | str] = None,
    ) -> bool:
        """Store one user-agent exchange through Athena's interaction API."""
        try:
            http = await self._http()
            payload: Dict[str, Any] = {
                "session_id": session_id,
                "user_message": user_message,
                "agent_response": agent_response,
                "metadata": {
                    "tenant_id": self._tenant_id,
                    "origin_service": "jarviscore",
                    **(metadata or {}),
                },
            }
            serialized_timestamp = _rfc3339(timestamp)
            if serialized_timestamp:
                payload["timestamp"] = serialized_timestamp
            resp = await http.post(
                f"/api/v1/sessions/{session_id}/interactions", json=payload
            )
            resp.raise_for_status()
            return bool(resp.json().get("success", False))
        except Exception as exc:
            logger.warning(f"[Athena] store_interaction failed: {exc}")
            return False

    async def store_event(
        self,
        session_id: str,
        role: str,
        event_type: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None,
        *,
        timestamp: Optional[datetime | str] = None,
        payload: Optional[bytes] = None,
        mime_type: Optional[str] = None,
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
            timestamp:   Optional occurrence time as datetime or RFC3339 string
            payload:     Optional exact binary payload, base64-encoded for REST
            mime_type:   Required MIME type when payload is provided

        Returns:
            True if stored successfully, False on error.
        """
        result = await self._store_event(
            session_id,
            role,
            event_type,
            content,
            metadata,
            timestamp=timestamp,
            payload=payload,
            mime_type=mime_type,
        )
        return result is not None

    async def store_event_with_id(
        self,
        session_id: str,
        role: str,
        event_type: str,
        content: str,
        metadata: Optional[Dict[str, str]] = None,
        *,
        timestamp: Optional[datetime | str] = None,
        payload: Optional[bytes] = None,
        mime_type: Optional[str] = None,
    ) -> Optional[str]:
        """Store an event and return its durable Athena event ID."""
        result = await self._store_event(
            session_id,
            role,
            event_type,
            content,
            metadata,
            timestamp=timestamp,
            payload=payload,
            mime_type=mime_type,
        )
        if result is None:
            return None
        return str(result.get("eventId") or result.get("event_id") or "") or None

    async def _store_event(
        self,
        session_id: str,
        role: str,
        event_type: str,
        content: str,
        metadata: Optional[Dict[str, str]],
        *,
        timestamp: Optional[datetime | str],
        payload: Optional[bytes],
        mime_type: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        if payload is not None and not mime_type:
            raise ValueError("mime_type is required when payload is provided")
        try:
            http = await self._http()
            request: Dict[str, Any] = {
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
            serialized_timestamp = _rfc3339(timestamp)
            if serialized_timestamp:
                request["timestamp"] = serialized_timestamp
            if payload is not None:
                request["payload"] = base64.b64encode(payload).decode("ascii")
                request["mime_type"] = mime_type
            resp = await http.post(
                f"/api/v1/sessions/{session_id}/events", json=request
            )
            resp.raise_for_status()
            data = resp.json()
            return data if data.get("success", True) else None
        except Exception as exc:
            logger.warning(f"[Athena] store_event failed: {exc}")
            return None

    # ── Memory Reads ──────────────────────────────────────────────────────────

    async def get_context(
        self,
        session_id: str,
        limit: int = 20,
        *,
        query: str = "",
        include_segments: bool = False,
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
                segments: List[dict]    — Athena memory segments
                user_persona: dict | None — inferred user persona
                ltpm: dict | None       — long-term persistent-memory status
                heat_score: float       — session heat (0.0–1.0)
        """
        try:
            http = await self._http()
            params: Dict[str, Any] = {"limit": limit}
            if query:
                params["query"] = query
            if include_segments:
                params["includeSegments"] = True
            resp = await http.get(f"/api/v1/sessions/{session_id}/context", params=params)
            resp.raise_for_status()
            data = resp.json()
            return {
                "stm_events": data.get(
                    "stmEvents", data.get("stm_events", data.get("events", []))
                ),
                "mtm_chains": data.get(
                    "relevantPages",
                    data.get(
                        "relevant_pages",
                        data.get("mtmChains", data.get("chains", [])),
                    ),
                ),
                "segments": data.get("segments", []),
                "user_persona": data.get(
                    "userPersona", data.get("user_persona")
                ),
                "ltpm": data.get("ltpm"),
                "heat_score": data.get(
                    "heatScore", data.get("heat_score", 0.0)
                ),
            }
        except Exception as exc:
            logger.debug(f"[Athena] get_context failed: {exc}")
            return {
                "stm_events": [],
                "mtm_chains": [],
                "segments": [],
                "user_persona": None,
                "ltpm": None,
                "heat_score": 0.0,
            }

    async def search_memory(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
        similarity_threshold: float = 0.7,
        metadata_filter: Optional[Dict[str, str]] = None,
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
                "filter": metadata_filter or {},
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

    async def analyze_topics(self, session_id: str) -> List[Dict[str, Any]]:
        """Return Athena's topic analysis for a session."""
        try:
            http = await self._http()
            resp = await http.get(f"/api/v1/sessions/{session_id}/analysis/topics")
            resp.raise_for_status()
            return resp.json().get("topics", [])
        except Exception as exc:
            logger.debug(f"[Athena] analyze_topics failed: {exc}")
            return []

    async def get_segments(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Return Athena memory segments for a session."""
        try:
            http = await self._http()
            resp = await http.get(
                f"/api/v1/sessions/{session_id}/segments", params={"limit": limit}
            )
            resp.raise_for_status()
            return resp.json().get("segments", [])
        except Exception as exc:
            logger.debug(f"[Athena] get_segments failed: {exc}")
            return []

    async def trigger_graph_analytics(self) -> bool:
        """Trigger Athena's administrative graph-analytics job."""
        try:
            http = await self._http()
            resp = await http.post("/api/v1/admin/analytics/trigger", json={})
            resp.raise_for_status()
            return bool(resp.json().get("success", False))
        except Exception as exc:
            logger.warning(f"[Athena] trigger_graph_analytics failed: {exc}")
            return False

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
            data = resp.json()
            return data.get("heatMetrics", data.get("heat_metrics", data))
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


def _rfc3339(value: Optional[datetime | str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
