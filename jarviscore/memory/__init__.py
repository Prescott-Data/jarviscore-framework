"""
Memory module for JarvisCore v1.0.2.

Three-tier baseline memory (Redis + Blob, zero extra deps):
  WorkingScratchpad  — per-step JSONL notes in BlobStorage
  EpisodicLedger     — chronological Redis Stream of all turn events
  LongTermMemory     — Redis-cached + Blob-durable compressed summaries
  UnifiedMemory      — single entry point composing all three tiers

Full three-tier memory with Athena MemOS (set ATHENA_URL to activate):
  AthenaClient       — async HTTP client for the Athena REST API
  AthenaMemory       — per-agent bridge: session management, typed events,
                       STM + MTM context retrieval, semantic search

Integration:
    # Baseline (no extra config)
    mem = UnifiedMemory(workflow_id, step_id, agent_id,
                        redis_store=redis_store, blob_storage=blob)

    # Full Athena memory (requires ATHENA_URL)
    athena = get_athena_client()
    am = await AthenaMemory.create("compass", athena, redis_store)
    await am.on_task_assigned("t1", "SEO audit", "compass")
    ctx = await am.get_memory_context()
"""

from .scratchpad import WorkingScratchpad
from .episodic import EpisodicLedger
from .ltm import LongTermMemory
from .unified import UnifiedMemory
from .athena_client import AthenaClient
from .athena_memory import AthenaMemory

__all__ = [
    # Baseline memory (Redis + Blob)
    "WorkingScratchpad",
    "EpisodicLedger",
    "LongTermMemory",
    "UnifiedMemory",
    # Athena MemOS
    "AthenaClient",
    "AthenaMemory",
    "get_athena_client",
]


def get_athena_client(settings=None) -> "AthenaClient | None":
    """
    Factory: create an AthenaClient from settings or environment.

    Returns None if ATHENA_URL is not set, so callers can treat Athena
    as optional without additional checks — same pattern as get_blob_storage().

    Usage:
        from jarviscore.memory import get_athena_client, AthenaMemory

        athena = get_athena_client()
        if athena:
            am = await AthenaMemory.create("compass", athena, redis_store)
    """
    if settings is None:
        try:
            from jarviscore.config.settings import settings as _s
            settings = _s
        except Exception:
            pass

    url = (getattr(settings, "athena_url", None) or "").strip()
    if not url:
        import os
        url = os.getenv("ATHENA_URL", "").strip()

    if not url:
        return None

    tenant = getattr(settings, "athena_tenant_id", "prescott")
    timeout = getattr(settings, "athena_http_timeout", 10.0)
    return AthenaClient(base_url=url, tenant_id=tenant, timeout=timeout)
