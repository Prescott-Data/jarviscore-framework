"""
AuthenticationManager — Dual-mode auth resolution for the kernel execution pipeline.

Production mode: NexusClient → Nexus Gateway → DynamicStrategy
Development mode: Tokens from environment variables (no external deps)

The auth manager sits between the kernel and sandbox execution,
transparently resolving credentials before code runs.

Production OAuth flow:
1. request_connection() → auth_url returned by Nexus Gateway
2. CLIFlowHandler opens browser + prints URL for user
3. User completes OAuth consent in browser
4. Nexus Broker receives callback, encrypts tokens, connection → ACTIVE
5. Framework polls Gateway until ACTIVE, then resolves strategy
6. LifecycleMonitor runs in background for health + proactive refresh
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from jarviscore.nexus.client import NexusClient
from jarviscore.nexus.lifecycle import LifecycleMonitor
from jarviscore.nexus.models import DynamicStrategy
from jarviscore.auth.oauth_flow import OAuthFlowHandler, CLIFlowHandler

logger = logging.getLogger(__name__)


class AuthenticationManager:
    """
    Dual-mode auth resolution for the kernel execution pipeline.

    Development mode (default):
    - Reads tokens from env vars: {PROVIDER}_TOKEN (e.g. SHOPIFY_TOKEN)
    - No external dependencies or network calls
    - Returns DynamicStrategy with type="api_key"

    Production mode:
    - Uses NexusClient to connect to Nexus Gateway
    - Interactive OAuth flow: opens browser, polls for completion
    - Lifecycle monitoring for connection health + proactive refresh
    - Strategy caching with configurable TTL

    Custom flow handlers:
        manager = AuthenticationManager(config)
        manager.flow_handler = MySlackFlowHandler()  # sends URL via Slack DM
    """

    def __init__(self, config: Dict[str, Any]):
        self.mode = config.get("auth_mode", "development")
        self.user_id = config.get("nexus_default_user_id", "jarviscore-agent")
        self.cache_ttl = config.get("auth_strategy_cache_ttl", 300)
        self.auth_timeout = config.get("auth_flow_timeout", 300)
        self.auth_poll_interval = config.get("auth_poll_interval", 2.0)

        # The return_url for OAuth callbacks — must point to the dashboard,
        # NOT to the Nexus Broker. The Broker redirects here after consent.
        self.return_url = config.get(
            "nexus_return_url",
            "http://localhost:8000/oauth/callback"
        )

        # Pluggable OAuth flow handler (CLI by default)
        self.flow_handler: OAuthFlowHandler = CLIFlowHandler(
            open_browser=config.get("auth_open_browser", True)
        )

        # Production mode: initialize NexusClient
        self.nexus_client: Optional[NexusClient] = None
        self.lifecycle_monitor: Optional[LifecycleMonitor] = None
        if self.mode == "production":
            gateway_url = config.get("nexus_gateway_url")
            if not gateway_url:
                raise ValueError(
                    "nexus_gateway_url is required for production auth mode. "
                    "Set NEXUS_GATEWAY_URL in your .env or config."
                )
            self.nexus_client = NexusClient(gateway_url)
            self.lifecycle_monitor = LifecycleMonitor(self.nexus_client)

        # Connection and strategy caches
        self.connections: Dict[str, str] = {}  # provider → connection_id
        self._strategy_cache: Dict[str, Tuple[DynamicStrategy, float]] = {}

    async def authenticate(
        self,
        provider: str,
        user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> str:
        """
        Acquire a connection for a provider.

        Development mode: Returns a pseudo connection_id, token from env var.
        Production mode: Nexus handshake → connection_id (cached per provider).

        Returns:
            connection_id string (opaque handle — never store tokens directly)
        """
        # Return cached connection if available
        if provider in self.connections:
            return self.connections[provider]

        uid = user_id or self.user_id
        scopes = scopes or []

        if self.mode == "development":
            connection_id = f"dev_{provider}_{uid}"
            self.connections[provider] = connection_id

            # Cache a dev strategy from env var
            env_key = f"{provider.upper()}_TOKEN"
            token = os.environ.get(env_key, "")
            strategy = DynamicStrategy(
                type="api_key",
                credentials={"api_key": token},
            )
            self._strategy_cache[connection_id] = (strategy, time.time())
            return connection_id

        # Production mode — interactive OAuth flow via Nexus Gateway
        if not self.nexus_client:
            raise RuntimeError("NexusClient not initialized for production mode")

        connection_id, auth_url = await self.nexus_client.request_connection(
            provider=provider,
            user_id=uid,
            scopes=scopes,
            return_url=self.return_url,
        )

        # Present auth URL to user (opens browser / prints URL)
        await self.flow_handler.present_auth_url(auth_url, provider)

        # Wait for user to complete OAuth consent
        status = await self.flow_handler.wait_for_completion(
            connection_id=connection_id,
            check_status_fn=self.nexus_client.check_connection_status,
            timeout=self.auth_timeout,
            poll_interval=self.auth_poll_interval,
        )

        if status != "ACTIVE":
            raise RuntimeError(
                f"OAuth flow for {provider} did not complete: {status}. "
                f"Connection {connection_id} is not active."
            )

        self.connections[provider] = connection_id

        # Start lifecycle monitoring for ongoing health
        if self.lifecycle_monitor:
            await self.lifecycle_monitor.monitor_connection(connection_id)

        logger.info(f"Connection established for {provider}: {connection_id}")
        return connection_id

    async def resolve_strategy(self, connection_id: str) -> DynamicStrategy:
        """
        Resolve a DynamicStrategy for a connection, with caching.

        Checks cache first. If cache miss or expired, fetches from Nexus Gateway.
        """
        # Check cache
        if connection_id in self._strategy_cache:
            strategy, cached_at = self._strategy_cache[connection_id]
            if time.time() - cached_at < self.cache_ttl:
                if not strategy.is_expired():
                    return strategy

        # Cache miss or expired — fetch fresh
        if self.mode == "development":
            # Dev mode: recreate from env
            provider = connection_id.split("_")[1] if "_" in connection_id else "unknown"
            env_key = f"{provider.upper()}_TOKEN"
            token = os.environ.get(env_key, "")
            strategy = DynamicStrategy(
                type="api_key",
                credentials={"api_key": token},
            )
        else:
            if not self.nexus_client:
                raise RuntimeError("NexusClient not initialized")
            strategy = await self.nexus_client.resolve_strategy(connection_id)

        self._strategy_cache[connection_id] = (strategy, time.time())
        return strategy

    async def resolve_auth_context(
        self,
        system: str,
        registry=None,
    ) -> Optional[Dict[str, Any]]:
        """
        Build auth_context dict for sandbox injection.

        Steps:
        1. Query registry for system auth requirements
        2. Authenticate with the required provider via Nexus
        3. Resolve strategy (cached with TTL)
        4. Return auth_context dict

        Returns:
            {"access_token": ..., "provider": ..., "strategy_type": ...}
            or None if system needs no auth.
        """
        if not registry:
            return None

        # Get auth requirements from registry
        try:
            requirements = registry.get_system_auth_requirements(system)
        except (AttributeError, Exception):
            return None

        if not requirements:
            return None

        provider = requirements.get("provider", system)
        scopes = requirements.get("scopes", [])

        # Authenticate via Nexus
        connection_id = await self.authenticate(provider, scopes=scopes)

        # Resolve strategy from Nexus Gateway
        strategy = await self.resolve_strategy(connection_id)

        # Build auth context for sandbox
        auth_context: Dict[str, Any] = {
            "provider": provider,
            "strategy_type": strategy.type,
        }

        # Extract the primary credential
        if strategy.type == "oauth2":
            auth_context["access_token"] = strategy.credentials.get("access_token", "")
        elif strategy.type == "api_key":
            auth_context["access_token"] = strategy.credentials.get("api_key", "")
        elif strategy.type == "basic_auth":
            auth_context["username"] = strategy.credentials.get("username", "")
            auth_context["password"] = strategy.credentials.get("password", "")

        return auth_context

    async def make_authenticated_request(
        self,
        provider: str,
        method: str,
        url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make an HTTP request with auth headers applied via Nexus strategy.

        Auto-retries once on 401: invalidates strategy cache, forces a fresh
        token fetch from Nexus Gateway, then retries the request.
        """
        connection_id = await self.authenticate(provider)
        strategy = await self.resolve_strategy(connection_id)

        request_kwargs = NexusClient.apply_strategy_to_request(
            strategy, method, url, **kwargs
        )

        async with httpx.AsyncClient() as client:
            response = await client.request(**request_kwargs)

            # Auto-retry on 401 — token may have been revoked/expired
            if response.status_code == 401:
                logger.info(f"Got 401 for {provider}, refreshing via Nexus Gateway...")
                # Force refresh via Gateway
                try:
                    await self.nexus_client.refresh_connection(connection_id)
                except Exception as e:
                    logger.warning(f"Refresh request failed: {e}")
                # Invalidate cache and re-resolve
                self._strategy_cache.pop(connection_id, None)
                strategy = await self.resolve_strategy(connection_id)
                request_kwargs = NexusClient.apply_strategy_to_request(
                    strategy, method, url, **kwargs
                )
                response = await client.request(**request_kwargs)

            return {
                "status_code": response.status_code,
                "body": response.text,
                "headers": dict(response.headers),
            }

    async def close(self):
        """Cleanup: stop lifecycle monitor, close Nexus client."""
        if self.lifecycle_monitor:
            await self.lifecycle_monitor.stop_all()
        if self.nexus_client:
            await self.nexus_client.close()
