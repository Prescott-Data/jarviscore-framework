"""
NexusCallProxy — The credential boundary.

This is the ONLY component in the entire JarvisCore framework that ever
holds a resolved DynamicStrategy (live credentials).  Everything else
operates on opaque connection_id handles.

Security contract:
  - Callers provide: connection_id (opaque) + HTTP intent (method, url, kwargs)
  - Proxy provides: HTTP response body + status code
  - Credentials: NEVER returned to callers. NEVER logged. NEVER stored in agent context.

Usage (from CoderSandbox):
    response = await nexus_call("GET", "https://api.github.com/repos/foo/bar")
    response = await nexus_call("POST", "https://api.stripe.com/v1/charges",
                                json={"amount": 1000, "currency": "usd"})

Usage (direct):
    proxy = NexusCallProxy(auth_manager)
    result = await proxy.call(connection_id, "GET", "https://api.slack.com/api/chat.postMessage",
                              json={"channel": "#general", "text": "Hello!"})
"""

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class NexusCallProxy:
    """
    Single entry point for ALL authenticated HTTP calls to connected apps.

    Internally resolves credentials via AuthenticationManager, applies them
    to the outgoing request, and returns the HTTP response dict.

    Agents and generated sandbox code call this via the `nexus_call()`
    function injected into their namespace — they never create this object
    directly or access the resolved strategy.

    Auto-retry on 401:
      Invalidates the strategy cache, forces a fresh token fetch from
      Nexus Gateway, and retries once.  If the second request also fails
      with 401, returns the error response as-is and logs ATTENTION.
    """

    def __init__(self, auth_manager):
        """
        Args:
            auth_manager: jarviscore.auth.manager.AuthenticationManager instance.
        """
        self._auth = auth_manager

    async def call(
        self,
        connection_id: str,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make an authenticated HTTP call through Nexus.

        Args:
            connection_id: Opaque Nexus connection handle (from context).
            method:         HTTP method ("GET", "POST", "PUT", "PATCH", "DELETE").
            url:            Full URL of the provider API endpoint.
            headers:        Optional additional headers (merged with auth headers).
            timeout:        Request timeout in seconds (default 30s).
            **kwargs:       Passed directly to httpx (json=, params=, data=, etc.)

        Returns:
            {
                "ok":          bool,         # True if status < 400
                "status_code": int,
                "body":        str,          # raw response text
                "json":        Any,          # parsed JSON or None
                "headers":     dict,
            }

        Never raises on HTTP errors — returns {"ok": False, "status_code": ...}.
        Raises RuntimeError only on internal proxy failure (no connection, no Nexus).
        """
        from jarviscore.nexus.client import NexusClient

        try:
            strategy = await self._auth.resolve_strategy(connection_id)
        except Exception as exc:
            raise RuntimeError(
                f"NexusCallProxy: could not resolve strategy for connection {connection_id!r}: {exc}"
            ) from exc

        request_kwargs = NexusClient.apply_strategy_to_request(
            strategy, method, url, headers=headers, **kwargs
        )
        request_kwargs.setdefault("timeout", timeout)

        async with httpx.AsyncClient() as client:
            response = await client.request(**request_kwargs)

            # Auto-retry on 401 — token may have been rotated externally
            if response.status_code == 401:
                logger.info(
                    "NexusCallProxy: 401 for connection=%s — refreshing via Nexus Gateway",
                    connection_id,
                )
                try:
                    if self._auth.nexus_client:
                        await self._auth.nexus_client.refresh_connection(connection_id)
                    self._auth._strategy_cache.pop(connection_id, None)
                    strategy = await self._auth.resolve_strategy(connection_id)
                    request_kwargs = NexusClient.apply_strategy_to_request(
                        strategy, method, url, headers=headers, **kwargs
                    )
                    request_kwargs.setdefault("timeout", timeout)
                    response = await client.request(**request_kwargs)
                    if response.status_code == 401:
                        logger.warning(
                            "NexusCallProxy: second 401 after refresh — "
                            "connection %s may need re-consent (ATTENTION)",
                            connection_id,
                        )
                except Exception as refresh_exc:
                    logger.warning(
                        "NexusCallProxy: refresh failed for %s: %s",
                        connection_id, refresh_exc,
                    )

            # Parse JSON response if possible
            json_body = None
            try:
                json_body = response.json()
            except Exception:
                pass

            return {
                "ok": response.status_code < 400,
                "status_code": response.status_code,
                "body": response.text,
                "json": json_body,
                "headers": dict(response.headers),
            }

    @staticmethod
    def make_nexus_call_fn(proxy: "NexusCallProxy", connection_id: str):
        """
        Create the `nexus_call` async function injected into the CoderSandbox namespace.

        The returned function is a closure over (proxy, connection_id).
        Sandbox code calls:

            response = await nexus_call("GET", "https://api.github.com/...")
            response = await nexus_call("POST", url, json={"key": "value"})

        Args:
            proxy:         NexusCallProxy instance (holds auth_manager reference).
            connection_id: The opaque connection handle for this task's provider.

        Returns:
            Async callable suitable for injection into a sandbox namespace.
        """
        async def nexus_call(method: str, url: str, **kwargs) -> Dict[str, Any]:
            """
            Call a provider API endpoint through Nexus.

            Credentials are resolved internally — this function never
            exposes tokens, API keys, or passwords.

            Args:
                method: HTTP method (GET, POST, PUT, PATCH, DELETE)
                url:    Full provider API endpoint URL
                **kwargs: httpx kwargs (json=, params=, data=, headers=, etc.)

            Returns:
                {"ok": bool, "status_code": int, "body": str, "json": Any, "headers": dict}

            Raises:
                RuntimeError if Nexus connection is unavailable.
            """
            return await proxy.call(connection_id, method, url, **kwargs)

        return nexus_call
