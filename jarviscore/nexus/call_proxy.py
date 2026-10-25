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


#: Providers that deduplicate a mutation by a request header. An operation's id
#: goes there, so a retried call is the same request and is carried out once.
_IDEMPOTENCY_HEADERS = {
    "stripe": "Idempotency-Key",
    "adyen": "Idempotency-Key",
    "mollie": "Idempotency-Key",
    "gocardless": "Idempotency-Key",
    "checkout": "Cko-Idempotency-Key",
    "paypal": "PayPal-Request-Id",
}


def _with_idempotency_key(provider: str, method: str, headers, authority) -> Optional[Dict[str, str]]:
    name = _IDEMPOTENCY_HEADERS.get(provider)
    operation = (authority or {}).get("action_id")
    if not name or not operation or method.upper() in ("GET", "HEAD", "OPTIONS"):
        return headers
    if any(key.lower() == name.lower() for key in (headers or {})):
        return headers
    return {**(headers or {}), name: str(operation)[:64]}


def _workflow_of(authority: Optional[Dict[str, Any]]) -> str:
    """The workflow a call belongs to, or this process when it belongs to none."""
    workflow = (authority or {}).get("workflow_id")
    if not workflow:
        from jarviscore.orchestration.budget import current_workflow_budget

        account = current_workflow_budget()
        workflow = getattr(account, "workflow_id", None)
    if workflow:
        return str(workflow)
    import os

    return f"process-{os.getpid()}"


def _run_name(authority: Optional[Dict[str, Any]]) -> str:
    """The journal run a call belongs to: its workflow step, or the workflow, or this process."""
    workflow, step = _workflow_of(authority), (authority or {}).get("step_id")
    return f"{workflow}/{step}" if step and not workflow.startswith("process-") else workflow


def _provider_call(provider: str, method: str, url: str, authority: Dict[str, Any], grounding=None):
    from jarviscore.auth.principal import acting_for
    from jarviscore.control.mandate import current as current_mandate
    from jarviscore.control.policy import ProviderCall

    return ProviderCall(
        acting_for=acting_for.get(),
        mandate=current_mandate(),
        provider=provider,
        method=method.upper(),
        url=url,
        atom=authority.get("atom"),
        declared_effect=authority.get("effect"),
        code_origin=authority.get("code_origin") or ("shipped" if authority.get("atom") else "direct"),
        contract=authority.get("contract"),
        action_id=authority.get("action_id"),
        approval_required=bool(authority.get("approval_required")),
        approval=authority.get("approval"),
        grounding=grounding,
    )


def _preview(provider: str, method: str, url: str, authority: Dict[str, Any], grounding) -> None:
    """Decide on a change without making it: note the decision for the caller, then hold."""
    from jarviscore.control.operations import describe
    from jarviscore.control.policy import PreviewHeld, current_policy

    from jarviscore.evidence.journal import current_journal

    call = _provider_call(provider, method, url, authority, grounding)
    decision = current_policy().decide(call)
    host, path = describe(url)
    noted = {
        "method": method.upper(), "host": host, "path": path, "atom": call.atom,
        "action_id": call.action_id,
        "outcome": decision.outcome, "rule": decision.rule, "reason": decision.reason,
        "enforced": decision.enforced,
        "grounding": grounding.record() if grounding is not None else None,
    }
    # On record too: a change refused before anyone was asked is evidence of an attempt.
    _record(current_journal(), _run_name(authority), "policy.preview", noted, False)
    authority["preview"].append(noted)
    raise PreviewHeld(decision)


def _decide(provider: str, method: str, url: str, authority: Optional[Dict[str, Any]], grounding=None):
    """Decide on a call before any I/O, and record the decision. Returns (call_id, run, journal)."""
    from jarviscore.control.operations import describe
    from jarviscore.control.policy import PolicyDenied, current_policy
    from jarviscore.evidence.journal import current_journal

    policy = current_policy()
    if policy.mode == "off":
        return None, None, None, False
    authority = authority or {}
    call = _provider_call(provider, method, url, authority, grounding)
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
        "approval": call.approval,
        "acting_for": call.acting_for,
        **({"mandate": call.mandate.record()} if call.mandate is not None else {}),
        "outcome": decision.outcome,
        "rule": decision.rule,
        "enforced": decision.enforced,
    }
    if grounding is not None:
        record["grounding"] = grounding.record()
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


def _record(journal, run, kind: str, data: Dict[str, Any], strict: bool) -> Optional[Dict[str, Any]]:
    if journal is None:
        return None
    try:
        return journal.append(run, kind, data)
    except Exception as exc:  # noqa: BLE001
        if strict:
            raise RuntimeError(f"The call was not made: it could not be recorded ({exc}).") from exc
        logger.warning("Journal write failed: %s", exc)
        return None


def _refusal_code(exc) -> str:
    try:
        return str(exc.response.json().get("error") or exc.response.status_code)
    except Exception:  # noqa: BLE001
        return "403"


def _grounding_rules():
    from jarviscore.control.policy import current_policy

    policy = current_policy()
    return policy.grounding if policy.mode != "off" else ()


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
        sent_to = url
        grounding_rules = _grounding_rules()
        grounding = None
        # The broker's own re-reads for grounding are sources, never held to it.
        if grounding_rules and (authority or {}).get("atom") != "control.grounding":
            grounding = await self._ground(
                connection_id, provider, method, url, kwargs, authority, grounding_rules,
            )
        if isinstance((authority or {}).get("preview"), list) and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            # A preview of an action before a person is asked: decided, never sent.
            _preview(provider, method, url, authority, grounding)
        # Decided before anything leaves this process, including the credential lookup.
        call_id, run, journal, strict = _decide(provider, method, url, authority, grounding)
        headers = _with_idempotency_key(provider, method, headers, authority)

        strategy = None
        request_kwargs = None

        # ── Try auth_manager (gateway mode) first ─────────────────────────────
        from jarviscore.auth.principal import operation

        # Nexus records which operation each credential was released for.
        operation_token = operation.set((authority or {}).get("action_id") or call_id)
        try:
            strategy = await self._auth.resolve_strategy(connection_id)
        except Exception as gateway_exc:
            status = getattr(getattr(gateway_exc, "response", None), "status_code", None)
            if status == 403:
                # Nexus refused this credential for the person the work acts for: that is
                # the answer, not a reason to use some other credential instead.
                raise PermissionError(
                    f"Nexus refused the {provider} credential for the person this work acts for "
                    f"({_refusal_code(gateway_exc)})."
                ) from gateway_exc
            from jarviscore.auth.principal import acting_for

            person = acting_for.get()
            deployment = getattr(self._auth, "user_id", None)
            if person and person != deployment and getattr(self._auth, "nexus_client", None) is not None:
                # Work for a person uses that person's credential or none: the deployment's
                # own local credential is not theirs.
                raise RuntimeError(
                    f"No usable {provider} credential for the person this work acts for "
                    f"({type(gateway_exc).__name__}: {gateway_exc})."
                ) from gateway_exc
            logger.debug(
                "NexusCallProxy: gateway resolve failed for %r (%s) — "
                "falling back to local credential store",
                connection_id, gateway_exc,
            )
        finally:
            operation.reset(operation_token)
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
        if grounding_rules and method.upper() not in ("GET", "HEAD", "OPTIONS"):
            from jarviscore.control.grounding import OBSERVATIONS
            from jarviscore.control.operations import describe

            # Whatever this run changes is no longer a source for grounding.
            OBSERVATIONS.record_change(_workflow_of(authority), provider, describe(sent_to)[1])
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
                    forget = getattr(self._auth, "forget_strategy", None)
                    if callable(forget):
                        forget(connection_id)
                    else:
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
        outcome = {"call_id": call_id, "status": response.status_code, "refreshed": refreshed}
        kept = None
        if (
            grounding_rules and method.upper() == "GET" and response.status_code < 400
            and json_body is not None
        ):
            from jarviscore.control.grounding import sources_matching
            from jarviscore.control.operations import describe
            from jarviscore.evidence.journal import digest

            host, path = describe(sent_to)
            if sources_matching(grounding_rules, provider, path):
                kept = (host, path, digest(json_body))
                outcome["observed"] = kept[2]
        event = _record(journal, run, "effect.outcome", outcome, False)
        if kept is not None:
            from jarviscore.control.grounding import OBSERVATIONS

            # Kept only once its record is written, so grounding can cite it.
            OBSERVATIONS.record_read(
                _workflow_of(authority), provider, kept[0], kept[1], json_body, kept[2],
                {"run": event["run"], "seq": event["seq"], "hash": event["hash"]} if event else None,
            )

        return {
            "ok": response.status_code < 400,
            "status_code": response.status_code,
            "body": response.text,
            "content": response.content,
            "json": json_body,
            "headers": dict(response.headers),
        }

    async def _ground(self, connection_id, provider, method, url, kwargs, authority, rules):
        """Hold the call to the grounding rules that apply to it (control.grounding)."""
        from urllib.parse import urlsplit

        from jarviscore.control import grounding as g

        request = g.request_from(method, url, kwargs)
        applying = [rule for rule in rules if rule.applies(provider, (authority or {}).get("atom"), request)]
        if not applying:
            return None
        workflow = _workflow_of(authority)
        scheme = urlsplit(url).scheme or "https"

        async def read_again(source, selectors, host):
            handle = connection_id if source.provider == provider else self.connection_handle(source.provider)
            response = await self.call(handle, "GET", f"{scheme}://{host}{g.fill(source, selectors)}", authority={
                "workflow_id": (authority or {}).get("workflow_id") or workflow,
                "step_id": (authority or {}).get("step_id"),
                "atom": "control.grounding", "effect": "read", "code_origin": "runtime",
            })
            if not response.get("ok") or response.get("json") is None:
                raise RuntimeError(f"re-read returned {response.get('status_code')}")

        return await g.ground(
            applying, request, workflow, inputs=g.workflow_input(workflow), fetch=read_again,
        )

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
