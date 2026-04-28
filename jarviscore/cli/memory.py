"""
jarviscore.cli.memory — 'python -m jarviscore.cli memory' subcommand.

Commands:
    status                      — health check Athena + Redis + Blob tiers
    context --agent <name>      — dump recent STM + MTM for an agent
    search  --agent <name> --query <q>  — semantic search agent memory
    up                          — guide to starting Athena stack locally

Usage:
    python -m jarviscore.cli memory status
    python -m jarviscore.cli memory context --agent my-agent
    python -m jarviscore.cli memory search --agent my-agent --query "analyse market data"
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


def _compose_file() -> Path:
    """Find docker-compose.athena.yml — bundled inside the installed package."""
    import importlib.resources as ir
    try:
        with ir.path("jarviscore.memory._data", "docker-compose.athena.yml") as p:
            if p.exists():
                return Path(p)
    except Exception:
        pass
    # Fallback: repo root
    candidates = [
        Path(__file__).parent.parent.parent / "jarviscore" / "memory" / "_data" / "docker-compose.athena.yml",
        Path.cwd() / "docker-compose.athena.yml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _find_athena_repo() -> Optional[Path]:
    """
    Locate the Athena source repo on this machine.

    Priority:
      1. ATHENA_DIR env var
      2. ~/athena
      3. ../athena (sibling of cwd)
    """
    # 1. Explicit env override
    env_dir = os.environ.get("ATHENA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir)
        if (p / "Dockerfile").exists():
            return p

    # 2. ~/athena (common default location)
    home_path = Path.home() / "athena"
    if (home_path / "Dockerfile").exists():
        return home_path

    # 3. Sibling directory
    sibling = Path.cwd().parent / "athena"
    if (sibling / "Dockerfile").exists():
        return sibling

    return None


def _pick_llm_key() -> tuple[str, str]:
    """
    Find an LLM API key from the current environment.
    Returns (provider, key) — prefers Gemini, then Anthropic, then OpenAI.
    """
    checks = [
        ("gemini", "GEMINI_API_KEY", "gemini-2.0-flash"),
        ("gemini", "GOOGLE_API_KEY", "gemini-2.0-flash"),
        ("openai", "OPENAI_API_KEY", "gpt-4o-mini"),
        ("anthropic", "ANTHROPIC_API_KEY", "claude-3-haiku-20240307"),
    ]
    for provider, env_var, model in checks:
        key = os.environ.get(env_var, "").strip()
        if key:
            return provider, key, model
    return "gemini", "", "gemini-2.0-flash"


def cmd_init(_args: argparse.Namespace) -> None:
    """
    One-command Athena setup — same philosophy as 'jarviscore nexus init'.

    1. Find the Athena source repo (~/athena or ATHENA_DIR)
    2. Pick an LLM API key from the existing environment
    3. Build + start all 7 services via docker compose
    4. Wait for Athena to be healthy (up to 90s — Milvus is slow)
    5. Write ATHENA_URL to the project .env
    """
    import shutil, subprocess, time, urllib.request, urllib.error

    _banner("JarvisCore — Athena MemOS Init", "═")

    if not shutil.which("docker"):
        _err("Docker not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop")
        sys.exit(1)

    # 1. Find Athena source
    athena_dir = _find_athena_repo()
    if not athena_dir:
        _err("Athena source repo not found.")
        print()
        print("  Clone the Athena repo first:")
        print("    git clone <athena-repo-url> ~/athena")
        print()
        print("  Or set ATHENA_DIR to point at your clone:")
        print("    export ATHENA_DIR=/path/to/athena")
        print()
        sys.exit(1)

    print(f"  ✅  Athena source: {athena_dir}")

    # 2. Pick LLM key
    provider, llm_key, model = _pick_llm_key()
    if not llm_key:
        _err("No LLM API key found. Set one of: GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY")
        sys.exit(1)
    print(f"  ✅  LLM: {provider} / {model}")

    # 3. Prepare env for compose
    env = {
        **os.environ,
        "ATHENA_BUILD_CONTEXT": str(athena_dir),
        "ATHENA_LLM_API_KEY":   llm_key,
        "ATHENA_LLM_PROVIDER":  provider,
        "ATHENA_LLM_MODEL":     model,
    }

    compose = _compose_file()
    print(f"  ✅  Compose file: {compose}")
    print()
    print("  Building Athena from source (first build takes ~2 min)...")
    print()

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose), "up", "-d", "--build"],
        env=env,
        text=True,
    )
    if result.returncode != 0:
        _err("Docker Compose failed — check output above.")
        sys.exit(1)

    # 4. Wait for Athena health (up to 90s — Milvus init is slow)
    print()
    print("  Waiting for Athena to be ready (Milvus takes ~60s on first boot)...")
    athena_url = "http://localhost:8080"
    for attempt in range(90):
        try:
            resp = urllib.request.urlopen(f"{athena_url}/api/v1/health", timeout=2)
            data = json.loads(resp.read())
            if data.get("status") in ("ok", "healthy", "pass", "UP"):
                break
        except Exception:
            pass
        time.sleep(1)
        if attempt % 10 == 9:
            print(f"    ...still waiting ({attempt + 1}s)")
    else:
        _warn("Athena didn't become healthy in 90s — check: docker logs athena")
        sys.exit(1)

    # 5. Write ATHENA_URL to .env
    env_file = Path.cwd() / ".env"
    env_text = env_file.read_text() if env_file.exists() else ""
    if "ATHENA_URL" not in env_text:
        env_text += f"\nATHENA_URL={athena_url}\n"
        env_file.write_text(env_text)
        print(f"  ✅  Wrote ATHENA_URL={athena_url} to {env_file}")
    else:
        print(f"  ✅  ATHENA_URL already set")

    print()
    _banner("Athena is live!", "─")
    print(f"""
  Memory tiers:     STM → Redis   MTM → MongoDB + Milvus   LTM → ArangoDB
  Athena URL:       {athena_url}
  Health check:     {athena_url}/api/v1/health

  Verify from JarvisCore:
    jarviscore memory status

  Once an agent runs, inspect its memory:
    jarviscore memory context --agent <agent-name>
    jarviscore memory search  --agent <agent-name> --query "market research"

  When a pre-built Docker image is available, swap to:
    jarviscore memory pull     # (coming soon)
""")


# ── Entry point ───────────────────────────────────────────────────────────────

def run(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="jarviscore memory",
        description="JarvisCore Memory — manage and inspect agent memory tiers",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="First-time setup: build + start Athena stack (run once)")

    # status
    sub.add_parser("status", help="Health check all memory tiers")

    # context
    p_ctx = sub.add_parser("context", help="Dump recent memory for an agent")
    p_ctx.add_argument("--agent", required=True, help="Agent name (e.g. researcher)")
    p_ctx.add_argument("--limit", type=int, default=20, help="Max STM events")

    # search
    p_srch = sub.add_parser("search", help="Semantic search agent memory")
    p_srch.add_argument("--agent", required=True, help="Agent name")
    p_srch.add_argument("--query", required=True, help="Natural language query")
    p_srch.add_argument("--limit", type=int, default=5, help="Max results")

    # up
    sub.add_parser("up", help="Instructions to start Athena locally")

    args = parser.parse_args(argv)

    if args.command == "init":
        cmd_init(args)
    elif args.command == "status":
        asyncio.run(cmd_status(args))
    elif args.command == "context":
        asyncio.run(cmd_context(args))
    elif args.command == "search":
        asyncio.run(cmd_search(args))
    elif args.command == "up":
        cmd_up(args)


if __name__ == "__main__":
    run()
