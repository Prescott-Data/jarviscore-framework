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
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

_DATA = Path(__file__).parent / "_data" / "provider_hosts.json"

# Fields that carry the customer's own base URL for tenant-hosted providers.
_TENANT_URL_FIELDS = (
    "instance_url", "odoo_url", "base_url", "domain", "site_url", "account_url",
)


class HostNotAllowed(RuntimeError):
    """A credential was about to be sent somewhere the provider does not own."""


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


def allowed_hosts(
    provider: str, entry: Optional[Dict[str, Any]] = None
) -> Tuple[str, ...]:
    """Host patterns this provider may be called on. '{}' matches one label."""
    known = _catalogue().get((provider or "").lower(), ())
    return known + _tenant_hosts(entry)


def _matches(host: str, pattern: str) -> bool:
    if "{}" not in pattern:
        return host == pattern
    # "{}.agilecrm.com" binds the registrable part while leaving the tenant open.
    literal = pattern.split("{}")
    if not host.endswith(literal[-1]) or len(host) <= len(literal[-1]):
        return False
    return all(part in host for part in literal if part)


def ensure_host_allowed(
    provider: str, url: str, entry: Optional[Dict[str, Any]] = None
) -> None:
    """Raise unless `url`'s host belongs to `provider`.

    Refuses rather than warns: a credential sent to the wrong host has already
    left the boundary by the time anyone reads a warning.
    """
    host = (urlparse(url).hostname or "").lower()
    if not host:
        raise HostNotAllowed(f"{url!r} has no host to check against {provider!r}")

    patterns = allowed_hosts(provider, entry)
    if not patterns:
        raise HostNotAllowed(
            f"No API hosts are known for provider {provider!r}, so its credential "
            f"cannot be sent anywhere safely. If this provider is hosted on your "
            f"own domain, record it on the connection (for example instance_url) "
            f"so calls to it can be recognised."
        )
    if any(_matches(host, pattern) for pattern in patterns):
        return

    raise HostNotAllowed(
        f"{provider!r} credentials may not be sent to {host!r}. "
        f"{provider!r} is called on: {', '.join(patterns)}. "
        f"Use the host that belongs to the provider whose credential this is, or "
        f"run this call against the provider that actually owns {host!r}."
    )
