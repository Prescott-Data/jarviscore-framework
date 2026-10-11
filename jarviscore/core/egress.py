"""Where the agents' web traffic leaves from.

JarvisCore supplies no IP addresses. A developer who needs a reputable,
stable or regional exit names their own proxy provider in
``EGRESS_PROXY_URL``; the browser and the pages the researcher reads leave
through it. Search-provider APIs are called directly: they authenticate by
key, not by the reputation of the calling IP.

``{session}`` anywhere in the URL (usually the username, where providers
read sticky-session ids) is replaced with a stable 16-character id, so one
tenant or workflow keeps one exit IP. Logins and checkouts break when the
IP changes underneath them.
"""

from __future__ import annotations

import hashlib
import ipaddress
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

SESSION_PLACEHOLDER = "{session}"


@dataclass(frozen=True)
class Egress:
    """A developer's proxy, as each HTTP stack in the framework needs it."""

    url: str
    bypass: str | None = None

    def __post_init__(self) -> None:
        parts = urlsplit(self.url.replace(SESSION_PLACEHOLDER, "0"))
        # Messages name the scheme only; the URL carries the provider password.
        if parts.scheme not in ("http", "https"):
            raise ValueError(
                f"EGRESS_PROXY_URL must be an http:// or https:// proxy, not {parts.scheme or 'no scheme'}://"
            )
        try:
            port = parts.port
        except ValueError as exc:
            raise ValueError("EGRESS_PROXY_URL has an invalid port") from exc
        if not parts.hostname or port is None:
            raise ValueError("EGRESS_PROXY_URL must name the proxy host and port")

    @property
    def sticky(self) -> bool:
        return SESSION_PLACEHOLDER in self.url

    def _resolved(self, session: str | None):
        url = self.url
        if self.sticky:
            token = hashlib.sha256(session.encode()).hexdigest()[:16] if session else uuid.uuid4().hex[:16]
            url = url.replace(SESSION_PLACEHOLDER, token)
        return urlsplit(url)

    def applies_to(self, url: str) -> bool:
        """Whether ``url`` leaves through the proxy (loopback and bypassed hosts do not)."""
        host = (urlsplit(url).hostname or "").lower()
        if host == "localhost":
            return False
        try:
            if ipaddress.ip_address(host).is_loopback:
                return False
        except ValueError:
            pass
        for rule in (self.bypass or "").split(","):
            rule = rule.strip().lower()
            if not rule:
                continue
            if rule.startswith("*."):
                rule = rule[1:]
            if rule.startswith("."):
                if host.endswith(rule) or host == rule[1:]:
                    return False
            elif host == rule:
                return False
        return True

    def playwright(self, session: str | None = None) -> dict[str, Any]:
        """Playwright's ``proxy`` launch option."""
        parts = self._resolved(session)
        proxy: dict[str, Any] = {"server": f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"}
        if parts.username:
            proxy["username"] = unquote(parts.username)
        if parts.password is not None:
            proxy["password"] = unquote(parts.password)
        if self.bypass:
            proxy["bypass"] = self.bypass
        return proxy

    def http_proxy(self, url: str, session: str | None = None) -> str | None:
        """The aiohttp ``proxy`` for a request to ``url``, or None when it goes direct."""
        return self._resolved(session).geturl() if self.applies_to(url) else None

    def redacted(self) -> str:
        parts = urlsplit(self.url)
        return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def configured_egress(config: Mapping[str, Any] | None = None) -> Egress | None:
    """The configured egress proxy, or None when traffic leaves directly."""
    from jarviscore.config import settings

    resolved = {
        "egress_proxy_url": settings.egress_proxy_url,
        "egress_proxy_bypass": settings.egress_proxy_bypass,
    }
    resolved.update({k: v for k, v in (config or {}).items() if k in resolved})
    url = str(resolved["egress_proxy_url"] or "").strip()
    if not url:
        return None
    return Egress(url=url, bypass=str(resolved["egress_proxy_bypass"] or "").strip() or None)
