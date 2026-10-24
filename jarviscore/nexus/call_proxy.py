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

import asyncio
import logging
import uuid
import weakref
from typing import Any, Dict, Optional

import httpx

from .strategy import apply_strategy
from .hosts import HostNotAllowed, ensure_host_allowed

logger = logging.getLogger(__name__)

# One connection pool per event loop and client factory: a provider call reuses
# the TCP and TLS connection the last one opened instead of paying a new
# handshake every time. Keyed by factory too, so a replaced factory (tests) never
# inherits another's client.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[Any, Any]]" = (
    weakref.WeakKeyDictionary()
)
_HTTPX_CLIENT = httpx.AsyncClient


def _keepalive_seconds() -> float:
    import importlib

    settings = importlib.import_module("jarviscore.config.settings").settings
    return float(getattr(settings, "nexus_keepalive_seconds", 120.0))


def _pooled_client():
    loop = asyncio.get_running_loop()
    factory = httpx.AsyncClient
    by_factory = _clients.setdefault(loop, {})
    client = by_factory.get(factory)
    if client is None or getattr(client, "is_closed", False):
        if factory is _HTTPX_CLIENT:
            # Agent turns between provider calls often outlast httpx's 5 s default,
            # which would close the connection the next call wants.
            client = factory(limits=httpx.Limits(keepalive_expiry=_keepalive_seconds()))
        else:
            client = factory()
        by_factory[factory] = client
    return client


async def close_pooled_clients() -> None:
    """Close the provider connections this event loop holds; agent teardown calls it."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for client in (_clients.pop(loop, None) or {}).values():
        close = getattr(client, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception as exc:  # noqa: BLE001 - closing must never fail a teardown
                logger.debug("Closing a provider connection pool failed: %s", exc)


def _run_name(authority: Optional[Dict[str, Any]]) -> str:
    """The journal run a call belongs to: its workflow step, or the workflow, or this process."""
    authority = authority or {}
    workflow, step = authority.get("workflow_id"), authority.get("step_id")
    if not workflow:
        from jarviscore.orchestration.budget import current_workflow_budget

        account = current_workflow_budget()
        workflow = getattr(account, "workflow_id", None)
    if workflow:
        return f"{workflow}/{step}" if step else str(workflow)
    import os

    return f"process-{os.getpid()}"


def _decide(provider: str, method: str, url: str, authority: Optional[Dict[str, Any]]):
    """Decide on a call before any I/O, and record the decision. Returns (call_id, run, journal)."""
    from jarviscore.control.operations import describe
    from jarviscore.control.policy import PolicyDenied, ProviderCall, current_policy
    from jarviscore.evidence.journal import current_journal

    policy = current_policy()
    if policy.mode == "off":
        return None, None, None, False
    authority = authority or {}
    call = ProviderCall(
        provider=provider,
        method=method.upper(),
        url=url,
        atom=authority.get("atom"),
        declared_effect=authority.get("effect"),
        code_origin=authority.get("code_origin") or ("shipped" if authority.get("atom") else "direct"),
        contract=authority.get("contract"),
        action_id=authority.get("action_id"),
    )
    decision = policy.decide(call)
    host, path = describe(url)
    call_id = uuid.uuid4().hex
    run = _run_name(authority)
    journal = current_journal()
    record = {
        "call_id": call_id,
        "provider": provider,
        "method": call.method,
        "host": host,
        "path": path,
        "atom": call.atom,
        "effect": call.effect,
        "code_origin": call.code_origin,
        "verified": call.verified,
        "action_id": call.action_id,
        "outcome": decision.outcome,
        "rule": decision.rule,
        "enforced": decision.enforced,
    }
    if journal is not None:
        try:
            journal.append(run, "policy.decision", record)
        except Exception as exc:  # noqa: BLE001
            if policy.mode == "strict":
                # Strict mode promises every decision is on record before the call leaves.
                raise RuntimeError(f"The call was not made: its decision could not be recorded ({exc}).") from exc
            logger.warning("Journal write failed for %s %s: %s", call.method, host, exc)
            journal = None
    if not decision.allowed:
        if decision.enforced:
            raise PolicyDenied(decision)
        logger.info("[control] would refuse %s %s%s: %s", call.method, host, path, decision.reason)
    return call_id, run, journal, policy.mode == "strict"


def _record(journal, run, kind: str, data: Dict[str, Any], strict: bool) -> None:
    if journal is None:
        return
    try:
        journal.append(run, kind, data)
    except Exception as exc:  # noqa: BLE001
        if strict:
            raise RuntimeError(f"The call was not made: it could not be recorded ({exc}).") from exc
        logger.warning("Journal write failed: %s", exc)


def _record_source(provider: str) -> None:
    """Note whose access the current workflow step used, so its output can be held
    for that person when it reaches a shared space (rooms)."""
    from jarviscore.auth.principal import acting_for
    from jarviscore.orchestration.budget import current_workflow_budget

    account = current_workflow_budget()
    record = getattr(getattr(account, "store", None), "record_workflow_source", None)
    if account is None or not callable(record):
        return
    try:
        record(account.workflow_id, provider, acting_for.get() or "")
    except Exception as exc:  # recording must never break the call
        logger.warning("Could not record the use of %s in %s: %s", provider, account.workflow_id, exc)


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
            auth_manager: an AuthenticationManager, or a zero-argument callable
                returning the one to use right now. The callable form exists
                because the mesh injects the shared manager after agent setup,
                and a proxy that captured a fallback at setup signed from a
                connection table the consent flow never wrote to.
        """
        self._auth_source = auth_manager

    @property
    def _auth(self):
        source = self._auth_source
        return source() if callable(source) else source

    def _provider_for(self, connection_id: str) -> str:
        """The provider behind an opaque handle, so its hosts can be checked."""
        connections = getattr(self._auth, "_connections", None) or {}
        for provider, cid in connections.items():
            if cid == connection_id:
                return str(provider).lower()
        # A gateway-discovered handle names its provider last: "resolved:[person:]github".
        if connection_id.startswith("resolved:"):
            return connection_id.rsplit(":", 1)[-1].lower()
        # Local-vault mode: the handle is the provider name ("github:user123").
        return connection_id.split(":")[0].lower()

    def connection_handle(self, provider: str) -> str:
        """Resolve a provider name to its opaque active handle when available."""
        lookup = getattr(self._auth, "connection_handle", None)
        handle = lookup(provider) if callable(lookup) else None
        return handle if isinstance(handle, str) and handle else provider

    async def call(
        self,
        connection_id: str,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        *,
        authority: Optional[Dict[str, Any]] = None,
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
            authority:      What the call arrives with: the atom, its declared effect,
                            where its code came from, its operation contract and the
                            workflow step. Decided on before any I/O (see control.policy).
            **kwargs:       Passed directly to httpx (json=, params=, data=, etc.)

        Returns:
            {
                "ok":          bool,         # True if status < 400
                "status_code": int,
                "body":        str,          # raw response text
                "content":     bytes,        # raw response body, for downloads
                "json":        Any,          # parsed JSON or None
                "headers":     dict,
            }

        Never raises on HTTP errors — returns {"ok": False, "status_code": ...}.
        Raises RuntimeError only on internal proxy failure (no connection, no Nexus).
        """
        from jarviscore.nexus.client import NexusClient
        provider = self._provider_for(connection_id)
        # Decided before anything leaves this process, including the credential lookup.
        call_id, run, journal, strict = _decide(provider, method, url, authority)

        strategy = None
        request_kwargs = None

        # ── Try auth_manager (gateway mode) first ─────────────────────────────
        try:
            strategy = await self._auth.resolve_strategy(connection_id)
        except Exception as gateway_exc:
            logger.debug(
                "NexusCallProxy: gateway resolve failed for %r (%s) — "
                "falling back to local credential store",
                connection_id, gateway_exc,
            )
        if strategy is not None:
            # Resolve inside the credential boundary, then bind the destination
            # before placing that credential. Policy or placement failures must
            # fail closed rather than selecting a different credential source.
            ensure_host_allowed(provider, url, strategy.config)
            request_kwargs = NexusClient.apply_strategy_to_request(
                strategy, method, url, headers=headers, **kwargs
            )

        # ── Local store fallback (zero-dep mode) ──────────────────────────────
        if request_kwargs is None:
            from jarviscore.nexus.store import get_store

            store = get_store()
            ensure_host_allowed(provider, url, store.get(provider))
            strategy = store.build_strategy(provider)
            if strategy is None:
                raise RuntimeError(
                    f"NexusCallProxy: no credentials found for {connection_id!r}. "
                    f"Run: python -m jarviscore.cli nexus register {provider} --client-id=... --client-secret=..."
                )
            request_kwargs = apply_strategy(strategy, method, url, headers=headers, **kwargs)
            url = request_kwargs["url"]
        request_kwargs.setdefault("timeout", timeout)
        _record_source(provider)

        client = _pooled_client()
        _record(journal, run, "effect.attempt", {"call_id": call_id}, strict)
        refreshed = False
        try:
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
                    ensure_host_allowed(provider, url, strategy.config)
                    request_kwargs = NexusClient.apply_strategy_to_request(
                        strategy, method, url, headers=headers, **kwargs
                    )
                    request_kwargs.setdefault("timeout", timeout)
                    response = await client.request(**request_kwargs)
                    refreshed = True
                    if response.status_code == 401:
                        logger.warning(
                            "NexusCallProxy: second 401 after refresh — "
                            "connection %s may need re-consent (ATTENTION)",
                            connection_id,
                        )
                except HostNotAllowed:
                    raise
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
        except BaseException as exc:
            # What became of a call that left matters most when it failed half way.
            _record(journal, run, "effect.outcome", {
                "call_id": call_id, "error": type(exc).__name__, "refreshed": refreshed,
            }, False)
            raise
        _record(journal, run, "effect.outcome", {
            "call_id": call_id, "status": response.status_code, "refreshed": refreshed,
        }, False)

        return {
            "ok": response.status_code < 400,
            "status_code": response.status_code,
            "body": response.text,
            "content": response.content,
            "json": json_body,
            "headers": dict(response.headers),
        }

    @staticmethod
    def make_nexus_call_fn(
        proxy: "NexusCallProxy", connection_id: str, authority: Optional[Dict[str, Any]] = None,
    ):
        """
        Create the `nexus_call` async function injected into the CoderSandbox namespace.

        The returned function is a closure over (proxy, connection_id).
        Sandbox code calls:

            response = await nexus_call("GET", "https://api.github.com/...")
            response = await nexus_call("POST", url, json={"key": "value"})

        Args:
            proxy:         NexusCallProxy instance (holds auth_manager reference).
            connection_id: The opaque connection handle for this task's provider.
            authority:     Who is calling and with what declared effect, decided on
                           for every call (see control.policy).

        Returns:
            Async callable suitable for injection into a sandbox namespace.
        """
        async def nexus_call(
            method: str, url: str, provider: Optional[str] = None, **kwargs
        ) -> Dict[str, Any]:
            """
            Call a provider API endpoint through Nexus.

            Credentials are resolved internally — this function never
            exposes tokens, API keys, or passwords.

            Args:
                method: HTTP method (GET, POST, PUT, PATCH, DELETE)
                url:    Full provider API endpoint URL
                **kwargs: httpx kwargs (json=, params=, data=, headers=, etc.)

            Returns:
                {"ok": bool, "status_code": int, "body": str, "content": bytes,
                 "json": Any, "headers": dict}

            Raises:
                RuntimeError if Nexus connection is unavailable.
            """
            target = proxy.connection_handle(provider) if provider else connection_id
            return await proxy.call(target, method, url, authority=authority, **kwargs)

        return nexus_call
