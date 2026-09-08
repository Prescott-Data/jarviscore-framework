"""
Nexus Provider Catalog — known defaults for commonly connected apps.

This catalog is a convenience, not a gate. `jarviscore nexus register` accepts
any provider: pass --auth-type and, for API keys, where the key goes
(--header-name / --value-prefix / --param-name). Entries here save that typing
for providers already looked up, and command-line flags override them.

It records:
  - Which auth strategy type each known provider uses
  - Where that provider expects its credential (`auth_config`)
  - Which OAuth scopes to request during the Nexus handshake
  - Human-readable labels for the Connected Apps UI

Design rules:
  - All providers go through Nexus regardless of auth_type.
    "api_key" providers still go through Nexus — Nexus stores the key,
     applies it via `auth_config`, and the key is never visible to agents.
  - `auth_config` states WHERE the credential goes: header_name, value_prefix,
    credential_field, param_name. There is no standard location for an API key
    (Bearer, X-API-KEY, api-key and SSWS are all in use), so it is never guessed.
  - Scopes must be minimal (principle of least privilege).
  - Adding an entry here is optional; it is not required to use a provider.
"""

from typing import Dict, Any, Optional

# ─────────────────────────────────────────────────────────────────────────────
# Provider catalog
# ─────────────────────────────────────────────────────────────────────────────

PROVIDER_CATALOG: Dict[str, Dict[str, Any]] = {
    # ── Communications ──────────────────────────────────────────────────────
    "slack": {
        "auth_type": "oauth2",
        "label": "Slack",
        "category": "communication",
        "scopes": [
            "chat:write",
            "channels:read",
            "channels:history",
            "users:read",
            "files:write",
            "reactions:write",
        ],
    },
    "gmail": {
        "auth_type": "oauth2",
        "label": "Gmail",
        "category": "communication",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.labels",
        ],
    },
    "sendgrid": {
        "auth_type": "api_key",
        "label": "SendGrid",
        "category": "communication",
        "auth_config": {"header_name": "Authorization", "value_prefix": "Bearer "},
    },
    "brevo": {
        "auth_type": "api_key",
        "label": "Brevo (Sendinblue)",
        "category": "communication",
        "auth_config": {"header_name": "api-key"},
    },
    "mailchimp": {
        # Mailchimp authenticates as HTTP Basic with any username and the key
        # as the password; register it with --client-id=anystring.
        "auth_type": "basic_auth",
        "label": "Mailchimp",
        "category": "communication",
    },

    # ── Code & Dev ───────────────────────────────────────────────────────────
    "github": {
        "auth_type": "oauth2",
        "label": "GitHub",
        "category": "development",
        "scopes": [
            "repo",
            "read:org",
            "read:user",
            "workflow",
        ],
    },
    "bitbucket": {
        "auth_type": "oauth2",
        "label": "Bitbucket",
        "category": "development",
        "scopes": [
            "repository",
            "repository:write",
            "pullrequest",
            "pullrequest:write",
            "account",
        ],
    },
    "linear": {
        "auth_type": "oauth2",
        "label": "Linear",
        "category": "development",
        "scopes": ["read", "write", "issues:create"],
    },
    "jira": {
        "auth_type": "basic_auth",
        "label": "Jira",
        "category": "development",
    },

    # ── Productivity ─────────────────────────────────────────────────────────
    "notion": {
        "auth_type": "oauth2",
        "label": "Notion",
        "category": "productivity",
        "scopes": ["read_content", "update_content", "insert_content"],
    },
    "google_sheets": {
        "auth_type": "oauth2",
        "label": "Google Sheets",
        "category": "productivity",
        "scopes": [
            "https://www.googleapis.com/auth/spreadsheets",
        ],
    },
    "google_drive": {
        "auth_type": "oauth2",
        "label": "Google Drive",
        "category": "productivity",
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/drive.file",
        ],
    },
    "google_calendar": {
        "auth_type": "oauth2",
        "label": "Google Calendar",
        "category": "productivity",
        "scopes": [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/calendar.readonly",
        ],
    },
    "airtable": {
        "auth_type": "api_key",
        "label": "Airtable",
        "category": "productivity",
        "auth_config": {"header_name": "Authorization", "value_prefix": "Bearer "},
    },

    # ── Social & Content ─────────────────────────────────────────────────────
    "x": {
        "auth_type": "oauth2",
        "label": "X (Twitter)",
        "category": "social",
        "scopes": [
            "tweet.read",
            "tweet.write",
            "users.read",
            "offline.access",
        ],
    },
    "linkedin": {
        "auth_type": "oauth2",
        "label": "LinkedIn",
        "category": "social",
        "scopes": [
            "openid",
            "profile",
            "email",
            "w_member_social",
            "r_organization_social",
        ],
    },

    # ── CRM & Sales ──────────────────────────────────────────────────────────
    "hubspot": {
        "auth_type": "oauth2",
        "label": "HubSpot",
        "category": "crm",
        "scopes": [
            "crm.objects.contacts.read",
            "crm.objects.contacts.write",
            "crm.objects.deals.read",
            "crm.objects.deals.write",
            "crm.objects.companies.read",
        ],
    },
    "salesforce": {
        "auth_type": "oauth2",
        "label": "Salesforce",
        "category": "crm",
        "scopes": ["api", "refresh_token", "offline_access"],
    },
    "apollo": {
        "auth_type": "api_key",
        "label": "Apollo.io",
        "category": "crm",
        # Apollo carries the key in the JSON body, which no strategy places.
        # Left unset deliberately: registration fails loudly instead of sending
        # a header Apollo ignores and returning an opaque 401.
    },

    # ── Finance & Payments ───────────────────────────────────────────────────
    "stripe": {
        "auth_type": "api_key",
        "label": "Stripe",
        "category": "finance",
        "auth_config": {"header_name": "Authorization", "value_prefix": "Bearer "},
    },
    "quickbooks": {
        "auth_type": "oauth2",
        "label": "QuickBooks",
        "category": "finance",
        "scopes": ["com.intuit.quickbooks.accounting"],
    },

    # ── Search ───────────────────────────────────────────────────────────────
    "serper": {
        "auth_type": "api_key",
        "label": "Serper (Google Search)",
        "category": "search",
        "auth_config": {"header_name": "X-API-KEY"},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Lookup helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_provider(name: str) -> Optional[Dict[str, Any]]:
    """Return catalog entry for a provider name, or None if unknown."""
    return PROVIDER_CATALOG.get(name.lower().strip())


def display_name(provider_name: str) -> str:
    """The name a person knows the provider by.

    The catalogue carries one for the providers it describes. For the rest the
    key is the only name there is, so it is made readable rather than shown raw.
    """
    entry = get_provider(provider_name)
    if entry and entry.get("label"):
        return str(entry["label"])
    return provider_name.replace("_", " ").strip().title()


def broker_name(provider_name: str) -> str:
    """The provider name as the Nexus broker accepts it.

    JarvisCore names providers with underscores because that is what the atom
    directories and function prefixes use, and the broker requires lowercase
    letters, numbers and hyphens. Translating here keeps that seam out of
    everything else.
    """
    return provider_name.strip().lower().replace("_", "-")


def get_scopes(provider_name: str) -> list:
    """Return OAuth scopes for a provider. Empty list for API key / basic auth."""
    entry = get_provider(provider_name)
    if not entry:
        return []
    return entry.get("scopes", [])


def get_auth_type(provider_name: str) -> Optional[str]:
    """Return auth_type ('oauth2', 'api_key', 'basic_auth') or None if unknown."""
    entry = get_provider(provider_name)
    if not entry:
        return None
    return entry.get("auth_type")


def get_auth_config(provider_name: str) -> Dict[str, str]:
    """Return where this provider expects its credential. Empty when unstated."""
    entry = get_provider(provider_name)
    if not entry:
        return {}
    return dict(entry.get("auth_config", {}))


def list_providers(category: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """List all providers, optionally filtered by category."""
    if not category:
        return dict(PROVIDER_CATALOG)
    return {k: v for k, v in PROVIDER_CATALOG.items() if v.get("category") == category}
