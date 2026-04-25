#!/usr/bin/env python3
"""
nexus/seeds/seed_local.py
==========================
Seed the local Nexus Broker database with OAuth provider credentials
from the JarvisCore NexusLocalStore (the encrypted local credential store).

Run this ONCE after `docker compose -f docker-compose.nexus.yml up -d`
and before running any agent workflows.

Usage:
    cd jarviscore-framework
    python nexus/seeds/seed_local.py [--user-id YOUR_USER_ID]

    # Or with explicit connection string:
    DATABASE_URL="postgresql://nexus:nexus@localhost:5432/nexus?sslmode=disable" \\
    python nexus/seeds/seed_local.py --user-id muyukani

What this does:
  1. Reads provider credentials from ~/.jarviscore/nexus.enc (the local store).
  2. Creates a workspace UUID for the given user_id (deterministic UUID5).
  3. Creates the workspace in the broker DB (idempotent).
  4. Upserts provider_profiles for each registered OAuth2 provider.

After running this script, run `request_connection()` in the Sky agents
to generate OAuth consent URLs and complete the handshake.
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

from jarviscore.nexus.store import NexusLocalStore


PROVIDER_URLS = {
    "linkedin": {
        "auth_url": "https://www.linkedin.com/oauth/v2/authorization",
        "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
        "user_info_endpoint": "https://api.linkedin.com/v2/userinfo",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "user_info_endpoint": "https://api.github.com/user",
    },
    "slack": {
        "auth_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "user_info_endpoint": "https://slack.com/api/users.identity",
    },
    "gmail": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "user_info_endpoint": "https://www.googleapis.com/oauth2/v3/userinfo",
        "issuer": "https://accounts.google.com",
    },
    "hubspot": {
        "auth_url": "https://app.hubspot.com/oauth/authorize",
        "token_url": "https://api.hubapi.com/oauth/v1/token",
        "user_info_endpoint": "https://api.hubapi.com/oauth/v1/access-tokens/{token}",
    },
    "notion": {
        "auth_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "user_info_endpoint": "https://api.notion.com/v1/users/me",
    },
}


def user_to_workspace_id(user_id: str) -> str:
    """Convert user_id (arbitrary string or UUID) to a deterministic UUID."""
    try:
        uuid.UUID(user_id)
        return user_id
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, user_id))


def seed(user_id: str, db_url: str) -> None:
    workspace_id = user_to_workspace_id(user_id)
    print(f"📦 Seeding workspace for user_id={user_id!r}")
    print(f"   workspace_id: {workspace_id}")
    print(f"   database:     {db_url.split('@')[-1]}")
    print()

    store = NexusLocalStore()
    registered = store.list()
    if not registered:
        print("⚠️  No providers in NexusLocalStore. Run `nexus register <provider>` first.")
        return

    print(f"📋 Providers in local store: {', '.join(registered)}")
    print()

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 1. Create workspace (idempotent)
        cur.execute(
            """
            INSERT INTO workspaces (id, name)
            VALUES (%s, %s)
            ON CONFLICT (id) DO NOTHING;
            """,
            (workspace_id, f"{user_id}-workspace"),
        )
        print(f"✅ Workspace: {user_id}-workspace ({workspace_id})")

        # 2. Upsert provider profiles
        for provider_name in registered:
            creds = store.get(provider_name)
            if not creds:
                continue
            if creds.get("auth_type") != "oauth2":
                print(f"⏭  Skipping {provider_name} (auth_type={creds.get('auth_type')}) — not OAuth2")
                continue

            urls = PROVIDER_URLS.get(provider_name, {})
            scopes = creds.get("scopes") or []

            cur.execute(
                """
                INSERT INTO provider_profiles
                    (workspace_id, name, auth_type, client_id, client_secret,
                     auth_url, token_url, user_info_endpoint, scopes, pkce_enabled, issuer)
                VALUES (%s, %s, 'oauth2', %s, %s, %s, %s, %s, %s, true, %s)
                ON CONFLICT (workspace_id, name) DO UPDATE SET
                    client_id           = EXCLUDED.client_id,
                    client_secret       = EXCLUDED.client_secret,
                    auth_url            = EXCLUDED.auth_url,
                    token_url           = EXCLUDED.token_url,
                    user_info_endpoint  = EXCLUDED.user_info_endpoint,
                    scopes              = EXCLUDED.scopes,
                    updated_at          = NOW();
                """,
                (
                    workspace_id,
                    provider_name,
                    creds.get("client_id", ""),
                    creds.get("client_secret", ""),
                    urls.get("auth_url", ""),
                    urls.get("token_url", ""),
                    urls.get("user_info_endpoint", ""),
                    scopes,
                    urls.get("issuer"),
                ),
            )
            print(f"✅ {provider_name}: client_id={creds.get('client_id','?')[:8]}...")

        conn.commit()
        print()
        print("🎉 Done. Run request_connection() in your agents to start OAuth flows.")
        print(f"   User workspace ID: {workspace_id}")
        print("   (Pass this UUID as user_id to NexusClient.request_connection)")

    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed local Nexus broker DB")
    parser.add_argument(
        "--user-id",
        default=os.environ.get("NEXUS_USER_ID", "muyukani"),
        help="User ID (arbitrary string or UUID). Converted to stable UUID5 workspace. Default: muyukani",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL", "postgresql://nexus:nexus@localhost:5432/nexus?sslmode=disable"),
        help="Postgres connection URL",
    )
    args = parser.parse_args()
    seed(args.user_id, args.db_url)


if __name__ == "__main__":
    main()
