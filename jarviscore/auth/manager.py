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
  2. CLIFlowHandler opens a browser, or HostedFlowHandler hands the link to a UI
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
from jarviscore.config import Settings

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
        manager.flow_handler = HostedFlowHandler(present)   # or SlackFlowHandler()
    """

    def __init__(self, config: Dict[str, Any]):
        # Settings are the fallback, not an alternative: NEXUS_GATEWAY_URL is how
        # the gateway is configured everywhere else, and a manager that only read
        # the config dict reported it unset while the rest of the mesh used it.
        settings = Settings()
        gateway_url = config.get("nexus_gateway_url") or getattr(
            settings, "nexus_gateway_url", None
        )

        self.user_id = config.get("nexus_default_user_id") or getattr(
            settings, "nexus_default_user_id", "jarviscore-agent"
        )
        self.cache_ttl = config.get("auth_strategy_cache_ttl", 300)
        self.auth_timeout = config.get("auth_flow_timeout", 300)
        self.auth_poll_interval = config.get("auth_poll_interval", 2.0)
        self.return_url = config.get("nexus_return_url") or getattr(
            settings, "nexus_return_url", "http://localhost:8000/oauth/callback"
        )

        # Nexus clients — only instantiated when gateway_url is provided.
        # Agents that never call authenticate() don't need Nexus at all.
        self.nexus_client: Optional[NexusClient] = None
        self.lifecycle_monitor: Optional[LifecycleMonitor] = None
        if gateway_url:
            self.nexus_client = NexusClient(gateway_url)
            # The monitor noticed revoked tokens and told nobody: it took an
            # on_attention callback and was built without one, so the next
            # agent run failed at the provider one full run after the system
            # already knew.
            self.lifecycle_monitor = LifecycleMonitor(
                self.nexus_client, on_attention=self._connection_needs_attention
            )
        else:
            logger.debug(
                "AuthenticationManager: NEXUS_GATEWAY_URL not set. "
                "Connected-app calls will raise at runtime. "
                "Set NEXUS_GATEWAY_URL to enable Nexus auth, or run "
                "'docker compose -f docker-compose.nexus.yml up' for local dev."
            )

        # Pluggable OAuth flow handler (CLI by default)
        self.flow_handler: OAuthFlowHandler = CLIFlowHandler(
            open_browser=config.get("auth_open_browser", True)
        )

        # Opaque connection handles — keyed by provider name
        self._connections: Dict[str, str] = {}

        # Providers whose connection the broker says can no longer sign a call.
        self._needs_attention: set = set()

        # Handles for connections found at the gateway rather than made here.
        self._discovered: Dict[str, str] = {}

        # _strategy_cache is package-private — only NexusCallProxy reads it
        self._strategy_cache: Dict[str, Tuple[DynamicStrategy, float]] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────────

    def _connection_needs_attention(self, connection_id: str) -> None:
        """The broker says this connection can no longer sign. Stop handing it out."""
        for provider, held in list(self._connections.items()):
            if held == connection_id:
                del self._connections[provider]
                self._needs_attention.add(provider)
                logger.warning(
                    "Connection for %s needs re-consent; its handle is withdrawn "
                    "until a person approves access again.", provider,
                )
        self._strategy_cache.pop(connection_id, None)

    def providers_needing_attention(self) -> List[str]:
        """Providers that were connected and now need a person to re-consent."""
        return sorted(self._needs_attention)

    def is_connected(self, provider: str) -> bool:
        """Whether a usable handle is held for this provider right now."""
        return provider in self._connections

    def connection_handle(self, provider: str) -> Optional[str]:
        """The opaque handle for a connected provider, or None."""
        return self._connections.get(provider)

    # ── Discovery ───────────────────────────────────────────────────────────

    async def discover(self, provider: str) -> Optional[str]:
        """Learn whether the gateway already holds an active connection.

        Every process starts knowing only the connections it made itself. A
        consent completed in the previous run, or from the CLI, is invisible
        until asked about. Returns the handle, or None when nothing is active.
        """
        if provider in self._connections:
            return self._connections[provider]
        if not self.nexus_client:
            return None
        try:
            found = await self.nexus_client.resolve_active(provider, self.user_id)
        except Exception as exc:
            logger.debug("Discovery for %s failed: %s", provider, exc)
            return None
        if not found:
            return None
        # The gateway resolves by workspace and provider, not by connection id,
        # so the handle names what it is and resolve_strategy knows to ask again.
        handle = f"resolved:{provider}"
        self._connections[provider] = handle
        self._discovered[handle] = provider
        self._needs_attention.discard(provider)
        logger.info("Discovered active %s connection at the gateway", provider)
        return handle

    async def discover_all(self, providers: List[str]) -> None:
        """Bring this process's view in line with the gateway for these providers."""
        for provider in providers:
            await self.discover(provider)

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
            RuntimeError if NEXUS_GATEWAY_URL is not configured.
            RuntimeError if the OAuth flow fails or times out.
        """
        if not self.nexus_client:
            logger.error(
                "Cannot authenticate provider %r: no Nexus gateway configured. "
                "Set NEXUS_GATEWAY_URL, or run "
                "'docker compose -f docker-compose.nexus.yml up' for local dev.",
                provider,
            )
            raise RuntimeError(
                f"No account can be connected to {provider!r} right now, because "
                "this deployment has no way to run a consent flow. Nobody can "
                "approve access until an administrator fixes that, so treat "
                f"{provider!r} as unavailable and say so plainly."
            )

        if provider in self._connections:
            return self._connections[provider]

        connection_id, auth_url = await self.begin_authentication(
            provider, user_id=user_id, scopes=scopes
        )

        # Present auth URL to user (opens browser / posts to Slack / SSE)
        await self.flow_handler.present_auth_url(
            auth_url, provider, connection_id=connection_id
        )

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
        self._needs_attention.discard(provider)

        # Start background lifecycle monitoring
        await self.lifecycle_monitor.monitor_connection(connection_id)

        logger.info(
            "Connection established: provider=%s connection_id=%s",
            provider, connection_id,
        )
        return connection_id

    async def begin_authentication(
        self,
        provider: str,
        user_id: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        return_url: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Create an OAuth handshake without waiting for user consent."""
        if not self.nexus_client:
            raise RuntimeError(
                f"No account can be connected to {provider!r} right now, because "
                "this deployment has no way to run a consent flow."
            )
        await self._ensure_provider(provider)
        return await self.nexus_client.request_connection(
            provider=provider,
            user_id=user_id or self.user_id,
            scopes=scopes or get_scopes(provider),
            return_url=return_url or self.return_url,
        )

    async def _ensure_provider(self, provider: str) -> None:
        """Seed the Broker from the registered provider through its public API."""
        from jarviscore.nexus._data import PROVIDER_URLS
        from jarviscore.nexus.providers import broker_name, get_provider
        from jarviscore.nexus.store import get_store

        entry = get_store().get(provider) or {}
        known = get_provider(provider) or {}
        urls = PROVIDER_URLS.get(provider, {})
        auth_type = str(entry.get("auth_type") or known.get("auth_type") or "oauth2")
        params = dict(urls.get("params") or {})
        if auth_type in {"api_key", "header", "query_param"}:
            field = (entry.get("auth_config") or {}).get("credential_field", "api_key")
            params["credential_schema"] = {
                "type": "object",
                "properties": {field: {"type": "string", "title": "API key", "format": "password"}},
                "required": [field],
            }
        elif auth_type == "basic_auth":
            params["credential_schema"] = {
                "type": "object",
                "properties": {
                    "username": {"type": "string", "title": "Username"},
                    "password": {"type": "string", "title": "Password", "format": "password"},
                },
                "required": ["username", "password"],
            }
        profile = {
            "name": broker_name(provider),
            "auth_type": auth_type,
            "client_id": entry.get("client_id"),
            "client_secret": entry.get("client_secret"),
            "auth_url": urls.get("auth_url"),
            "token_url": urls.get("token_url"),
            "api_base_url": urls.get("api_base_url"),
            "user_info_endpoint": urls.get("user_info_endpoint"),
            "scopes": entry.get("scopes") or known.get("scopes") or [],
            "params": params or None,
            "description": known.get("label"),
            "category": known.get("category"),
        }
        await self.nexus_client.ensure_provider({k: v for k, v in profile.items() if v is not None})

    async def credential_capture(self, auth_url: str) -> Tuple[str, Dict[str, Any]]:
        """Return signed capture state and form schema for a non-OAuth handshake."""
        from urllib.parse import parse_qs, urlparse
        state = (parse_qs(urlparse(auth_url).query).get("state") or [""])[0]
        if not state:
            raise RuntimeError("Nexus did not return a credential capture state.")
        return state, await self.nexus_client.capture_schema(state)

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

        provider = self._discovered.get(connection_id)
        if provider is not None:
            payload = await self.nexus_client.resolve_active(provider, self.user_id)
            if payload is None:
                self._connection_needs_attention(connection_id)
                raise RuntimeError(
                    f"The {provider} connection is no longer active at the gateway."
                )
            strategy = self._strategy_from_resolve(payload)
        else:
            strategy = await self.nexus_client.resolve_strategy(connection_id)
        self._strategy_cache[connection_id] = (strategy, time.time())
        return strategy

    @staticmethod
    def _strategy_from_resolve(payload: Dict[str, Any]) -> DynamicStrategy:
        """/v1/resolve returns the token at the top level; /v1/token nests it.

        The gateway's credentials object also carries bookkeeping (expired,
        expires_in, scope) alongside the credential. Only string-valued fields
        are credentials; the expiry is lifted to where the strategy expects it.
        """
        strategy = payload.get("strategy") or {}
        raw = payload.get("credentials") or {}
        credentials = {
            k: v for k, v in raw.items()
            if isinstance(v, str) and k != "expires_at"
        }
        if payload.get("access_token") and "access_token" not in credentials:
            credentials["access_token"] = payload["access_token"]
        return DynamicStrategy(
            type=strategy.get("type") or "oauth2",
            credentials=credentials,
            config=strategy.get("config") or {},
            expires_at=payload.get("expires_at") or raw.get("expires_at"),
        )

    # ── Cleanup ─────────────────────────────────────────────────────────────

    async def close(self):
        """Stop lifecycle monitor and close Nexus client."""
        if self.lifecycle_monitor:
            await self.lifecycle_monitor.stop_all()
        if self.nexus_client:
            await self.nexus_client.close()
