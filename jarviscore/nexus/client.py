"""
6H.2: NexusClient — HTTP client for Dromos Gateway REST API.

Handles both control plane (connection management) and data plane
(token retrieval, strategy resolution) operations.
"""

import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .models import ConnectionRequest, DynamicStrategy

logger = logging.getLogger(__name__)


class NexusClient:
    """
    HTTP client for the Dromos Gateway.

    Control Plane:
    - request_connection(): Initiate OAuth/auth flow
    - check_connection_status(): Poll connection state

    Data Plane:
    - get_token(): Retrieve current token payload
    - resolve_strategy(): Parse token into DynamicStrategy

    Strategy Application:
    - apply_strategy_to_request(): Inject auth headers into HTTP requests
    """

    def __init__(self, gateway_url: str, timeout: float = 30.0):
        self.gateway_url = gateway_url.rstrip("/")
        self.client = httpx.AsyncClient(
            base_url=self.gateway_url,
            timeout=timeout,
        )

    # ── Control Plane ─────────────────────────────────────────────

    async def request_connection(
        self,
        provider: str,
        user_id: str,
        scopes: List[str],
        return_url: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Initiate a connection via Dromos Gateway.

        POST /v1/request-connection

        Returns:
            (connection_id, auth_url) tuple
        """
        payload = ConnectionRequest(
            user_id=user_id,
            provider_name=provider,
            scopes=scopes,
            return_url=return_url or "http://localhost:8080/callback",
        ).model_dump()

        response = await self.client.post("/v1/request-connection", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["connection_id"], data["auth_url"]

    async def check_connection_status(self, connection_id: str) -> str:
        """
        Check status of a connection.

        GET /v1/check-connection/{connection_id}

        Returns:
            Status string: PENDING, ACTIVE, ATTENTION, REVOKED, EXPIRED, FAILED
        """
        response = await self.client.get(
            f"/v1/check-connection/{connection_id}"
        )
        response.raise_for_status()
        data = response.json()
        return data["status"]

    # ── Data Plane ────────────────────────────────────────────────

    async def get_token(self, connection_id: str) -> Dict[str, Any]:
        """
        Retrieve current token payload for a connection.

        GET /v1/token/{connection_id}

        Returns:
            Token payload dict with access_token, refresh_token, etc.
        """
        response = await self.client.get(f"/v1/token/{connection_id}")
        response.raise_for_status()
        return response.json()

    async def resolve_strategy(self, connection_id: str) -> DynamicStrategy:
        """
        Resolve a connection into a DynamicStrategy.

        Fetches the token and parses it into the appropriate strategy type.
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
        ready for httpx/requests.
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
