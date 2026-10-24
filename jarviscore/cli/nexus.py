"""
jarviscore nexus — Developer setup tool for Nexus auth infrastructure.

Usage:
    python -m jarviscore.cli nexus init
    python -m jarviscore.cli nexus status
    python -m jarviscore.cli nexus up
    python -m jarviscore.cli nexus register github --client-id=GH_ID      # secret is prompted for
    python -m jarviscore.cli nexus register stripe                        # API key is prompted for
    python -m jarviscore.cli nexus list
    python -m jarviscore.cli nexus test github

This command is the developer's single entry point for:
  1. Checking if a Nexus Gateway is reachable
  2. Starting a local Nexus stack via Docker Compose
  3. Registering connected app credentials (client IDs, secrets, API keys)
  4. Listing registered providers
  5. Testing that a connection works end-to-end
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── Colour helpers ───────────────────────────────────────────────────────────

def _ok(msg: str)  -> str: return f"\033[32m✓\033[0m  {msg}"
def _err(msg: str) -> str: return f"\033[31m✗\033[0m  {msg}"
def _warn(msg: str)-> str: return f"\033[33m!\033[0m  {msg}"
def _info(msg: str)-> str: return f"\033[36mℹ\033[0m  {msg}"
def _bold(msg: str)-> str: return f"\033[1m{msg}\033[0m"

# ── Docker Compose file location ─────────────────────────────────────────────

def _compose_file() -> Path:
    """Find docker-compose.nexus.yml — bundled inside the installed package."""
    import importlib.resources as ir
    # 1. Bundled inside the wheel (works after pip install)
    try:
        with ir.path("jarviscore.nexus._data", "docker-compose.nexus.yml") as p:
            if p.exists():
                return Path(p)
    except Exception:
        pass
    # 2. Repo root (works when running from a git clone)
    candidates = [
        Path(__file__).parent.parent.parent / "docker-compose.nexus.yml",
        Path.cwd() / "docker-compose.nexus.yml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


# ── Nexus Gateway URL ─────────────────────────────────────────────────────────

def _env_or_dotenv(name: str) -> Optional[str]:
    """Read one variable from the environment, else from ./.env.

    The file is parsed with python-dotenv, so quoting and inline comments
    (`KEY=value # note`) are handled the way Settings handles them.
    """
    value = os.environ.get(name, "")
    if value:
        return value
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        from dotenv import dotenv_values
        return dotenv_values(env_file).get(name) or None
    return None


# ── Stack secrets ────────────────────────────────────────────────────────────
#
# The broker's secrets belong to the broker. A project .env is loaded by every
# agent process, and a process holding NEXUS_ENCRYPTION_KEY can decrypt every
# stored credential; one agent already listed it into a user-facing answer.
# Agents get the Gateway URL and a Gateway API key, which is all they use.

#: Only the broker and gateway containers read these.
STACK_SECRETS = (
    "NEXUS_ENCRYPTION_KEY",
    "NEXUS_STATE_KEY",
    "NEXUS_BROKER_API_KEY",
    "NEXUS_GATEWAY_API_KEY",
)

#: Never written to, and moved out of, the project .env.
BROKER_ONLY_SECRETS = ("NEXUS_ENCRYPTION_KEY", "NEXUS_STATE_KEY", "NEXUS_BROKER_API_KEY")

#: The placeholder older stacks shipped as the broker API key.
_DEV_BROKER_KEY = "dev-broker-api-key-change-in-prod"


def _stack_env_path() -> Path:
    return Path.home() / ".jarviscore" / "nexus" / "stack.env"


def _read_env_file(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_private(path: Path, text: str, private_dir: bool = True) -> None:
    """Write a file only the current user can read; optionally lock its directory to 0700."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if private_dir:
        os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def _generate_secret(name: str) -> str:
    import base64, secrets
    if name in ("NEXUS_ENCRYPTION_KEY", "NEXUS_STATE_KEY"):
        return base64.b64encode(secrets.token_bytes(32)).decode()
    return secrets.token_urlsafe(32)


def ensure_stack_secrets(project_env: Path, stack_env: Path) -> tuple:
    """
    Make sure the stack's secrets exist in ``stack_env`` and only there.

    Keys an older ``nexus init`` wrote to the project .env are adopted rather
    than regenerated: a new ENCRYPTION_KEY would leave every stored credential
    unreadable. A broker-only key is removed from the project .env only when
    ``stack_env`` holds the same value, so the copy that decrypts an existing
    database is never the one deleted.

    Returns (secrets, notes): the stack's secrets and what was done, for display.
    """
    notes = []
    stack = _read_env_file(stack_env)
    project = _read_env_file(project_env)

    for name in STACK_SECRETS:
        if stack.get(name):
            continue
        legacy = project.get(name) or os.environ.get(name, "")
        if legacy and legacy != _DEV_BROKER_KEY:
            stack[name] = legacy
            notes.append(f"Moved {name} from {project_env.name} to {stack_env}")
        else:
            stack[name] = _generate_secret(name)
            notes.append(f"Generated {name}")

    _write_private(
        stack_env,
        "# Nexus stack secrets. Read by the broker and gateway containers only.\n"
        "# Do not copy NEXUS_ENCRYPTION_KEY into a project .env: any process that\n"
        "# can read it can decrypt every stored credential. Back this file up.\n"
        + "".join(f"{name}={stack[name]}\n" for name in STACK_SECRETS),
    )

    kept, removed, conflicting = [], [], []
    lines = project_env.read_text().splitlines() if project_env.exists() else []
    for line in lines:
        name, _, value = line.partition("=")
        name = name.strip()
        if name in BROKER_ONLY_SECRETS and not line.lstrip().startswith("#"):
            value = value.strip().strip('"').strip("'")
            if value in (stack[name], _DEV_BROKER_KEY):
                removed.append(name)
                continue
            conflicting.append(name)
        kept.append(line)

    wanted = {
        "NEXUS_GATEWAY_URL": f"http://localhost:{os.environ.get('NEXUS_GATEWAY_PORT', '8090')}",
        "NEXUS_RETURN_URL": "http://localhost:8000/oauth/callback",
        "NEXUS_GATEWAY_API_KEY": stack["NEXUS_GATEWAY_API_KEY"],
    }
    present = {line.partition("=")[0].strip() for line in kept}
    for index, line in enumerate(kept):
        if line.partition("=")[0].strip() == "NEXUS_GATEWAY_API_KEY":
            kept[index] = f"NEXUS_GATEWAY_API_KEY={stack['NEXUS_GATEWAY_API_KEY']}"
    kept += [f"{name}={value}" for name, value in wanted.items() if name not in present]

    new_text = "\n".join(kept).strip("\n") + "\n"
    if not project_env.exists():
        _write_private(project_env, new_text, private_dir=False)
    elif new_text != project_env.read_text():
        project_env.write_text(new_text)
    for name in removed:
        notes.append(f"Removed {name} from {project_env.name}; agents no longer hold it")
    for name in conflicting:
        notes.append(
            f"WARNING {project_env.name} has a {name} that differs from {stack_env}. "
            "Left in place: find out which one encrypted your data, keep it in "
            f"{stack_env}, and delete the other"
        )
    return stack, notes


def _compose(stack_env: Path, secrets: dict, *args: str) -> int:
    """Run docker compose on the bundled stack with its secrets."""
    compose = _compose_file()
    print(_info(f"Compose file: {compose}"))
    return subprocess.run(
        ["docker", "compose", "-f", str(compose), "--env-file", str(stack_env), *args],
        text=True,
        # Explicit values win over anything exported from an older setup.
        env={**os.environ, **secrets},
    ).returncode


def _wait_healthy(url: str, seconds: int = 60) -> bool:
    import time, urllib.request
    deadline = time.monotonic() + seconds
    while True:
        try:
            remaining = deadline - time.monotonic()
            urllib.request.urlopen(url, timeout=max(0.1, min(2, remaining)))
            return True
        except Exception:
            if time.monotonic() >= deadline:
                return False
            time.sleep(max(0, min(1, deadline - time.monotonic())))


def _gateway_url() -> Optional[str]:
    """Read NEXUS_GATEWAY_URL from env or .env file."""
    return _env_or_dotenv("NEXUS_GATEWAY_URL")


def _gateway_api_key() -> Optional[str]:
    """Read NEXUS_GATEWAY_API_KEY from env or .env file (None when unset)."""
    return _env_or_dotenv("NEXUS_GATEWAY_API_KEY")


def _gateway_headers(extra: Optional[dict] = None) -> dict:
    """Headers every raw CLI call to the Gateway must carry: the caller API key, if set."""
    headers = dict(extra or {})
    key = _gateway_api_key()
    if key:
        headers["X-API-Key"] = key
    return headers


def _gateway_open(req, timeout: float):
    """urlopen for an authenticated Gateway call that never follows a redirect.

    urllib copies request headers onto the redirected request, so a redirect
    to another origin, or from https to http, would forward the caller API key.
    The Gateway API never redirects; a 3xx is surfaced as an HTTPError instead.
    """
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    return urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_status(args):
    """Check gateway reachability + local Docker state."""
    print(_bold("\nJarvisCore — Nexus Status\n"))

    # 1. Gateway URL
    url = _gateway_url()
    ping = None
    if not url:
        print(_warn("NEXUS_GATEWAY_URL not set in your .env"))
        print(_info("  Set it to http://localhost:8090 for local dev, or your deployed Gateway URL"))
    else:
        print(_ok(f"NEXUS_GATEWAY_URL = {url}"))

        # 2. Ping the gateway (in parallel with the Docker inspect below)
        import threading
        import urllib.request, urllib.error
        ping_lines: list = []

        def _ping() -> None:
            try:
                req = urllib.request.urlopen(f"{url}/health", timeout=5)
                if req.status == 200:
                    ping_lines.append(_ok("Gateway is reachable and healthy"))
                else:
                    ping_lines.append(_warn(f"Gateway responded with HTTP {req.status}"))
            except Exception as e:
                ping_lines.append(_err(f"Gateway not reachable: {e}"))
                ping_lines.append(_info("  Run: python -m jarviscore.cli nexus up"))

        ping = threading.Thread(target=_ping, daemon=True)
        ping.start()

    # 3. Secrets are where they belong
    secret_lines: list = []
    stack_env = _stack_env_path()
    if stack_env.exists():
        secret_lines.append(_ok(f"Stack secrets: {stack_env}"))
    leaked = [n for n in BROKER_ONLY_SECRETS if n in _read_env_file(Path.cwd() / ".env")]
    if leaked:
        secret_lines.append(_warn(f"{', '.join(leaked)} in ./.env — agents can read it and decrypt every credential"))
        secret_lines.append(_info("  Run: jarviscore nexus up   (moves them to the stack's private file)"))

    # 4. Docker container state
    names = ("nexus-broker", "nexus-gateway", "nexus-db")
    docker_lines: list = []
    if shutil.which("docker"):
        try:
            # Missing containers go to stderr; the found ones are still listed on stdout.
            out = subprocess.run(
                ["docker", "inspect", "--format", "{{.Name}}|{{.State.Status}}", *names],
                capture_output=True, text=True, timeout=10,
            )
            states = {}
            for line in out.stdout.splitlines():
                cname, _, cstatus = line.partition("|")
                states[cname.lstrip("/")] = cstatus.strip()
            for name in names:
                status = states.get(name, "")
                if status == "running":
                    docker_lines.append(_ok(f"Container {name}: running"))
                elif status:
                    docker_lines.append(_warn(f"Container {name}: {status}"))
                else:
                    docker_lines.append(_err(f"Container {name}: not found (run 'nexus up')"))
        except Exception as e:
            docker_lines.append(_warn(f"Could not inspect Docker containers: {e}"))
    else:
        docker_lines.append(_warn("Docker not found — needed for local Nexus stack"))

    if ping is not None:
        ping.join()
        for line in ping_lines:
            print(line)
    for line in (*secret_lines, *docker_lines):
        print(line)

    print()


def cmd_init(args):
    """
    One-command first-time setup:
      1. Generate the stack's secrets into ~/.jarviscore/nexus/stack.env (0600),
         adopting keys an older init left in the project .env
      2. Give the project .env what agents use: Gateway URL and Gateway API key
      3. Start the local Docker stack and wait for broker and gateway health
    """
    print(_bold("\nJarvisCore — Nexus Init\n"))
    _start_stack(first_run=True)

    print(_bold("  Next step — register your OAuth apps:"))
    print()
    print("    jarviscore nexus register github --client-id=YOUR_GH_CLIENT_ID")
    print("    # the client secret is prompted for, so it stays out of shell history")
    print()
    print("  Then connect an account:")
    print("    jarviscore nexus test github")
    print()


def cmd_up(args):
    """Start the local Nexus stack with the secrets from ~/.jarviscore/nexus/stack.env."""
    print(_bold("\nStarting local Nexus stack...\n"))
    _start_stack(first_run=False)


def _start_stack(first_run: bool) -> None:
    if not shutil.which("docker"):
        print(_err("Docker not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop"))
        sys.exit(1)

    project_env = Path.cwd() / ".env"
    stack_env = _stack_env_path()
    secrets, notes = ensure_stack_secrets(project_env, stack_env)
    for note in notes:
        print(_warn(note[len("WARNING "):]) if note.startswith("WARNING ") else _ok(note))
    if first_run or notes:
        print(_ok(f"Stack secrets: {stack_env} (readable by you only)"))
        print(_ok(f"Agent settings: {project_env} (NEXUS_GATEWAY_URL, NEXUS_GATEWAY_API_KEY)"))
    print()

    if _compose(stack_env, secrets, "up", "-d", "--pull", "missing") != 0:
        print(_err("Docker Compose failed — check output above."))
        sys.exit(1)

    broker_port = os.environ.get("NEXUS_BROKER_PORT", "8080")
    gateway_port = os.environ.get("NEXUS_GATEWAY_PORT", "8090")
    print()
    print(_info("Waiting for broker and gateway to be ready..."))
    if not _wait_healthy(f"http://localhost:{broker_port}/health"):
        print(_warn("Broker didn't respond in 60s — check `docker logs nexus-broker`"))
        sys.exit(1)
    if not _wait_healthy(f"http://localhost:{gateway_port}/health"):
        print(_warn("Gateway didn't respond in 60s — check `docker logs nexus-gateway`"))
        sys.exit(1)

    print(_ok("Nexus stack is up and healthy!"))
    print(_info(f"  Gateway: http://localhost:{gateway_port}  (requires NEXUS_GATEWAY_API_KEY)"))
    print()


def _prompt_secret(label: str) -> Optional[str]:
    """Ask for a secret without echoing it; a flag would leave it in shell history."""
    if not sys.stdin.isatty():
        return None
    import getpass
    return getpass.getpass(f"  {label} (input hidden): ").strip() or None


def _placement_from_args(args) -> dict:
    """Credential placement supplied on the command line."""
    flags = {
        "header_name":      getattr(args, "header_name", None),
        "value_prefix":     getattr(args, "value_prefix", None),
        "param_name":       getattr(args, "param_name", None),
        "credential_field": getattr(args, "credential_field", None),
    }
    return {key: value for key, value in flags.items() if value}


def cmd_register(args):
    """Register a provider's credentials — local store or gateway."""
    from jarviscore.nexus.providers import (
        PROVIDER_CATALOG,
        broker_name,
        get_auth_config,
        get_auth_type,
        get_provider,
    )
    from jarviscore.nexus.store import get_store

    provider = args.provider.lower()
    catalog_entry = get_provider(provider) or {}

    auth_type = (getattr(args, "auth_type", None) or catalog_entry.get("auth_type") or "").lower()
    if not auth_type:
        print(_err(f"{provider!r} is not preconfigured, so its auth type must be given"))
        print(_info("  --auth-type=oauth2 | api_key | basic_auth"))
        print(_info("  api_key also needs where the key goes: --header-name=X-API-KEY"))
        print(_info("  (optionally --value-prefix='Bearer ') or --param-name=api_key"))
        sys.exit(1)
    label = catalog_entry.get("label", provider)

    # Flags win over catalog defaults — the person connecting the app is reading
    # that provider's API docs right now.
    auth_config = {**get_auth_config(provider), **_placement_from_args(args)}

    # Build credentials dict based on auth type
    if auth_type == "oauth2":
        args.client_secret = args.client_secret or _prompt_secret(f"{label} client secret")
        if not args.client_id or not args.client_secret:
            print(_err(f"{label} requires --client-id and --client-secret"))
            _print_console_url(provider)
            sys.exit(1)
        credentials = {
            "auth_type":     "oauth2",
            "client_id":     args.client_id,
            "client_secret": args.client_secret,
            "scopes":        catalog_entry.get("scopes", []),
        }
    elif auth_type == "api_key":
        api_key = args.api_key or args.client_id or _prompt_secret(f"{label} API key")
        if not api_key:
            print(_err(f"{label} requires --api-key"))
            _print_console_url(provider)
            sys.exit(1)
        if not auth_config:
            print(_err(f"{label} needs to know where its API key goes"))
            print(_info(
                "An API key has no standard location — X-API-KEY, api-key, "
                "Authorization: Bearer and ?api_key= are all in use. State it:"
            ))
            print(_info("  --header-name=X-API-KEY  [--value-prefix='Bearer ']"))
            print(_info("  --param-name=api_key     (for keys sent as a query parameter)"))
            sys.exit(1)
        credentials = {
            "auth_type": "api_key",
            "api_key": api_key,
        }
    elif auth_type == "basic_auth":
        args.client_secret = args.client_secret or _prompt_secret(f"{label} password or token")
        if not args.client_id or not args.client_secret:
            print(_err(f"{label} requires --client-id (username) and --client-secret (token)"))
            sys.exit(1)
        credentials = {
            "auth_type": "basic_auth",
            "username":  args.client_id,
            "password":  args.client_secret,
        }
    else:
        print(_err(f"Unsupported auth_type: {auth_type}"))
        sys.exit(1)

    if auth_config:
        credentials["auth_config"] = auth_config

    gateway_url = _gateway_url()

    if gateway_url:
        # ── Gateway mode: POST to running Nexus Gateway ──────────────────────
        import urllib.request, urllib.error
        print(_bold(f"\nRegistering {label} ({auth_type}) with Nexus Gateway...\n"))
        try:
            # Nexus Gateway API: POST /v1/providers
            # Payload must be wrapped in a `profile` object with `name` (not `provider`).
            # Reference: nexus-framework/docs/PROVIDER_REGISTRATION_GUIDE.md
            profile: dict = {"name": broker_name(provider), "auth_type": auth_type}
            if auth_type == "oauth2":
                profile["client_id"]     = credentials["client_id"]
                profile["client_secret"] = credentials["client_secret"]
                profile["scopes"]        = credentials.get("scopes", [])
                # auth_url / token_url / user_info_endpoint come from _data.PROVIDER_URLS
                from jarviscore.nexus._data import PROVIDER_URLS
                urls = PROVIDER_URLS.get(provider, {})
                if urls.get("auth_url"):     profile["auth_url"]            = urls["auth_url"]
                if urls.get("token_url"):    profile["token_url"]           = urls["token_url"]
                if urls.get("user_info"):    profile["user_info_endpoint"]  = urls["user_info"]
            elif auth_type == "api_key":
                profile["params"] = {
                    "credential_schema": {
                        "type": "object",
                        "required": ["api_key"],
                        "properties": {"api_key": {"type": "string", "title": "API Key"}},
                    }
                }
            elif auth_type == "basic_auth":
                profile["params"] = {
                    "credential_schema": {
                        "type": "object",
                        "required": ["username", "password"],
                        "properties": {
                            "username": {"type": "string", "title": "Username"},
                            "password": {"type": "string", "title": "Password", "format": "password"},
                        },
                    }
                }

            payload = json.dumps({"profile": profile}).encode()
            req = urllib.request.Request(
                f"{gateway_url}/v1/providers",
                data=payload,
                headers={"Content-Type": "application/json", **_gateway_headers()},
                method="POST",
            )
            resp = _gateway_open(req, timeout=10)
            body = json.loads(resp.read())
            print(_ok(f"{label} registered with gateway"))
            print(_info(f"  Provider ID: {body.get('id', body.get('provider_id', provider))}"))
        except urllib.error.HTTPError as e:
            print(_err(f"Gateway registration failed (HTTP {e.code}): {e.read().decode()}"))
            sys.exit(1)
        except Exception as e:
            print(_warn(f"Gateway unreachable ({e}) — falling back to local store"))
            _register_local(get_store(), provider, label, auth_type, credentials)
    else:
        # ── Local store mode: zero-dep encrypted file ─────────────────────────
        _register_local(get_store(), provider, label, auth_type, credentials)


def _seed_broker_db(provider: str, credentials: dict, workspace_id: str) -> bool:
    """
    Upsert provider credentials directly into the broker DB.
    Called automatically after `nexus register` when the local stack is running.
    Silently skips if psycopg2 isn't installed or DB isn't reachable.
    """
    try:
        import psycopg2
    except ImportError:
        return False  # psycopg2 optional — local store is the source of truth

    from jarviscore.nexus.store import NexusLocalStore
    from jarviscore.nexus._data import PROVIDER_URLS
    from jarviscore.nexus.providers import broker_name

    db_url = os.environ.get(
        "NEXUS_DB_URL",
        os.environ.get("DATABASE_URL", "postgresql://nexus:nexus@localhost:5432/nexus?sslmode=disable"),
    )
    urls = PROVIDER_URLS.get(provider, {})

    try:
        conn = psycopg2.connect(db_url, connect_timeout=3)
        conn.autocommit = False
        cur = conn.cursor()
        # Ensure workspace exists
        cur.execute(
            "INSERT INTO workspaces (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
            (workspace_id, f"{workspace_id}-workspace"),
        )
        cur.execute(
            """
            INSERT INTO provider_profiles
                (workspace_id, name, auth_type, client_id, client_secret,
                 auth_url, token_url, user_info_endpoint, scopes, pkce_enabled, params)
            VALUES (%s, %s, 'oauth2', %s, %s, %s, %s, %s, %s, true, %s)
            ON CONFLICT (workspace_id, name) DO UPDATE SET
                client_id          = EXCLUDED.client_id,
                client_secret      = EXCLUDED.client_secret,
                params             = EXCLUDED.params,
                updated_at         = NOW();
            """,
            (
                # The name request_connection will ask the broker for.
                workspace_id, broker_name(provider),
                credentials.get("client_id", ""),
                credentials.get("client_secret", ""),
                urls.get("auth_url", ""), urls.get("token_url", ""),
                urls.get("user_info_endpoint", ""),
                credentials.get("scopes", []),
                # The broker appends these to the authorization URL. For Google
                # this is how a refresh token is asked for at all.
                json.dumps(urls.get("params")) if urls.get("params") else None,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception:
        return False


def _register_local(store, provider, label, auth_type, credentials):
    """Write credentials to the local encrypted store and optionally seed the broker DB."""
    import uuid as _uuid
    store.register(provider, credentials)
    print(_bold(f"\nRegistering {label} ({auth_type})...\n"))
    print(_ok(f"{label} registered in local credential store"))
    print(_info(f"  Stored at: {store._path}"))
    print(_info( "  Credentials are AES-256-GCM encrypted at rest"))

    # Auto-seed the broker DB if the local stack is running (OAuth2 only)
    if auth_type == "oauth2":
        # The same identity the runtime authenticates as. A different one here
        # put seeded apps in a workspace the agents never looked in, so consent
        # 404ed for every provider registered from the CLI.
        from jarviscore.config import Settings
        user_env = os.environ.get("NEXUS_USER_ID") or Settings().nexus_default_user_id
        try:
            workspace_id = str(_uuid.UUID(user_env))
        except ValueError:
            workspace_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, user_env))
        seeded = _seed_broker_db(provider, credentials, workspace_id)
        if seeded:
            print(_ok(f"  Synced to local Nexus broker DB (workspace: {workspace_id[:8]}...)"))
        else:
            print(_info("  Local broker DB not reachable — run 'jarviscore nexus init' to start the stack"))

    print()
    if auth_type == "oauth2" and not credentials.get("access_token"):
        # Registering the app is not the same as connecting an account. Saying
        # "ready" here is how a missing consent step turns into an unexplained
        # 401 much later, inside an agent run.
        print(_warn(f"  {label}'s app is registered. No account is connected yet."))
        print(_info( "  OAuth2 needs a user to consent before a token exists. Run:"))
        print(_info( "    jarviscore nexus init      # start the Nexus stack, once"))
        print(_info(f"    jarviscore nexus test {provider}"))
        print(_info( "  If the provider issues a static token instead, such as a personal"))
        print(_info( "  or private app token, register it as the header strategy it is:"))
        print(_info(f"    jarviscore nexus register {provider} --api-key=TOKEN --auth-type=api_key \\"))
        print(_info( "        --header-name=Authorization --value-prefix='Bearer '"))
    else:
        print(f"  Agents can now call {label} APIs via nexus_call().")
    print()


def cmd_list(args):
    """List registered providers — from local store and/or gateway."""
    from jarviscore.nexus.store import get_store

    print(_bold("\nRegistered Providers\n"))

    # Always show local store first
    store = get_store()
    local = store.get_summary()
    if local:
        print(_bold("  Local store:"))
        for entry in local:
            name   = entry["provider"]
            atype  = entry["auth_type"]
            masked = entry["client_id"]
            reg    = entry["registered_at"][:10]
            print(f"  {_ok(name):<30} {atype:<12} id={masked}  ({reg})")
        print()
    else:
        print(_warn("  No providers in local store."))
        print(_info("  Register one: python -m jarviscore.cli nexus register github --client-id=... --client-secret=..."))
        print()

    # If gateway is configured, also show gateway providers
    gateway_url = _gateway_url()
    if gateway_url:
        import urllib.request, urllib.error
        try:
            req = urllib.request.Request(f"{gateway_url}/v1/providers", headers=_gateway_headers())
            providers = json.loads(_gateway_open(req, timeout=5).read())
            if providers:
                print(_bold("  Gateway providers:"))
                for p in providers:
                    name = p.get("provider", p.get("name", "?"))
                    atype = p.get("auth_type", "?")
                    print(f"  {_ok(name):<30} {atype}")
                print()
        except Exception:
            pass  # gateway optional — don't fail if unreachable


def cmd_test(args):
    """Test that a provider connection works end-to-end."""
    from jarviscore.nexus.providers import get_provider

    provider = args.provider.lower()
    gateway_url = _gateway_url()
    if not gateway_url:
        print(_err("NEXUS_GATEWAY_URL is not set."))
        sys.exit(1)

    catalog_entry = get_provider(provider)
    label = (catalog_entry or {}).get("label", provider)
    print(_bold(f"\nTesting {label} connection...\n"))

    async def _test():
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from jarviscore.nexus.client import NexusClient
            client = NexusClient(gateway_url, api_key=_gateway_api_key())
            # Request a connection (this will open a browser for OAuth)
            user_id = args.user_id or "jarviscore-test"
            from jarviscore.nexus.providers import get_scopes
            scopes = get_scopes(provider)
            conn_id, auth_url = await client.request_connection(
                provider=provider,
                user_id=user_id,
                scopes=scopes,
                return_url=os.environ.get("NEXUS_RETURN_URL", "http://localhost:8000/oauth/callback"),
            )
            print(_ok(f"Gateway accepted connection request"))
            print(_info(f"  connection_id = {conn_id}"))
            print(_info(f"  auth_url      = {auth_url}"))
            print()
            print("  Open the auth_url in your browser to complete the connection.")
            print("  Then run this command again with --connection-id to verify token resolution.")
            await client.close()
        except Exception as e:
            print(_err(f"Test failed: {e}"))
            sys.exit(1)

    asyncio.run(_test())


def _print_console_url(provider: str):
    """Print the developer console URL for a provider."""
    urls = {
        "github":    "  https://github.com/settings/developers",
        "slack":     "  https://api.slack.com/apps",
        "notion":    "  https://www.notion.so/my-integrations",
        "hubspot":   "  https://developers.hubspot.com/",
        "google_sheets": "  https://console.cloud.google.com/apis/credentials",
        "google_drive":  "  https://console.cloud.google.com/apis/credentials",
        "linear":    "  https://linear.app/settings/api",
        "stripe":    "  https://dashboard.stripe.com/apikeys",
        "airtable":  "  https://airtable.com/create/tokens",
        "brevo":     "  https://app.brevo.com/settings/keys/api",
        "mailchimp": "  https://mailchimp.com/developer/",
        "apollo":    "  https://app.apollo.io/#/settings/integrations/api",
    }
    if provider in urls:
        print(_info(f"  Developer console: {urls[provider]}"))


# ── Argument parser ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m jarviscore.cli nexus",
        description="Manage Nexus auth infrastructure for JarvisCore connected apps",
    )
    sub = p.add_subparsers(dest="subcommand")

    # init (first-time setup)
    sub.add_parser("init", help="First-time setup: generate keys, start stack (run this once)")

    # status
    sub.add_parser("status", help="Check Nexus Gateway and container status")

    # up
    sub.add_parser("up", help="Start local Nexus stack (run 'init' first if keys not set)")

    # register
    reg = sub.add_parser("register", help="Register a provider's credentials")
    reg.add_argument("provider", help="Provider name (github, slack, stripe, ...)")
    reg.add_argument("--client-id",     default=None, help="OAuth client ID (or username for basic_auth)")
    reg.add_argument("--client-secret", default=None, help="OAuth client secret (or password for basic_auth)")
    reg.add_argument("--api-key",       default=None, help="API key (for api_key providers)")
    reg.add_argument("--auth-type",     default=None,
                     choices=["oauth2", "api_key", "basic_auth"],
                     help="Auth type — required for providers not preconfigured in the catalog")
    reg.add_argument("--header-name",   default=None,
                     help="Header carrying the credential, e.g. X-API-KEY or PRIVATE-TOKEN")
    reg.add_argument("--value-prefix",  default=None,
                     help="Scheme word before the credential, e.g. 'Bearer ' or 'SSWS '")
    reg.add_argument("--param-name",    default=None,
                     help="Query parameter carrying the credential, e.g. token_auth")
    reg.add_argument("--credential-field", default=None,
                     help="Credential field to send when it is not the default for the auth type")

    # list
    sub.add_parser("list", help="List registered providers")

    # test
    tst = sub.add_parser("test", help="Test a provider connection end-to-end")
    tst.add_argument("provider", help="Provider name to test")
    tst.add_argument("--user-id", default=None, help="User ID for the test connection")

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        print()
        print(_bold("Quick start (first time):"))
        print("  jarviscore nexus init                           # generates keys + starts Docker")
        print("  jarviscore nexus register github \\")
        print("      --client-id=YOUR_ID --client-secret=YOUR_SECRET")
        print("  jarviscore nexus test github                    # opens browser OAuth")
        print()
        print(_bold("Day-to-day:"))
        print("  jarviscore nexus status                         # check stack health")
        print("  jarviscore nexus list                           # see registered providers")
        print()
        sys.exit(0)

    dispatch = {
        "init":     cmd_init,
        "status":   cmd_status,
        "up":       cmd_up,
        "register": cmd_register,
        "list":     cmd_list,
        "test":     cmd_test,
    }
    dispatch[args.subcommand](args)


if __name__ == "__main__":
    main()
