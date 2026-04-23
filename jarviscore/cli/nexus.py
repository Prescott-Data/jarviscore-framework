"""
jarviscore nexus — Developer setup tool for Nexus auth infrastructure.

Usage:
    python -m jarviscore.cli nexus status
    python -m jarviscore.cli nexus up
    python -m jarviscore.cli nexus register github --client-id=GH_ID --client-secret=GH_SECRET
    python -m jarviscore.cli nexus register stripe --api-key=sk_live_...
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
    """Find docker-compose.nexus.yml — ships with the framework package."""
    # When installed as a package, it lives next to the jarviscore/ directory
    pkg_root = Path(__file__).parent.parent.parent
    candidates = [
        pkg_root / "docker-compose.nexus.yml",
        Path.cwd() / "docker-compose.nexus.yml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # Return expected path even if missing


# ── Nexus Gateway URL ─────────────────────────────────────────────────────────

def _gateway_url() -> Optional[str]:
    """Read NEXUS_GATEWAY_URL from env or .env file."""
    url = os.environ.get("NEXUS_GATEWAY_URL", "")
    if url:
        return url
    env_file = Path.cwd() / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("NEXUS_GATEWAY_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_status(args):
    """Check gateway reachability + local Docker state."""
    print(_bold("\nJarvisCore — Nexus Status\n"))

    # 1. Gateway URL
    url = _gateway_url()
    if not url:
        print(_warn("NEXUS_GATEWAY_URL not set in your .env"))
        print(_info("  Set it to http://localhost:8090 for local dev, or your deployed Gateway URL"))
    else:
        print(_ok(f"NEXUS_GATEWAY_URL = {url}"))

        # 2. Ping the gateway
        import urllib.request, urllib.error
        try:
            req = urllib.request.urlopen(f"{url}/health", timeout=5)
            if req.status == 200:
                print(_ok("Gateway is reachable and healthy"))
            else:
                print(_warn(f"Gateway responded with HTTP {req.status}"))
        except Exception as e:
            print(_err(f"Gateway not reachable: {e}"))
            print(_info("  Run: python -m jarviscore.cli nexus up"))

    # 3. Docker container state
    if shutil.which("docker"):
        try:
            for name in ("nexus-broker", "nexus-gateway", "nexus-db"):
                out = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", name],
                    capture_output=True, text=True,
                )
                status = out.stdout.strip()
                if status == "running":
                    print(_ok(f"Container {name}: running"))
                elif status:
                    print(_warn(f"Container {name}: {status}"))
                else:
                    print(_err(f"Container {name}: not found (run 'nexus up')"))
        except Exception as e:
            print(_warn(f"Could not inspect Docker containers: {e}"))
    else:
        print(_warn("Docker not found — needed for local Nexus stack"))

    print()


def cmd_up(args):
    """Start local Nexus stack via Docker Compose."""
    print(_bold("\nStarting local Nexus stack...\n"))

    if not shutil.which("docker"):
        print(_err("Docker not found. Install Docker Desktop first."))
        print(_info("  https://www.docker.com/products/docker-desktop"))
        sys.exit(1)

    compose = _compose_file()
    if not compose.exists():
        print(_err(f"docker-compose.nexus.yml not found at {compose}"))
        sys.exit(1)

    print(_info(f"Compose file: {compose}"))
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose), "up", "-d", "--pull", "missing"],
        text=True,
    )

    if result.returncode == 0:
        print()
        print(_ok("Nexus stack is up!"))
        print()
        print("  Add this to your .env:")
        print()
        print("    NEXUS_GATEWAY_URL=http://localhost:8090")
        print("    NEXUS_RETURN_URL=http://localhost:8000/oauth/callback")
        print()
        print("  Then register your provider credentials:")
        print("    python -m jarviscore.cli nexus register github \\")
        print("        --client-id=YOUR_GH_CLIENT_ID \\")
        print("        --client-secret=YOUR_GH_CLIENT_SECRET")
        print()
    else:
        print(_err("Docker Compose failed. Check the output above."))
        sys.exit(1)


def cmd_register(args):
    """Register a provider's credentials — local store or gateway."""
    from jarviscore.nexus.providers import get_provider, get_auth_type, PROVIDER_CATALOG
    from jarviscore.nexus.store import get_store

    provider = args.provider.lower()
    catalog_entry = get_provider(provider)

    if not catalog_entry:
        known = ", ".join(sorted(PROVIDER_CATALOG.keys()))
        print(_err(f"Unknown provider: {provider!r}"))
        print(_info(f"Known providers: {known}"))
        sys.exit(1)

    auth_type = get_auth_type(provider)
    label = catalog_entry.get("label", provider)

    # Build credentials dict based on auth type
    if auth_type == "oauth2":
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
        api_key = args.api_key or args.client_id
        if not api_key:
            print(_err(f"{label} requires --api-key"))
            _print_console_url(provider)
            sys.exit(1)
        credentials = {"auth_type": "api_key", "api_key": api_key}
    elif auth_type == "basic_auth":
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

    gateway_url = _gateway_url()

    if gateway_url:
        # ── Gateway mode: POST to running Nexus Gateway ──────────────────────
        import urllib.request, urllib.error
        print(_bold(f"\nRegistering {label} ({auth_type}) with Nexus Gateway...\n"))
        try:
            payload = json.dumps({"provider": provider, **credentials}).encode()
            req = urllib.request.Request(
                f"{gateway_url}/v1/register-provider",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            body = json.loads(resp.read())
            print(_ok(f"{label} registered with gateway"))
            print(_info(f"  Provider ID: {body.get('provider_id', provider)}"))
        except urllib.error.HTTPError as e:
            print(_err(f"Gateway registration failed (HTTP {e.code}): {e.read().decode()}"))
            sys.exit(1)
        except Exception as e:
            print(_warn(f"Gateway unreachable ({e}) — falling back to local store"))
            _register_local(get_store(), provider, label, auth_type, credentials)
    else:
        # ── Local store mode: zero-dep encrypted file ─────────────────────────
        _register_local(get_store(), provider, label, auth_type, credentials)


def _register_local(store, provider, label, auth_type, credentials):
    """Write credentials to the local encrypted store."""
    store.register(provider, credentials)
    print(_bold(f"\nRegistering {label} ({auth_type})...\n"))
    print(_ok(f"{label} registered in local credential store"))
    print(_info(f"  Stored at: {store._path}"))
    print(_info( "  Credentials are AES-256-GCM encrypted at rest"))
    print()
    print(f"  Agents can now call {label} APIs via nexus_call() — no further setup needed.")
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
            req = urllib.request.urlopen(f"{gateway_url}/v1/providers", timeout=5)
            providers = json.loads(req.read())
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
            client = NexusClient(gateway_url)
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

    # status
    sub.add_parser("status", help="Check Nexus Gateway and container status")

    # up
    sub.add_parser("up", help="Start local Nexus stack (Docker Compose)")

    # register
    reg = sub.add_parser("register", help="Register a provider's credentials")
    reg.add_argument("provider", help="Provider name (github, slack, stripe, ...)")
    reg.add_argument("--client-id",     default=None, help="OAuth client ID (or username for basic_auth)")
    reg.add_argument("--client-secret", default=None, help="OAuth client secret (or password for basic_auth)")
    reg.add_argument("--api-key",       default=None, help="API key (for api_key providers)")

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
        print(_bold("Quick start:"))
        print("  python -m jarviscore.cli nexus up")
        print("  python -m jarviscore.cli nexus register github \\")
        print("      --client-id=YOUR_ID --client-secret=YOUR_SECRET")
        print("  python -m jarviscore.cli nexus status")
        print()
        sys.exit(0)

    dispatch = {
        "status":   cmd_status,
        "up":       cmd_up,
        "register": cmd_register,
        "list":     cmd_list,
        "test":     cmd_test,
    }
    dispatch[args.subcommand](args)


if __name__ == "__main__":
    main()
