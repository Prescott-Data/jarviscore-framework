"""
Applying a resolved Nexus strategy to an outgoing request.

This is the single place JarvisCore decides where a credential goes on a
request. Both the gateway path and the local-store path route through it, so
the two can never disagree about how a provider is authenticated.

Placement is data (`DynamicStrategy.config`), matching the Nexus broker's
strategy config, because it is a property of the provider rather than of the
auth type — `Bearer`, `SSWS`, `Zoho-oauthtoken` and `PRIVATE-TOKEN` are all
"an API key on a header" and only the provider knows which.
"""
from __future__ import annotations

import base64
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import DynamicStrategy


class StrategyError(RuntimeError):
    """A strategy cannot be applied — placement or credentials are missing."""


# RFC 6750: OAuth2 bearer placement is standardised, so it is a real default.
# Everything else must be stated by the provider profile.
_OAUTH2_DEFAULTS = {
    "header_name": "Authorization",
    "value_prefix": "Bearer ",
    "credential_field": "access_token",
}


def _credential(strategy: DynamicStrategy, field: str) -> str:
    value = strategy.credentials.get(field, "")
    if not value:
        if field == "access_token":
            raise StrategyError(
                "this connection has no access token. Registering a provider's app "
                "is not the same as connecting an account: OAuth2 needs a user to "
                "consent before a token exists. If the provider issues a static "
                "token instead, register it with --auth-type=api_key and the header "
                "it belongs on"
            )
        raise StrategyError(
            f"credential field {field!r} is missing or empty for this connection"
        )
    return value


def _with_query(url: str, name: str, value: str) -> str:
    parts = urlparse(url)
    query = parse_qsl(parts.query, keep_blank_values=True) + [(name, value)]
    return urlunparse(parts._replace(query=urlencode(query)))


def apply_strategy(
    strategy: DynamicStrategy,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Build request kwargs for httpx with the credential placed as the provider expects.

    Raises StrategyError when placement is unknown rather than guessing — a wrong
    header produces an opaque 401 at the provider, which is far harder to diagnose.
    """
    headers = dict(headers) if headers else {}
    config = strategy.config or {}

    if strategy.type == "basic_auth":
        username = _credential(strategy, config.get("username_field", "username"))
        password = _credential(strategy, config.get("password_field", "password"))
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"
        return {"method": method, "url": url, "headers": headers, **kwargs}

    if strategy.type == "query_param":
        param_name = config.get("param_name")
        if not param_name:
            raise StrategyError(
                "query_param strategy requires 'param_name' in the provider's "
                "strategy config — it names the query parameter carrying the credential"
            )
        field = config.get("credential_field", "api_key")
        url = _with_query(url, param_name, _credential(strategy, field))
        return {"method": method, "url": url, "headers": headers, **kwargs}

    if strategy.type == "oauth2":
        placement = {**_OAUTH2_DEFAULTS, **config}
    elif strategy.type == "header":
        placement = {
            "header_name": config.get("header_name", "Authorization"),
            "value_prefix": config.get("value_prefix", ""),
            "credential_field": config.get("credential_field", "api_key"),
        }
    elif strategy.type == "api_key":
        # No standard exists: X-Api-Key, Authorization: Bearer, Authorization: SSWS,
        # PRIVATE-TOKEN and ?api_key= are all in use across providers.
        if not config.get("header_name") and not config.get("param_name"):
            raise StrategyError(
                "api_key strategy has no placement configured. There is no standard "
                "location for an API key, so it must be stated per provider: set "
                "'header_name' (with optional 'value_prefix') or 'param_name' in the "
                "provider's strategy config."
            )
        if config.get("param_name"):
            field = config.get("credential_field", "api_key")
            url = _with_query(url, config["param_name"], _credential(strategy, field))
            return {"method": method, "url": url, "headers": headers, **kwargs}
        placement = {
            "header_name": config["header_name"],
            "value_prefix": config.get("value_prefix", ""),
            "credential_field": config.get("credential_field", "api_key"),
        }
    else:
        raise StrategyError(f"unsupported auth strategy type: {strategy.type!r}")

    credential = _credential(strategy, placement["credential_field"])
    headers[placement["header_name"]] = f"{placement['value_prefix']}{credential}"
    return {"method": method, "url": url, "headers": headers, **kwargs}


def unmet_requirement(strategy: Optional[DynamicStrategy]) -> Optional[str]:
    """Why this strategy could not authenticate a request, or None if it can.

    Answered by dry-running the real placement rather than restating its rules:
    a second opinion about which credentials suffice is a second opinion that
    can drift from the code that actually performs the call.
    """
    if strategy is None:
        return "no credentials are registered for this provider"
    try:
        apply_strategy(strategy, "GET", "https://example.invalid/")
    except StrategyError as exc:
        return str(exc)
    return None
