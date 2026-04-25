-- Nexus Broker — Initial Database Schema
-- ========================================
-- This schema was reverse-engineered from the nexus-broker binary during
-- local dogfooding (April 2026). It is the authoritative init script for
-- the local development Nexus stack.
--
-- Apply with:
--   docker exec nexus-db psql -U nexus -d nexus -f /docker-entrypoint-initdb.d/001_initial_schema.sql
--
-- Or automatically via docker compose (mount this file into initdb.d).
--
-- Key design notes:
--   - workspace_id is used as the tenant identifier (user_id UUID → workspace_id)
--   - user_id in connections is TEXT and nullable (broker doesn't INSERT it via consent-spec)
--   - provider_profiles scoped per-workspace (not global)
--   - ALLOWED_RETURN_DOMAINS must be set on broker for localhost OAuth callbacks
--   - Gateway uses user_id as workspace_id in broker calls — must be a valid UUID

-- ── Workspaces ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspaces (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    deleted_at  TIMESTAMPTZ
);

-- ── Provider Profiles ─────────────────────────────────────────────────────────
-- One row per (workspace, provider). Client credentials stored encrypted at rest
-- by the broker using ENCRYPTION_KEY.
CREATE TABLE IF NOT EXISTS provider_profiles (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id                UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    name                        TEXT NOT NULL,
    display_name                TEXT,
    auth_type                   TEXT NOT NULL DEFAULT 'oauth2',
    client_id                   TEXT,
    client_secret               TEXT,
    auth_url                    TEXT,
    token_url                   TEXT,
    scopes                      TEXT[],
    extra_params                JSONB,
    -- OIDC / discovery fields
    issuer                      TEXT,
    enable_discovery            BOOLEAN DEFAULT false,
    userinfo_endpoint           TEXT,
    user_info_endpoint          TEXT,
    jwks_uri                    TEXT,
    pkce_enabled                BOOLEAN DEFAULT true,
    token_endpoint_auth_method  TEXT DEFAULT 'client_secret_post',
    -- Extended fields
    auth_header                 TEXT,
    request_token_url           TEXT,
    verify_url                  TEXT,
    access_token_url            TEXT,
    callback_url                TEXT,
    allowed_scopes              TEXT[],
    metadata                    JSONB,
    api_base_url                TEXT,
    logo_url                    TEXT,
    color                       TEXT,
    is_system                   BOOLEAN DEFAULT false,
    is_active                   BOOLEAN DEFAULT true,
    rate_limit_requests         INT,
    rate_limit_window_seconds   INT,
    params                      JSONB,
    headers                     JSONB,
    audience                    TEXT,
    resource                    TEXT,
    nonce_param                 TEXT,
    state_param                 TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ DEFAULT NOW(),
    deleted_at                  TIMESTAMPTZ,
    UNIQUE(workspace_id, name)
);

-- ── Connections ───────────────────────────────────────────────────────────────
-- One row per OAuth handshake. PENDING → ACTIVE after user consents.
-- NOTE: user_id is nullable — the broker's consent-spec INSERT does not include it.
CREATE TABLE IF NOT EXISTS connections (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider_id   UUID NOT NULL REFERENCES provider_profiles(id) ON DELETE CASCADE,
    user_id       TEXT,               -- nullable; set separately if needed
    status        TEXT NOT NULL DEFAULT 'PENDING',
    code_verifier TEXT,
    scopes        TEXT[],
    return_url    TEXT,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW(),
    deleted_at    TIMESTAMPTZ
);

-- ── Tokens ────────────────────────────────────────────────────────────────────
-- Encrypted OAuth tokens. One per connection. Never returned to agents.
CREATE TABLE IF NOT EXISTS tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id   UUID NOT NULL UNIQUE REFERENCES connections(id) ON DELETE CASCADE,
    encrypted_data  BYTEA NOT NULL,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ── Audit Events ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  UUID REFERENCES workspaces(id) ON DELETE CASCADE,
    event_type    TEXT NOT NULL,
    payload       JSONB,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── API Keys ──────────────────────────────────────────────────────────────────
-- Gateway→Broker authentication. key_hash = SHA256(raw_key) hex.
CREATE TABLE IF NOT EXISTS api_keys (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    key_hash      TEXT NOT NULL UNIQUE,
    name          TEXT,
    is_active     BOOLEAN DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    deleted_at    TIMESTAMPTZ
);
