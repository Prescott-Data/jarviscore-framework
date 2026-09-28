"""Which hosts a provider's credential may be sent to.

A credential is bound to the task, not to the destination, everywhere else in
the call path: `nexus_call` attaches whatever the connection holds to whatever
URL the caller passes. That is how a HubSpot token reached slack.com. Since the
URL in generated code is chosen by a model, and a model can be wrong or misled,
the destination has to be checked against the provider rather than trusted.

Two honest sources answer "which hosts belong to this provider":

  1. The atom corpus. Every atom for a provider calls that provider, so the
     hosts in its source are authoritative. Derived by
     scripts/derive_provider_hosts.py into _data/provider_hosts.json.
  2. The connection itself, for providers whose host is the customer's own
     tenant (Salesforce instances, Odoo deployments). Nothing can be known about
     those in advance, but the domain is recorded when the connection is made.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

_DATA = Path(__file__).parent / "_data" / "provider_hosts.json"

# Fields that carry the customer's own base URL for tenant-hosted providers.
_TENANT_URL_FIELDS = (
    "instance_url",
    "odoo_url",
    "base_url",
    "api_base_url",
    "domain",
    "site_url",
    "account_url",
)
_ZENDESK_TENANT_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.zendesk\.com$")


class HostNotAllowed(RuntimeError):
    """A credential was about to be sent somewhere the provider does not own."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        requested_host: str = "",
        allowed: Tuple[str, ...] = (),
    ):
        super().__init__(message)
        self.provider = provider
        self.requested_host = requested_host
        self.allowed = allowed


@lru_cache(maxsize=1)
def _catalogue() -> Dict[str, Tuple[str, ...]]:
    if not _DATA.exists():
        return {}
    raw = json.loads(_DATA.read_text())
    return {provider: tuple(hosts) for provider, hosts in raw.items()}


def _tenant_hosts(entry: Optional[Dict[str, Any]]) -> Tuple[str, ...]:
    if not entry:
        return ()
    hosts = []
    for field in _TENANT_URL_FIELDS:
        value = entry.get(field)
        if not value or not isinstance(value, str):
            continue
        candidate = value if "://" in value else f"https://{value}"
        host = (urlparse(candidate).hostname or "").lower()
        if host:
            hosts.append(host)
    return tuple(hosts)


def _zendesk_support_base_url(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    """Read the exact Zendesk Support API origin recorded on its connection."""
    if not entry:
        return None

    candidate = entry.get("api_base_url")
    if not candidate and entry.get("subdomain"):
        candidate = f"https://{entry['subdomain']}.zendesk.com/api/v2"
    if not isinstance(candidate, str) or not candidate.strip():
        return None

    try:
        parsed = urlparse(candidate.strip())
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.path.rstrip("/") != "/api/v2"
        or parsed.query
        or parsed.fragment
        or not _ZENDESK_TENANT_HOST.fullmatch(host)
    ):
        return None
    return f"https://{host}/api/v2"


def allowed_hosts(provider: str, entry: Optional[Dict[str, Any]] = None) -> Tuple[str, ...]:
    """Host patterns this provider may be called on. '{}' matches one label."""
    if (provider or "").lower() == "zendesk_support":
        base_url = _zendesk_support_base_url(entry)
        if not base_url:
            return ()
        return ((urlparse(base_url).hostname or ""),)
    known = _catalogue().get((provider or "").lower(), ())
    return known + _tenant_hosts(entry)


def resolve_provider_url(provider: str, url: str, entry: Optional[Dict[str, Any]] = None) -> str:
    """Resolve Zendesk's API-relative paths against its recorded tenant.

    The caller supplies only paths under ``/api/v2``. The host comes from the
    connected provider profile, never from model-selected request arguments.
    """
    if (provider or "").lower() != "zendesk_support":
        return url

    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        raise HostNotAllowed(
            "Zendesk Support calls require a path under /api/v2 or the exact "
            "connected tenant host.",
            provider=provider,
        )
    if parsed.netloc and not parsed.scheme:
        raise HostNotAllowed(
            "Zendesk Support calls require a path under /api/v2 or an absolute HTTPS URL.",
            provider=provider,
        )
    if parsed.scheme or parsed.netloc:
        return url

    path = unquote(parsed.path)
    path_parts = path.split("/")
    if (
        not path.startswith("/api/v2/")
        or url.startswith("//")
        or "\\" in url
        or parsed.fragment
        or any(part in {".", ".."} for part in path_parts)
    ):
        raise HostNotAllowed(
            "Zendesk Support calls require a normalized path under /api/v2.",
            provider=provider,
        )

    base_url = _zendesk_support_base_url(entry)
    if not base_url:
        raise HostNotAllowed(
            "No valid Zendesk Support tenant is recorded on this connection.",
            provider=provider,
        )
    host = urlparse(base_url).hostname
    return f"https://{host}{url}"


def _matches(host: str, pattern: str) -> bool:
    if "{}" not in pattern:
        return host == pattern
    # "{}.agilecrm.com" binds the registrable part while leaving the tenant open.
    literal = pattern.split("{}")
    if not host.endswith(literal[-1]) or len(host) <= len(literal[-1]):
        return False
    return all(part in host for part in literal if part)


def ensure_host_allowed(provider: str, url: str, entry: Optional[Dict[str, Any]] = None) -> None:
    """Raise unless `url`'s host belongs to `provider`.

    Refuses rather than warns: a credential sent to the wrong host has already
    left the boundary by the time anyone reads a warning.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        raise HostNotAllowed(
            f"{url!r} has no host to check against {provider!r}",
            provider=provider,
        )

    if (provider or "").lower() == "zendesk_support":
        parsed = urlparse(url)
        try:
            port = parsed.port
        except ValueError:
            port = -1
        paths = unquote(parsed.path).split("/")
        allowed = allowed_hosts(provider, entry)
        if not allowed:
            raise HostNotAllowed(
                "No valid Zendesk Support tenant host is recorded on this connection.",
                provider=provider,
                requested_host=host,
            )
        if (
            parsed.scheme.lower() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or host not in allowed
            or not parsed.path.startswith("/api/v2/")
            or "\\" in parsed.path
            or any(part in {".", ".."} for part in paths)
        ):
            raise HostNotAllowed(
                f"Zendesk Support credentials may only be sent over HTTPS to "
                f"the connected tenant API host {allowed[0]!r}.",
                provider=provider,
                requested_host=host,
                allowed=allowed,
            )
        return

    patterns = allowed_hosts(provider, entry)
    if not patterns:
        raise HostNotAllowed(
            f"No API hosts are known for provider {provider!r}, so its credential "
            f"cannot be sent anywhere safely. If this provider is hosted on your "
            f"own domain, record it on the connection (for example instance_url) "
            f"so calls to it can be recognised.",
            provider=provider,
            requested_host=host,
        )
    if any(_matches(host, pattern) for pattern in patterns):
        return

    raise HostNotAllowed(
        f"{provider!r} credentials may not be sent to {host!r}. "
        f"{provider!r} is called on: {', '.join(patterns)}. "
        f"Use the host that belongs to the provider whose credential this is, or "
        f"run this call against the provider that actually owns {host!r}.",
        provider=provider,
        requested_host=host,
        allowed=patterns,
    )
