"""What a person delegated for a piece of work, held at every provider call.

An agent acting for someone uses that person's own credentials (Nexus releases
a credential only for the subject that owns it), so it can never do more than
the person could. A mandate narrows that further, to what the person handed
over for this work:

    mandate:
      systems: [erp, gmail]          # providers the work may call
      effects: [read, write]         # read, propose, write, notify, destructive
      expires_at: "2026-11-01T00:00:00Z"

It is registered with the workflow by trusted application code (the caller's
``context["mandate"]``), never taken from what agents write, and holds for every
step and peer working on that workflow. A call outside it is refused
(``outside-mandate``) whatever its origin; no deployment rule lifts it. A mandate
that cannot be read refuses every call.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, FrozenSet, Optional

EFFECTS = ("read", "propose", "write", "notify", "destructive")


@dataclass(frozen=True)
class Mandate:
    systems: Optional[FrozenSet[str]] = None
    effects: Optional[FrozenSet[str]] = None
    expires_at: Optional[float] = None
    digest: str = ""
    #: Why the mandate could not be read; an unreadable mandate refuses every call.
    invalid: str = ""

    def refusal(self, provider: str, effect: str, now: Optional[float] = None) -> Optional[str]:
        """Why a call to ``provider`` with ``effect`` is outside this mandate, or None."""
        if self.invalid:
            return f"The work's mandate cannot be read ({self.invalid}), so nothing may be done under it."
        if self.expires_at is not None and (now if now is not None else time.time()) >= self.expires_at:
            return "The work's mandate has expired."
        if self.systems is not None and (provider or "").lower() not in self.systems:
            return f"The person did not delegate {provider} for this work (mandate: {', '.join(sorted(self.systems)) or 'none'})."
        if self.effects is not None and effect not in self.effects:
            return f"The person did not delegate {effect} effects for this work (mandate: {', '.join(sorted(self.effects)) or 'none'})."
        return None

    def record(self) -> dict:
        return {"digest": self.digest, **({"invalid": self.invalid} if self.invalid else {})}


def _instant(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("expires_at is a time")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("expires_at needs a time zone")
    return parsed.timestamp()


def parse(raw: Any) -> Optional[Mandate]:
    """A mandate from its record; None when there is none."""
    if raw is None:
        return None
    try:
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    except (TypeError, ValueError):
        digest = ""
    try:
        if not isinstance(raw, dict):
            raise ValueError("a mandate is a mapping")
        unknown = set(raw) - {"systems", "effects", "expires_at"}
        if unknown:
            raise ValueError(f"unknown keys {sorted(unknown)}")
        systems = raw.get("systems")
        effects = raw.get("effects")
        if systems is not None and not (isinstance(systems, list) and all(isinstance(s, str) for s in systems)):
            raise ValueError("systems is a list of provider names")
        if effects is not None:
            if not (isinstance(effects, list) and all(e in EFFECTS for e in effects)):
                raise ValueError(f"effects is a list of {', '.join(EFFECTS)}")
        return Mandate(
            systems=frozenset(s.lower() for s in systems) if systems is not None else None,
            effects=frozenset(effects) if effects is not None else None,
            expires_at=_instant(raw["expires_at"]) if raw.get("expires_at") is not None else None,
            digest=digest,
        )
    except (ValueError, TypeError, KeyError) as exc:
        return Mandate(digest=digest, invalid=str(exc))


def current() -> Optional[Mandate]:
    """The mandate the current work runs under (set with ``principal.act_for``)."""
    from jarviscore.auth.principal import mandate

    return parse(mandate.get())
