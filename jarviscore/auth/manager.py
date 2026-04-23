"""
AuthenticationManager — Nexus-gated credential resolution.

JarvisCore's single rule: ALL authentication goes through Nexus.
This applies universally to OAuth tokens, API keys, and basic auth passwords.
Agents never see credentials — only opaque connection_id handles.

Flow:
  1. authenticate(provider) → Nexus handshake → connection_id
  2. get_connection_id(provider) → returns cached connection_id
  3. NexusCallProxy.call(connection_id, ...) → resolves strategy internally
                                             → applies auth headers
                                             → returns HTTP response

Agents and generated code ONLY ever call nexus_call() (via CoderSandbox).
resolve_strategy() is intentionally package-private — used only by NexusCallProxy.

Production OAuth flow:
  1. request_connection() → auth_url returned by Nexus Gateway
  2. CLIFlowHandler / DashboardFlowHandler opens browser + presents URL
  3. User completes OAuth consent
  4. Nexus Broker receives callback, encrypts tokens, connection → ACTIVE
  5. Framework polls Gateway until ACTIVE
  6. LifecycleMonitor runs in background for health + proactive refresh
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from jarviscore.nexus.client import NexusClient
from jarviscore.nexus.lifecycle import LifecycleMonitor
from jarviscore.nexus.models import DynamicStrategy
from jarviscore.nexus.providers import get_scopes, get_provider
from jarviscore.auth.oauth_flow import OAuthFlowHandler, CLIFlowHandler

logger = logging.getLogger(__name__)


class AuthenticationManager:
    """
    Nexus-gated credential manager.

    All auth goes through Nexus regardless of strategy type:
      - oauth2      → full interactive OAuth consent flow via Nexus Gateway
      - api_key     → key stored in Nexus; applied transparently by NexusCallProxy
      - basic_auth  → credentials stored in Nexus; applied transparently by NexusCallProxy

    Public API (for agents + kernel):
      get_connection_id(provider) → str   — opaque handle; contains no credentials
      authenticate(provider)      → str   — same, but triggers handshake if needed

    Package-private (for NexusCallProxy only):
      resolve_strategy(connection_id) → DynamicStrategy

    Custom flow handlers:
        manager = AuthenticationManager(config)
        manager.flow_handler = SlackFlowHandler()   # or DashboardFlowHandler()
    """

    def __init__(self, config: Dict[str, Any]):
        gateway_url = config.get("nexus_gateway_url")
        if not gateway_url:
            raise ValueError(
                "nexus_gateway_url is required for AuthenticationManager. "
                "Set NEXUS_GATEWAY_URL in your .env file. "
                "JarvisCore requires Nexus for all auth — there is no bypass mode."
            )

        self.user_id = config.get("nexus_default_user_id", "jarviscore-agent")
        self.cache_ttl = config.get("auth_strategy_cache_ttl", 300)
        self.auth_timeout = config.get("auth_flow_timeout", 300)
        self.auth_poll_interval = config.get("auth_poll_interval", 2.0)
        self.return_url = config.get(
            "nexus_return_url",
            "http://localhost:8000/oauth/callback",
        )

        # Nexus clients
        self.nexus_client = NexusClient(gateway_url)
        self.lifecycle_monitor = LifecycleMonitor(self.nexus_client)

        # Pluggable OAuth flow handler (CLI by default)
        self.flow_handler: OAuthFlowHandler = CLIFlowHandler(
            open_browser=config.get("auth_open_browser", True)
        )

        # Opaque connection handles — keyed by provider name
        self._connections: Dict[str, str] = {}

        # _strategy_cache is package-private — only NexusCallProxy reads it
        # (via resolve_strategy). Agents never call resolve_strategy directly.
        self._strategy_cache: Dict[str, Tuple[DynamicStrategy, float]] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def get_connection_id(self, provider: str) -> str:
        """
        Return the opaque connection_id for a provider.

        If a connection has already been established this session, returns
        the cached connection_id immediately without another handshake.

        Raises:
            RuntimeError if a new handshake is needed but fails.
        """
        if provider in self._connections:
            return self._connections[provider]
        return await self.authenticate(provider)

    async def authenticate(
        self,
        provider: str,
        user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
    ) -> str:
        """
        Establish a Nexus connection for a provider.

        Scopes are resolved from the provider catalog (nexus/providers.py)
        if not explicitly provided.

        Returns:
            connection_id — an opaque string handle containing no credentials.
            Store this; never store tokens.

        Raises:
            RuntimeError if the OAuth flow fails or times out.
        """
        if provider in self._connections:
            return self._connections[provider]

        uid = user_id or self.user_id
        resolved_scopes = scopes or get_scopes(provider)

        connection_id, auth_url = await self.nexus_client.request_connection(
            provider=provider,
            user_id=uid,
            scopes=resolved_scopes,
            return_url=self.return_url,
        )

        # Present auth URL to user (opens browser / posts to Slack / SSE)
        await self.flow_handler.present_auth_url(auth_url, provider)

        # Poll until ACTIVE
        status = await self.flow_handler.wait_for_completion(
            connection_id=connection_id,
            check_status_fn=self.nexus_client.check_connection_status,
            timeout=self.auth_timeout,
            poll_interval=self.auth_poll_interval,
        )

        if status != "ACTIVE":
            raise RuntimeError(
                f"Nexus auth flow for {provider!r} did not complete: status={status}. "
                f"Connection {connection_id!r} is not active."
            )

        self._connections[provider] = connection_id

        # Start background lifecycle monitoring
        await self.lifecycle_monitor.monitor_connection(connection_id)

        logger.info(
            "Connection established: provider=%s connection_id=%s",
            provider, connection_id,
        )
        return connection_id

    # ── Package-private — NexusCallProxy only ──────────────────────────────

    async def resolve_strategy(self, connection_id: str) -> DynamicStrategy:
        """
        Resolve a connection_id to a DynamicStrategy. Package-private.

        Only NexusCallProxy should call this. Agents and kernel MUST NOT.
        The strategy contains live credentials that agents must never see.

        Uses a TTL cache (default 300s) to avoid hammering the Gateway.
        """
        if connection_id in self._strategy_cache:
            strategy, cached_at = self._strategy_cache[connection_id]
            if time.time() - cached_at < self.cache_ttl and not strategy.is_expired():
                return strategy

        strategy = await self.nexus_client.resolve_strategy(connection_id)
        self._strategy_cache[connection_id] = (strategy, time.time())
        return strategy

    # ── Cleanup ─────────────────────────────────────────────────────────────

    async def close(self):
        """Stop lifecycle monitor and close Nexus client."""
        if self.lifecycle_monitor:
            await self.lifecycle_monitor.stop_all()
        if self.nexus_client:
            await self.nexus_client.close()
