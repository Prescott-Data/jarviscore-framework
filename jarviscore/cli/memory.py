"""
jarviscore.cli.memory — 'python -m jarviscore.cli memory' subcommand.

Commands:
    status                      — health check Athena + Redis + Blob tiers
    context --agent <name>      — dump recent STM + MTM for an agent
    search  --agent <name> --query <q>  — semantic search agent memory
    up                          — guide to starting Athena stack locally

Usage:
    python -m jarviscore.cli memory status
    python -m jarviscore.cli memory context --agent compass
    python -m jarviscore.cli memory search --agent compass --query "seo audit"
    python -m jarviscore.cli memory up
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Optional


# ── Helpers ───────────────────────────────────────────────────────────────────

def _banner(msg: str, char: str = "─") -> None:
    width = min(72, max(len(msg) + 4, 40))
    print(f"\n{char * width}")
    print(f"  {msg}")
    print(f"{char * width}")


def _ok(msg: str) -> None:
    print(f"  ✅  {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠️   {msg}")


def _err(msg: str) -> None:
    print(f"  ❌  {msg}")


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_status(_args: argparse.Namespace) -> None:
    """Show health status of all memory tiers."""
    _banner("JarvisCore Memory — Status", "═")

    # 1. Athena
    athena_url = os.getenv("ATHENA_URL", "").strip()
    if athena_url:
        from jarviscore.memory import get_athena_client
        client = get_athena_client()
        if client:
            health = await client.health_check()
            status = health.get("status", "unknown")
            if status in ("ok", "healthy", "pass", "UP"):
                _ok(f"Athena MemOS  {athena_url}  [{status}]")
                deps = health.get("dependencies", {})
                for dep, dep_status in deps.items():
                    if dep_status in ("ok", "healthy", "pass", "UP", "true"):
                        _ok(f"  └─ {dep}: {dep_status}")
                    else:
                        _warn(f"  └─ {dep}: {dep_status}")
            else:
                _err(f"Athena MemOS  {athena_url}  [{status}]")
        await client.close()
    else:
        _warn("Athena MemOS  NOT CONFIGURED — set ATHENA_URL to enable")
        print("         e.g. export ATHENA_URL=http://localhost:8080")

    # 2. Redis
    try:
        import redis as _redis
        r = _redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
        )
        r.ping()
        _ok(f"Redis  {os.getenv('REDIS_HOST','localhost')}:{os.getenv('REDIS_PORT','6379')}  [connected]")
    except ImportError:
        _warn("Redis  not installed — pip install 'jarviscore-framework[redis]'")
    except Exception as exc:
        _err(f"Redis  {exc}")

    # 3. Blob storage
    storage_backend = os.getenv("STORAGE_BACKEND", "local")
    if storage_backend == "azure":
        _ok("Blob  Azure Blob Storage  [configured]") if os.getenv("AZURE_STORAGE_CONNECTION_STRING") else _warn("Blob  Azure — AZURE_STORAGE_CONNECTION_STRING not set")
    else:
        base = os.getenv("STORAGE_BASE_PATH", "./blob_storage")
        _ok(f"Blob  Local filesystem  [{base}]")

    print()


async def cmd_context(args: argparse.Namespace) -> None:
    """Dump recent STM + MTM context for an agent from Athena."""
    agent_id = args.agent
    limit = getattr(args, "limit", 20)

    athena_url = os.getenv("ATHENA_URL", "").strip()
    if not athena_url:
        _err("ATHENA_URL is not set. Run 'jarviscore memory up' for setup instructions.")
        sys.exit(1)

    from jarviscore.memory import get_athena_client, AthenaMemory

    client = get_athena_client()
    if not client:
        _err("Could not create Athena client.")
        sys.exit(1)

    _banner(f"Memory Context — agent: {agent_id}")

    try:
        # Get or create a session (read-only — reuse existing)
        session_id = await client.get_or_create_session(agent_id)
        if not session_id:
            _err(f"Could not retrieve Athena session for agent '{agent_id}'.")
            await client.close()
            sys.exit(1)

        print(f"\n  Session ID: {session_id}")
        ctx = await client.get_context(session_id, limit=limit)

        # STM
        stm = ctx.get("stm_events", [])
        print(f"\n  Short-Term Memory ({len(stm)} events):")
        if stm:
            for ev in stm[-10:]:  # show last 10
                role = ev.get("role", "?")
                etype = ev.get("type", "?")
                content = str(ev.get("content", ""))[:120]
                ts = ev.get("timestamp", ev.get("created_at", ""))[:19] if ev.get("timestamp") or ev.get("created_at") else ""
                print(f"    [{ts}] {role}/{etype}: {content}")
        else:
            print("    (empty)")

        # MTM
        mtm = ctx.get("mtm_chains", [])
        print(f"\n  Mid-Term Memory ({len(mtm)} cognitive chains):")
        if mtm:
            for chain in mtm:
                topic = chain.get("topic", "?")
                summary = str(chain.get("summary", ""))[:150]
                heat = chain.get("heatScore", chain.get("heat_score", ""))
                print(f"    [{heat:.2f} heat] {topic}: {summary}" if isinstance(heat, float) else f"    {topic}: {summary}")
        else:
            print("    (empty — not enough events for MTM formation yet)")

        # Heat
        heat_score = ctx.get("heat_score", 0.0)
        print(f"\n  Overall Heat Score: {heat_score:.3f}")

    finally:
        await client.close()

    print()


async def cmd_search(args: argparse.Namespace) -> None:
    """Semantic search across an agent's memory."""
    agent_id = args.agent
    query    = args.query
    limit    = getattr(args, "limit", 5)

    athena_url = os.getenv("ATHENA_URL", "").strip()
    if not athena_url:
        _err("ATHENA_URL is not set.")
        sys.exit(1)

    from jarviscore.memory import get_athena_client

    client = get_athena_client()
    if not client:
        sys.exit(1)

    _banner(f"Memory Search — agent: {agent_id}  query: '{query}'")

    try:
        session_id = await client.get_or_create_session(agent_id)
        if not session_id:
            _err(f"No Athena session for '{agent_id}'.")
            await client.close()
            sys.exit(1)

        results = await client.search_memory(session_id, query, limit=limit)
        if not results:
            print("  No results found.")
        else:
            for i, r in enumerate(results, 1):
                score   = r.get("similarity_score", r.get("similarityScore", 0.0))
                source  = r.get("source_type", r.get("sourceType", "?"))
                content = str(r.get("content", ""))[:200]
                print(f"\n  [{i}] Score: {score:.3f}  Source: {source}")
                print(f"      {content}")
    finally:
        await client.close()

    print()


def cmd_up(_args: argparse.Namespace) -> None:
    """Print instructions to start Athena locally."""
    _banner("Starting Athena MemOS Locally", "═")
    print("""
  Athena is a Go service. To run it locally:

  1. Clone the repo (you should already have it):
       git clone git@github.com:Prescott-Data/athena.git

  2. Start the full stack (Redis + MongoDB + Milvus + ArangoDB + Athena):
       cd athena
       cp .env.example .env.dev
       # Edit .env.dev — fill in LLM_API_KEY at minimum
       docker compose -f docker-compose.local.yml up -d

  3. Verify it's healthy:
       curl http://localhost:8080/api/v1/health

  4. Point JarvisCore at it:
       export ATHENA_URL=http://localhost:8080

  5. Check status from JarvisCore:
       python -m jarviscore.cli memory status

  Athena ports (default):
    :8080   HTTP / gRPC gateway
    :6379   Redis (STM hot path)
    :27017  MongoDB (STM durable + MTM)
    :19530  Milvus (MTM vector search)
    :8529   ArangoDB (LTM graph)
""")


# ── Entry point ───────────────────────────────────────────────────────────────

def run(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="jarviscore memory",
        description="JarvisCore Memory — manage and inspect agent memory tiers",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # status
    sub.add_parser("status", help="Health check all memory tiers")

    # context
    p_ctx = sub.add_parser("context", help="Dump recent memory for an agent")
    p_ctx.add_argument("--agent", required=True, help="Agent name (e.g. compass)")
    p_ctx.add_argument("--limit", type=int, default=20, help="Max STM events")

    # search
    p_srch = sub.add_parser("search", help="Semantic search agent memory")
    p_srch.add_argument("--agent", required=True, help="Agent name")
    p_srch.add_argument("--query", required=True, help="Natural language query")
    p_srch.add_argument("--limit", type=int, default=5, help="Max results")

    # up
    sub.add_parser("up", help="Instructions to start Athena locally")

    args = parser.parse_args(argv)

    if args.command == "status":
        asyncio.run(cmd_status(args))
    elif args.command == "context":
        asyncio.run(cmd_context(args))
    elif args.command == "search":
        asyncio.run(cmd_search(args))
    elif args.command == "up":
        cmd_up(args)


if __name__ == "__main__":
    run()
