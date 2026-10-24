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
from pathlib import Path
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

async def _athena_status(athena_url: str) -> list:
    from jarviscore.memory import get_athena_client
    lines: list = []
    client = get_athena_client()
    if client:
        health = await client.health_check(timeout=2.5)
        status = health.get("status", "unknown")
        if status in ("ok", "healthy", "pass", "UP"):
            lines.append((_ok, f"Athena MemOS  {athena_url}  [{status}]"))
            deps = health.get("dependencies", {})
            for dep, dep_status in deps.items():
                if dep_status in ("ok", "healthy", "pass", "UP", "true"):
                    lines.append((_ok, f"  └─ {dep}: {dep_status}"))
                else:
                    lines.append((_warn, f"  └─ {dep}: {dep_status}"))
        else:
            lines.append((_err, f"Athena MemOS  {athena_url}  [{status}]"))
        await client.close()
    return lines


def _redis_status() -> list:
    try:
        import redis as _redis
        r = _redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        r.ping()
        return [(_ok, f"Redis  {os.getenv('REDIS_HOST','localhost')}:{os.getenv('REDIS_PORT','6379')}  [connected]")]
    except ImportError:
        return [(_warn, "Redis  not installed — pip install 'jarviscore-framework[redis]'")]
    except Exception as exc:
        return [(_err, f"Redis  {exc}")]


async def cmd_status(_args: argparse.Namespace) -> None:
    """Show health status of all memory tiers."""
    _banner("JarvisCore Memory — Status", "═")

    athena_url = os.getenv("ATHENA_URL", "").strip()

    async def _no_athena() -> list:
        return [
            (_warn, "Athena MemOS  NOT CONFIGURED — set ATHENA_URL to enable"),
            (print, "         e.g. export ATHENA_URL=http://localhost:8080"),
        ]

    # 1. Athena and 2. Redis are checked concurrently, printed in order.
    athena_lines, redis_lines = await asyncio.gather(
        _athena_status(athena_url) if athena_url else _no_athena(),
        asyncio.to_thread(_redis_status),
    )
    for emit, msg in (*athena_lines, *redis_lines):
        emit(msg)

    # 3. Blob storage
    storage_backend = os.getenv("STORAGE_BACKEND", "local")
    if storage_backend == "azure":
        _ok("Blob  Azure Blob Storage  [configured]") if os.getenv("AZURE_STORAGE_CONNECTION_STRING") else _warn("Blob  Azure — AZURE_STORAGE_CONNECTION_STRING not set")
    else:
        base = os.getenv("STORAGE_BASE_PATH", os.path.join(".jarviscore", "blob_storage"))
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

    from jarviscore.memory import get_athena_client

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


def _post_json(url: str, key: str, body: dict) -> tuple[int, str]:
    """POST to an Azure deployment; returns (status, body text). Uses httpx, which
    verifies TLS with certifi's CA bundle (urllib depends on the interpreter's, which
    python.org builds on macOS do not install)."""
    import httpx

    try:
        resp = httpx.post(url, json=body, headers={"api-key": key}, timeout=30)
        return resp.status_code, resp.text
    except Exception as exc:
        return 0, str(exc)


def _check_azure_deployments(key: str, chat: str, embedding: str) -> None:
    """Warn now, not after memory silently stops forming, when a deployment is missing.

    Reasoning deployments (gpt-5 and later, o-series) reject ``max_tokens``; that is
    detected here and passed to Athena (``ATHENA_LLM_REASONING``) so it sends the
    parameters they accept from its first request."""
    ask = {"messages": [{"role": "user", "content": "ok"}]}
    status, body = _post_json(os.environ["ATHENA_LLM_BASE_URL"], key, {**ask, "max_tokens": 1})
    if status == 400 and "max_completion_tokens" in body:
        status, body = _post_json(os.environ["ATHENA_LLM_BASE_URL"], key, {**ask, "max_completion_tokens": 64})
        if status == 200:
            os.environ.setdefault("ATHENA_LLM_REASONING", "true")
            print(f"  ✅  '{chat}' is a reasoning deployment; Athena will send it the parameters it accepts")
    if status != 200:
        _warn(f"Azure chat deployment '{chat}' did not answer ({status}: {body[:160]}). Set "
              "ATHENA_AZURE_CHAT_DEPLOYMENT to a deployed chat model (default gpt-4o-mini).")
    status, body = _post_json(os.environ["ATHENA_EMBEDDING_BASE_URL"], key, {"input": "ok"})
    if status != 200:
        _warn(f"Azure embedding deployment '{embedding}' did not answer ({status}: {body[:160]}). Set "
              "ATHENA_AZURE_EMBEDDING_DEPLOYMENT to a deployed embedding model (default text-embedding-3-small).")


def _pick_llm_key() -> tuple[str, str, str]:
    """
    Find an LLM API key from the current environment.
    Returns (provider, key, model). Prefers Gemini, then Azure OpenAI,
    then OpenAI, then Anthropic.
    """
    # Azure needs the endpoint too; the compose passes AZURE_OPENAI_* through
    azure_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip() or os.environ.get("AZURE_API_KEY", "").strip()
    azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip() or os.environ.get("AZURE_ENDPOINT", "").strip()
    # Athena's providers are Gemini, Azure OpenAI and OpenAI (it has no Anthropic provider).
    checks = [
        ("gemini", "GEMINI_API_KEY", "gemini-2.0-flash"),
        ("gemini", "GOOGLE_API_KEY", "gemini-2.0-flash"),
        ("openai", "OPENAI_API_KEY", "gpt-4o-mini"),
    ]
    for provider, env_var, model in checks[:2]:
        key = os.environ.get(env_var, "").strip()
        if key:
            return provider, key, model
    if azure_key and azure_endpoint:
        # Athena summarises with max_tokens and temperature, which reasoning
        # deployments (gpt-5 and later) refuse: it needs a chat deployment of its own.
        model = os.environ.get("ATHENA_AZURE_CHAT_DEPLOYMENT", "").strip() or "gpt-4o-mini"
        embedding = os.environ.get("ATHENA_AZURE_EMBEDDING_DEPLOYMENT", "").strip() or "text-embedding-3-small"
        base = azure_endpoint.rstrip("/")
        os.environ.setdefault("AZURE_OPENAI_API_KEY", azure_key)
        os.environ.setdefault("AZURE_OPENAI_ENDPOINT", base)
        os.environ.setdefault("ATHENA_LLM_BASE_URL",
                              f"{base}/openai/deployments/{model}/chat/completions?api-version=2024-08-01-preview")
        os.environ.setdefault("ATHENA_EMBEDDING_BASE_URL",
                              f"{base}/openai/deployments/{embedding}/embeddings?api-version=2023-05-15")
        _check_azure_deployments(azure_key, model, embedding)
        return "azure", azure_key, model
    if azure_key and not azure_endpoint:
        _warn("AZURE_OPENAI_API_KEY is set but AZURE_OPENAI_ENDPOINT is not; skipping Azure")
    for provider, env_var, model in checks[2:]:
        key = os.environ.get(env_var, "").strip()
        if key:
            return provider, key, model
    return "gemini", "", "gemini-2.0-flash"


def _dotenv_value(path: Path, name: str) -> str:
    """Return NAME's value from a .env file, or "" if the file or line is absent."""
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def _append_dotenv(path: Path, name: str, value: str) -> None:
    """Add NAME=value as its own line, even when the file's last line has no newline."""
    text = path.read_text() if path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(f"{text}{name}={value}\n")


def cmd_init(args: argparse.Namespace) -> None:
    """
    One-command Athena setup — same philosophy as 'jarviscore nexus init'.

    1. Pick an LLM API key from the existing environment
    2. Pull + start all 7 services via docker compose
       (--from-source builds Athena from a local clone instead)
    3. Wait for Athena to be healthy (up to 90s — Milvus is slow)
    4. Write ATHENA_URL and ATHENA_API_KEY to the project .env
    """
    import shutil
    import subprocess
    import time
    import urllib.error
    import urllib.request

    _banner("JarvisCore — Athena MemOS Init", "═")

    if not shutil.which("docker"):
        _err("Docker not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop")
        sys.exit(1)

    from_source = bool(getattr(args, "from_source", False))
    athena_dir = None
    if from_source:
        athena_dir = _find_athena_repo()
        if not athena_dir:
            _err("--from-source needs an Athena clone.")
            print()
            print("  Clone the Athena repo first:")
            print("    git clone https://github.com/Prescott-Data/athena ~/athena")
            print()
            print("  Or set ATHENA_DIR to point at an existing clone:")
            print("    export ATHENA_DIR=/path/to/athena")
            print()
            sys.exit(1)
        print(f"  ✅  Athena source: {athena_dir}")
    else:
        print(f"  ✅  Athena image: {os.environ.get('ATHENA_IMAGE') or 'ghcr.io/prescott-data/athena:v0.2.0'}")

    # LLM key
    provider, llm_key, model = _pick_llm_key()
    if not llm_key:
        _err("No LLM API key found. Set one of: GEMINI_API_KEY, AZURE_OPENAI_API_KEY (+ AZURE_OPENAI_ENDPOINT), OPENAI_API_KEY")
        sys.exit(1)
    print(f"  ✅  LLM: {provider} / {model}")

    # Athena requires authentication. JarvisCore holds a service key: it serves
    # many tenants and names the tenant in each request.
    env_file = Path.cwd() / ".env"
    api_key = os.environ.get("ATHENA_API_KEY", "").strip() or _dotenv_value(env_file, "ATHENA_API_KEY")
    generated_key = not api_key
    if generated_key:
        import secrets
        api_key = secrets.token_hex(32)

    # Prepare env for compose
    env = {
        **os.environ,
        "ATHENA_API_KEY":       api_key,
        "ATHENA_LLM_API_KEY":   llm_key,
        "ATHENA_LLM_PROVIDER":  provider,
        "ATHENA_LLM_MODEL":     model,
    }
    compose_cmd = ["docker", "compose", "-f", None, "up", "-d"]
    if from_source:
        env["ATHENA_BUILD_CONTEXT"] = str(athena_dir)
        env["ATHENA_IMAGE"] = "athena-memos:local"
        compose_cmd.append("--build")

    compose = _compose_file()
    compose_cmd[3] = str(compose)
    env["ATHENA_MONGO_INIT"] = str(compose.parent / "init-mongo.js")
    print(f"  ✅  Compose file: {compose}")
    print()
    if from_source:
        print("  Building Athena from source (first build takes ~2 min)...")
    else:
        print("  Pulling images and starting the stack (first pull takes ~2 min)...")
    print()

    result = subprocess.run(
        compose_cmd,
        env=env,
        text=True,
    )
    if result.returncode != 0:
        _err("Docker Compose failed — check output above.")
        sys.exit(1)

    # 4. Wait for Athena health (up to 90s — Milvus init is slow)
    print()
    print("  Waiting for Athena to be ready (Milvus takes ~60s on first boot)...")
    athena_port = os.environ.get("ATHENA_PORT", "8080").strip() or "8080"
    athena_url = f"http://localhost:{athena_port}"
    start = time.monotonic()
    deadline = start + 90
    next_report = 10
    while True:
        try:
            remaining = deadline - time.monotonic()
            req = urllib.request.Request(f"{athena_url}/api/v1/health", headers={"X-API-Key": api_key})
            resp = urllib.request.urlopen(req, timeout=max(0.1, min(2, remaining)))
            data = json.loads(resp.read())
            if data.get("status") in ("ok", "healthy", "pass", "UP"):
                break
        except Exception:
            pass
        if time.monotonic() >= deadline:
            _warn("Athena didn't become healthy in 90s — check: docker logs athena")
            sys.exit(1)
        time.sleep(max(0, min(1, deadline - time.monotonic())))
        if time.monotonic() - start >= next_report:
            print(f"    ...still waiting ({next_report}s)")
            next_report += 10

    # 5. Write ATHENA_URL and ATHENA_API_KEY to .env
    if _dotenv_value(env_file, "ATHENA_URL"):
        print("  ✅  ATHENA_URL already set")
    else:
        _append_dotenv(env_file, "ATHENA_URL", athena_url)
        print(f"  ✅  Wrote ATHENA_URL={athena_url} to {env_file}")
    if _dotenv_value(env_file, "ATHENA_API_KEY") or not generated_key:
        print("  ✅  ATHENA_API_KEY already set")
    else:
        _append_dotenv(env_file, "ATHENA_API_KEY", api_key)
        print(f"  ✅  Wrote a new ATHENA_API_KEY to {env_file} (keep it secret)")

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
""")


# ── Entry point ───────────────────────────────────────────────────────────────

def run(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="jarviscore memory",
        description="JarvisCore Memory — manage and inspect agent memory tiers",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="First-time setup: pull + start the Athena stack (run once)")
    p_init.add_argument(
        "--from-source",
        action="store_true",
        help="Build Athena from a local clone (~/athena or ATHENA_DIR) instead of pulling the image",
    )

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

    # up (alias for init: kept because docs and error messages reference it)
    sub.add_parser("up", help="Start the Athena stack (alias for init)")

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
        # pre-existing bug: cmd_up never existed, so 'memory up' crashed with
        # NameError. init is idempotent (compose up), so alias it.
        args.from_source = False
        cmd_init(args)


if __name__ == "__main__":
    run()
