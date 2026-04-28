"""
NexusClient — HTTP client for the Nexus Gateway REST API.

JarvisCore's Python integration with the Nexus Framework.

The Nexus Framework provides provider-agnostic, secure OAuth 2.0 / OIDC
connection management. JarvisCore communicates exclusively with the
Nexus Gateway — never with the Broker or any provider directly.

Control Plane (connection lifecycle):
- request_connection(): Initiate OAuth/auth flow → returns (connection_id, auth_url)
- check_connection_status(): Poll PENDING → ACTIVE | ATTENTION | FAILED
- refresh_connection(): Force a token refresh via the Gateway

Data Plane (runtime token usage):
- get_token(): Retrieve the current credential payload
- resolve_strategy(): Parse payload into DynamicStrategy for header injection

Strategy Application:
- apply_strategy_to_request(): Inject auth headers into outgoing HTTP requests

IMPORTANT — user_id must be a UUID:
    The Nexus Gateway uses user_id as the workspace_id in broker calls.
    If you pass a non-UUID string (e.g. "alice"), it is automatically
    converted to a deterministic UUID5 derived from the string.
    Use the same user_id string consistently — it always maps to the same UUID.
"""

import base64
import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .models import ConnectionRequest, DynamicStrategy

logger = logging.getLogger(__name__)


class NexusClient:
    """
    HTTP client for the Nexus Gateway.

    Agents NEVER talk to providers or the Broker directly.
    All auth flows and token retrieval go through the Gateway.

    Instantiate with the NEXUS_GATEWAY_URL from settings:
        client = NexusClient(gateway_url=settings.nexus_gateway_url)
    """

    def __init__(self, gateway_url: str, timeout: float = 30.0):
        self.gateway_url = gateway_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.gateway_url,
            timeout=timeout,
        )

    # ── Control Plane ─────────────────────────────────────────────

    @staticmethod
    def _ensure_uuid(user_id: str) -> str:
        """
        Ensure user_id is a valid UUID string.

        The Nexus Gateway uses user_id as workspace_id in broker calls,
        which requires a UUID. If a non-UUID string is passed (e.g. "alice"),
        it is converted to a deterministic UUID5 so the same string always
        maps to the same workspace.
        """
        try:
            _uuid.UUID(user_id)   # already a valid UUID
            return user_id
        except ValueError:
            # Derive a stable UUID5 from the string
            stable = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, user_id))
            logger.debug(
                "[NexusClient] user_id %r is not a UUID — using deterministic UUID5: %s",
                user_id, stable,
            )
            return stable

    async def request_connection(
        self,
        provider: str,
        user_id: str,
        scopes: List[str],
        return_url: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Initiate a connection via Nexus Gateway.

        POST /v1/request-connection

        The return_url must point to the dashboard OAuth callback endpoint
        (e.g. http://localhost:8000/oauth/callback) so the Broker can
        redirect the user back after consent. Never use the Broker port (8080)
        as a return_url.

        user_id — can be any string (e.g. "alice") or a UUID. Non-UUID
        strings are automatically converted to a deterministic UUID5 so they
        are consistent across calls. The Gateway uses user_id as workspace_id
        in broker calls.

        Returns:
            (connection_id, auth_url) tuple.
            Store the connection_id; never store tokens.

        Raises:
            ValueError if return_url is not set.
            httpx.HTTPStatusError on unexpected errors (not 200 or 409).
        """
        if return_url is None:
            raise ValueError(
                "return_url is required. Set it to your dashboard OAuth callback: "
                "e.g. 'http://localhost:8000/oauth/callback'. "
                "Do NOT default to the Broker port."
            )

        payload = ConnectionRequest(
            user_id=self._ensure_uuid(user_id),
            provider_name=provider,
            scopes=scopes,
            return_url=return_url,
        ).model_dump()

        response = await self.client.post("/v1/request-connection", json=payload)

        if response.status_code == 409:
            # Existing pending connection — extract auth_url from response if present
            data = response.json()
            auth_url = data.get("authUrl") or data.get("auth_url") or data.get("redirect_url")
            conn_id = data.get("connection_id") or data.get("connectionId")
            if auth_url and conn_id:
                logger.info(
                    "[NexusClient] Existing pending connection for provider=%s conn_id=%s",
                    provider, conn_id,
                )
                return conn_id, auth_url
            # If 409 doesn't include a reusable auth URL, re-raise as an error
            response.raise_for_status()

        response.raise_for_status()
        data = response.json()
        return data["connection_id"], data["authUrl"]

    async def check_connection_status(self, connection_id: str) -> str:
        """
        Check status of a connection.

        GET /v1/check-connection/{connection_id}

        Returns:
            Status string: PENDING | ACTIVE | ATTENTION | REVOKED | EXPIRED | FAILED

        ATTENTION means the user must re-authenticate (e.g. token revoked by provider).
        REVOKED / EXPIRED / FAILED are terminal — stop polling.
        """
        response = await self.client.get(
            f"/v1/check-connection/{connection_id}"
        )
        response.raise_for_status()
        data = response.json()
        return data["status"].upper()

    async def refresh_connection(self, connection_id: str) -> None:
        """
        Force a proactive token refresh via Nexus Gateway.

        POST /v1/refresh/{connection_id}

        The Gateway proxies this to the Broker's refresh endpoint using its
        internal API key — agents never need the Broker API key.

        Raises httpx.HTTPStatusError on failure (e.g. 409 ATTENTION_REQUIRED
        means the user must re-consent via a new handshake).
        """
        response = await self.client.post(f"/v1/refresh/{connection_id}")
        response.raise_for_status()
        logger.info(f"Token refreshed for connection {connection_id}")

    # ── Data Plane ────────────────────────────────────────────────

    async def get_token(self, connection_id: str) -> Dict[str, Any]:
        """
        Retrieve the current credential payload for a connection.

        GET /v1/token/{connection_id}

        Returns a generic strategy payload — inspect the 'strategy.type' field:
            {"strategy": {"type": "oauth2"}, "credentials": {"access_token": "..."}, ...}
            {"strategy": {"type": "api_key"}, "credentials": {"api_key": "..."}, ...}
            {"strategy": {"type": "basic_auth"}, "credentials": {"username": ..., "password": ...}, ...}

        Agents store only the connection_id. Tokens are fetched on demand.
        """
        response = await self.client.get(f"/v1/token/{connection_id}")
        response.raise_for_status()
        return response.json()

    async def resolve_strategy(self, connection_id: str) -> DynamicStrategy:
        """
        Resolve a connection into a DynamicStrategy.

        Fetches the token payload and parses it into the appropriate strategy.
        Use apply_strategy_to_request() to inject auth headers.
        """
        token_data = await self.get_token(connection_id)
        return DynamicStrategy(
            type=token_data.get("type", "oauth2"),
            credentials=token_data.get("credentials", {}),
            expires_at=token_data.get("expires_at"),
        )

    # ── Strategy Application ──────────────────────────────────────

    @staticmethod
    def apply_strategy_to_request(
        strategy: DynamicStrategy,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Apply auth headers to an HTTP request based on strategy type.

        Returns a dict with method, url, headers, and any extra kwargs
        suitable for httpx/requests:
            request_kwargs = NexusClient.apply_strategy_to_request(strategy, "GET", url)
            async with httpx.AsyncClient() as c:
                resp = await c.request(**request_kwargs)
        """
        headers = dict(headers) if headers else {}

        if strategy.type == "oauth2":
            token = strategy.credentials.get("access_token", "")
            headers["Authorization"] = f"Bearer {token}"
        elif strategy.type == "api_key":
            key = strategy.credentials.get("api_key", "")
            headers["X-Api-Key"] = key
        elif strategy.type == "basic_auth":
            username = strategy.credentials.get("username", "")
            password = strategy.credentials.get("password", "")
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        return {"method": method, "url": url, "headers": headers, **kwargs}

    # ── Lifecycle ─────────────────────────────────────────────────

    async def close(self):
        """Close the underlying HTTP client."""
        await self.client.aclose()
