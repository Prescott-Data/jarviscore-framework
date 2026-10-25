"""The decision on what a browser page sends, made where it leaves the browser.

Browser code and the page's own scripts run in a real browser with the network.
Whatever the agent does there (a click that submits a form, ``evaluate`` running
``fetch``, a script posting to an analytics or attacker host) leaves as an HTTP
request from the browser context. This module decides on those requests where
they leave, through :mod:`jarviscore.control.effects`:

- **navigate**: a top-level document load (where the agent goes). Decided and
  recorded.
- **send**: any request that carries data out: a method other than GET, HEAD or
  OPTIONS, from a form, ``fetch``, XHR or a beacon. Decided and recorded. In
  strict mode one to a host other than the page's own is refused unless the
  deployment allows that host (``browser-send-off-site``).
- Other reads (images, scripts, styles, GET data requests) pass without a
  decision; recording each would bury the record and tell nothing new.

In strict mode requests are intercepted (``context.route``) so a refusal stops
them before they leave; Playwright disables the HTTP cache while it intercepts.
In report mode they are only observed, at no cost to the page.

Not covered: WebSocket and WebRTC traffic, and requests a service worker makes
(strict mode blocks service workers where it creates the context).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from jarviscore.control import effects

logger = logging.getLogger(__name__)

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _page_url(request) -> str:
    try:
        frame = request.frame
        return frame.page.url if frame is not None else ""
    except Exception:  # noqa: BLE001 - service-worker requests have no frame
        return ""


def describe(request) -> Optional[effects.Effect]:
    """The effect a request is, or None for a read that needs no decision."""
    url = request.url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    method = request.method.upper()
    try:
        navigation = request.is_navigation_request() and request.frame.parent_frame is None
    except Exception:  # noqa: BLE001
        navigation = False
    if method in READ_METHODS and not navigation:
        return None
    try:
        body = request.post_data_buffer or b""
    except Exception:  # noqa: BLE001 - an unreadable body is still recorded as a send
        body = b""
    page = _page_url(request)
    return effects.Effect(
        "browser", "navigate" if navigation and method in READ_METHODS else "send",
        target=f"{(parts.hostname or '').lower()}{parts.path or '/'}",
        origin="page",
        attributes={
            "method": method,
            "host": (parts.hostname or "").lower(),
            "page": _host(page),
            "resource": request.resource_type,
            **effects.content_digest(body),
        },
    )


class RequestBroker:
    """Decides on and records one browser context's navigations and sends."""

    def __init__(self, scope: Optional[Dict[str, Any]]):
        self.scope = dict(scope or {})
        self._open: Dict[int, effects.Mediation] = {}
        #: Every request that carried data out, in order: what the agent's actions really sent.
        self.sent: list = []

    def _note(self, effect: effects.Effect, mediation: Optional[effects.Mediation], refused: bool) -> None:
        if effect.action != "send":
            return
        decision = getattr(mediation, "decision", None)
        self.sent.append({
            "method": effect.attributes.get("method"), "to": effect.target,
            "outcome": "refused" if refused else (
                "sent (strict mode would refuse)" if decision is not None and not decision.allowed else "sent"
            ),
        })

    def _mediation(self, effect: effects.Effect) -> effects.Mediation:
        agent = self.scope.get("agent")
        if agent and not effect.agent:
            effect = effects.Effect(effect.sink, effect.action, effect.target, effect.origin, agent, effect.attributes)
        return effects.mediated(effect, workflow_id=self.scope.get("workflow_id"), step_id=self.scope.get("step_id"))

    async def route(self, route, request) -> None:
        """Strict mode: decided before it leaves; a refusal aborts it."""
        effect = describe(request)
        if effect is None:
            await route.continue_()
            return
        mediation = self._mediation(effect)
        try:
            mediation.__enter__()
        except effects.EffectDenied as exc:
            logger.info("[browser] refused %s %s: %s", request.method, effect.target, exc)
            self._note(effect, mediation, refused=True)
            await route.abort("blockedbyclient")
            return
        self._note(effect, mediation, refused=False)
        self._open[id(request)] = mediation
        try:
            await route.continue_()
        except Exception as exc:  # noqa: BLE001 - the page went away; the attempt is on record
            self._finish(request, ok=False, error=type(exc).__name__)

    def observe(self, request) -> None:
        """Report mode: recorded as it leaves; nothing is held."""
        effect = describe(request)
        if effect is None:
            return
        mediation = self._mediation(effect)
        try:
            mediation.__enter__()
        except effects.EffectDenied:  # report mode never enforces; a strict switch mid-run does
            return
        except Exception as exc:  # noqa: BLE001 - observing must never break the page
            logger.warning("[browser] could not record %s: %s", effect.target, exc)
            return
        self._note(effect, mediation, refused=False)
        self._open[id(request)] = mediation

    async def finished(self, request) -> None:
        status = None
        try:
            response = await request.response()
            status = response.status if response is not None else None
        except Exception:  # noqa: BLE001 - the outcome is still that it was sent
            pass
        self._finish(request, ok=status is None or status < 400, status=status)

    def failed(self, request) -> None:
        self._finish(request, ok=False, error=str(getattr(request, "failure", "") or "failed")[:200])

    def _finish(self, request, **outcome) -> None:
        mediation = self._open.pop(id(request), None)
        if mediation is None:
            return
        mediation.done(**{k: v for k, v in outcome.items() if v is not None})
        mediation.__exit__(None, None, None)


async def attach(context, scope: Optional[Dict[str, Any]] = None) -> Optional[RequestBroker]:
    """Decide on and record what pages in ``context`` send, as the current mode says."""
    from jarviscore.control.policy import current_policy

    policy = current_policy()
    if policy.mode == "off" or context is None:
        return None
    existing = getattr(context, "_jc_request_broker", None)
    if existing is not None:
        existing.scope = dict(scope or effects.scope.get() or {})
        return existing
    broker = RequestBroker(scope or effects.scope.get())
    context._jc_request_broker = broker
    if policy.mode == "strict":
        await context.route("**/*", broker.route)
    else:
        context.on("request", broker.observe)
    context.on("requestfinished", broker.finished)
    context.on("requestfailed", broker.failed)
    return broker
