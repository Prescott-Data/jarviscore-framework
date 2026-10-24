"""
Spending: how much model use each person's work may cost.

In a team, work runs for whoever asked, so its cost belongs to them. Every
model call made while working for a person (``acting_for``) is charged to
that person, per day and per month, and a tenant can cap it:

    spending = Spending(mesh._redis_store)
    spending.set_caps("acme", tokens_per_day=2_000_000, usd_per_month=200)   # everyone in Acme
    spending.set_caps("acme", person="u_1842", usd_per_month=500)           # Alice may spend more

A call that would go over a cap is refused before it is made
(``SpendCapReached``), so a cap is never overshot by more than the calls
already in flight. Asking a room for work checks first, and tells the person
when they have used their allowance and when it comes back. Periods are UTC
days and months.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Iterator, Optional
from uuid import uuid4

from jarviscore.orchestration.budget import WorkflowBudgetExceeded


class SpendCapReached(WorkflowBudgetExceeded):
    """A person's work would go over a spending cap. Not retried: wait for the
    period to end, or have the cap raised."""

    def __init__(self, message: str, *, person: str = "", period: str = ""):
        super().__init__(message, recoverable=False)
        self.person = person
        self.period = period


@dataclass
class Caps:
    """Limits per UTC day and month; None is unlimited."""

    tokens_per_day: Optional[int] = None
    tokens_per_month: Optional[int] = None
    usd_per_day: Optional[float] = None
    usd_per_month: Optional[float] = None

    def limits(self, period: str) -> Dict[str, Optional[float]]:
        return {"tokens": getattr(self, f"tokens_per_{period}"), "usd": getattr(self, f"usd_per_{period}")}

    def any(self) -> bool:
        return any(v is not None for v in asdict(self).values())


def _periods(now: Optional[float] = None) -> Dict[str, str]:
    t = time.gmtime(now if now is not None else time.time())
    return {"day": time.strftime("%Y-%m-%d", t), "month": time.strftime("%Y-%m", t)}


def _resets(period: str) -> str:
    return "at midnight UTC" if period == "day" else "at the start of next month (UTC)"


def _split(person_key: str):
    tenant, _, person_id = str(person_key).partition("/")
    return tenant, person_id


class Spending:
    """Per-person spending ledgers and caps, in the mesh's Redis."""

    #: A reservation not settled within this many seconds (its process stopped) no longer counts.
    reservation_seconds = 900.0

    def __init__(self, redis_store):
        self.store = redis_store
        self._redis = redis_store._redis

    # ── Caps ────────────────────────────────────────────────────────────────

    @staticmethod
    def _caps_key(tenant: str) -> str:
        return f"spend:{{{tenant}}}:caps"

    def set_caps(self, tenant: str, *, person: str = "", **caps) -> Caps:
        """Set caps for everyone in ``tenant``, or for one ``person`` (their id), which
        overrides the tenant's. Unnamed limits are left as they were; pass None to clear one."""
        unknown = set(caps) - {f.name for f in fields(Caps)}
        if unknown:
            raise ValueError(f"Unknown caps: {sorted(unknown)}")
        import json

        key, field = self._caps_key(tenant), person or "*"
        current = json.loads(self._redis.hget(key, field) or "{}")
        current.update(caps)
        current = {k: v for k, v in current.items() if v is not None}
        if current:
            self._redis.hset(key, field, json.dumps(current))
        else:
            self._redis.hdel(key, field)
        return Caps(**current)

    def caps_for(self, person_key: str) -> Caps:
        """The caps that apply to a person: theirs over their tenant's."""
        import json

        tenant, person_id = _split(person_key)
        both = self._redis.hmget(self._caps_key(tenant), "*", person_id)
        merged: Dict[str, Any] = {}
        for raw in both:
            merged.update(json.loads(raw) if raw else {})
        return Caps(**merged)

    # ── Usage ───────────────────────────────────────────────────────────────

    def usage(self, person_key: str, now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        """What a person's work has used this day and month: tokens, USD, calls."""
        return {period: self.store.person_spend(person_key, period, stamp)
                for period, stamp in _periods(now).items()}

    def check(self, person_key: str) -> None:
        """Raise ``SpendCapReached`` if any of the person's caps is already reached."""
        caps = self.caps_for(person_key)
        if not caps.any():
            return
        for period, used in self.usage(person_key).items():
            limits = caps.limits(period)
            if limits["tokens"] is not None and used["tokens"] >= limits["tokens"]:
                self._refuse(person_key, period, f"{used['tokens']:,} of {int(limits['tokens']):,} tokens")
            if limits["usd"] is not None and used["usd"] >= limits["usd"]:
                self._refuse(person_key, period, f"${used['usd']:.2f} of ${limits['usd']:.2f}")

    @staticmethod
    def _refuse(person_key: str, period: str, amount: str) -> None:
        raise SpendCapReached(
            f"This {period}'s allowance for work done for {person_key} is used up ({amount}); "
            f"it renews {_resets(period)}, or an admin can raise it.",
            person=person_key, period=period)

    # ── Charging model calls ────────────────────────────────────────────────

    def reserve(self, person_key: str, tokens: int) -> str:
        """Hold ``tokens`` against the person's caps before a call; raises ``SpendCapReached``."""
        caps = self.caps_for(person_key)
        reservation_id = uuid4().hex
        refused = self.store.reserve_person_spend(
            person_key, _periods(), {p: caps.limits(p) for p in ("day", "month")},
            reservation_id, max(1, int(tokens)), self.reservation_seconds)
        if refused:
            period, amount = refused
            self._refuse(person_key, period, amount)
        return reservation_id

    def settle(self, person_key: str, reservation_id: str, tokens: int, cost_usd: float) -> None:
        self.store.settle_person_spend(person_key, _periods(), reservation_id,
                                       max(0, int(tokens)), max(0.0, float(cost_usd)))

    def release(self, person_key: str, reservation_id: str) -> None:
        self.store.release_person_spend(person_key, reservation_id)


_CURRENT: ContextVar[Optional[Spending]] = ContextVar("jarviscore_spending", default=None)


def current_spending() -> Optional[Spending]:
    return _CURRENT.get()


@contextmanager
def spending_scope(redis_store) -> Iterator[None]:
    """Charge model calls made inside to the person they are made for (``acting_for``)."""
    token = _CURRENT.set(Spending(redis_store) if redis_store is not None else None)
    try:
        yield
    finally:
        _CURRENT.reset(token)


class PersonCharge:
    """One model call's charge to the person it is made for; a no-op outside a spending scope."""

    def __init__(self, tokens: int):
        from jarviscore.auth.principal import acting_for

        self.person = acting_for.get() or ""
        self.spending = current_spending() if "/" in self.person else None
        self.reservation = self.spending.reserve(self.person, tokens) if self.spending else None

    def settle(self, tokens: int, cost_usd: float) -> None:
        if self.reservation:
            self.spending.settle(self.person, self.reservation, tokens, cost_usd)
            self.reservation = None

    def release(self) -> None:
        if self.reservation:
            self.spending.release(self.person, self.reservation)
            self.reservation = None
