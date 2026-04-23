"""
Nexus Provider Catalog — Static auth requirements for every supported connected app.

This catalog is the authoritative source of truth for:
  - Which auth strategy type each provider uses (oauth2, api_key, basic_auth)
  - Which OAuth scopes to request during the Nexus handshake
  - Human-readable labels for the Connected Apps UI

Design rules:
  - All providers go through Nexus regardless of auth_type.
    "api_key" providers still go through Nexus — Nexus stores the key,
     applies it as X-Api-Key, and the key is never visible to agents.
  - Scopes must be minimal (principle of least privilege).
  - Add new providers here when onboarding, not in agent code.
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
            "https://www.googleapis.com/auth/gmail.labels",
        ],
    },
    "sendgrid": {
        "auth_type": "api_key",
        "label": "SendGrid",
        "category": "communication",
    },
    "brevo": {
        "auth_type": "api_key",
        "label": "Brevo (Sendinblue)",
        "category": "communication",
    },
    "mailchimp": {
        "auth_type": "api_key",
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
    },

    # ── Finance & Payments ───────────────────────────────────────────────────
    "stripe": {
        "auth_type": "api_key",
        "label": "Stripe",
        "category": "finance",
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
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Lookup helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_provider(name: str) -> Optional[Dict[str, Any]]:
    """Return catalog entry for a provider name, or None if unknown."""
    return PROVIDER_CATALOG.get(name.lower().strip())


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


def list_providers(category: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """List all providers, optionally filtered by category."""
    if not category:
        return dict(PROVIDER_CATALOG)
    return {k: v for k, v in PROVIDER_CATALOG.items() if v.get("category") == category}
