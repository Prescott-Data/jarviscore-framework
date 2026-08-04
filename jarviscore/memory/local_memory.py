"""
LocalMemory: the zero-infrastructure cross-session memory tier.

Same surface as AthenaMemory, backed by a single SQLite file. No Go
stack, no Docker, no Redis. Set ATHENA_URL and the kernel upgrades to
Athena MemOS with no code changes; until then, agents still remember
across restarts.

Persistence is deliberate and loud: the location is announced once at
init (default ./.jarviscore/memory.db, override with
JARVISCORE_MEMORY_PATH, disable with JARVISCORE_MEMORY_PATH=off).

Search is keyword-overlap ranking, not embeddings. It is honest about
that: results carry match_type="keyword" so callers and readers never
mistake it for semantic recall.
"""

import asyncio
import contextlib
import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = os.path.join(".jarviscore", "memory.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    agent_id   TEXT NOT NULL,
    created_at REAL NOT NULL,
    metadata   TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    type       TEXT NOT NULL,
    content    TEXT NOT NULL,
    metadata   TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id);
"""


class LocalMemory:
    """Cross-session agent memory in one SQLite file. AthenaMemory-compatible."""

    def __init__(self, agent_id: str, session_id: str, db_path: str) -> None:
        self._agent_id = agent_id
        self._session_id = session_id
        self._db_path = db_path

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        agent_id: str,
        db_path: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> "LocalMemory":
        """Create or reuse the durable session for this agent."""
        path = db_path or os.environ.get("JARVISCORE_MEMORY_PATH") or DEFAULT_PATH
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        def _init() -> str:
            with cls._connect(path) as conn:
                conn.executescript(_SCHEMA)
                row = conn.execute(
                    "SELECT session_id FROM sessions WHERE agent_id = ?", (agent_id,)
                ).fetchone()
                if row:
                    return row[0]
                session_id = f"local-{uuid.uuid4().hex[:12]}"
                conn.execute(
                    "INSERT INTO sessions (session_id, agent_id, created_at, metadata) "
                    "VALUES (?, ?, ?, ?)",
                    (session_id, agent_id, time.time(), json.dumps(metadata or {})),
                )
                return session_id

        session_id = await asyncio.to_thread(_init)
        logger.info(
            "[LocalMemory] ready: agent=%s session=%s path=%s "
            "(set ATHENA_URL for cross-session semantic memory)",
            agent_id, session_id, path,
        )
        return cls(agent_id=agent_id, session_id=session_id, db_path=path)

    @staticmethod
    @contextlib.contextmanager
    def _connect(path: str) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on error, always close."""
        conn = sqlite3.connect(path, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    # ── Write helpers (AthenaMemory surface) ─────────────────────────────────

    async def record_thought(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        await self._store("agent", "thought", content, metadata)

    async def record_action(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        await self._store("agent", "action", content, metadata)

    async def record_observation(
        self, content: str, metadata: Optional[Dict[str, str]] = None
    ) -> None:
        await self._store("agent", "observation", content, metadata)

    async def _store(
        self, role: str, type_: str, content: str, metadata: Optional[Dict[str, str]]
    ) -> None:
        meta = json.dumps({"agent_id": self._agent_id, **(metadata or {})})

        def _write() -> None:
            with self._connect(self._db_path) as conn:
                conn.execute(
                    "INSERT INTO events (session_id, role, type, content, metadata, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (self._session_id, role, type_, content, meta, time.time()),
                )

        await asyncio.to_thread(_write)

    # ── Read helpers (AthenaMemory surface) ──────────────────────────────────

    async def get_memory_context(self, limit: int = 20) -> Dict[str, Any]:
        """Recent events, shaped like Athena's context payload.

        mtm_chains is always empty: consolidation is Athena's job, and
        pretending otherwise here would be a lie.
        """

        def _read() -> List[Dict[str, Any]]:
            with self._connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT role, type, content, metadata, created_at FROM events "
                    "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (self._session_id, limit),
                ).fetchall()
            return [
                {
                    "role": r[0], "type": r[1], "content": r[2],
                    "metadata": json.loads(r[3]), "created_at": r[4],
                }
                for r in reversed(rows)
            ]

        events = await asyncio.to_thread(_read)
        return {"stm_events": events, "mtm_chains": [], "heat_score": 0.0}

    async def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Keyword-overlap search. Labeled as such: this is not semantic recall."""
        terms = {t for t in query.lower().split() if len(t) > 2}
        if not terms:
            return []

        def _read() -> List[Dict[str, Any]]:
            with self._connect(self._db_path) as conn:
                rows = conn.execute(
                    "SELECT content, type, created_at FROM events "
                    "WHERE session_id = ? ORDER BY id DESC LIMIT 2000",
                    (self._session_id,),
                ).fetchall()
            scored = []
            for content, type_, created_at in rows:
                words = set(content.lower().split())
                overlap = len(terms & words)
                if overlap:
                    scored.append(
                        {
                            "content": content,
                            "type": type_,
                            "created_at": created_at,
                            "similarity_score": overlap / len(terms),
                            "match_type": "keyword",
                        }
                    )
            scored.sort(key=lambda x: x["similarity_score"], reverse=True)
            return scored[:limit]

        return await asyncio.to_thread(_read)

    async def get_heat(self) -> Dict[str, Any]:
        return {"heat_score": 0.0, "backend": "local"}

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def agent_id(self) -> str:
        return self._agent_id
