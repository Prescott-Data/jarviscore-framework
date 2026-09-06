"""Completion-gate evidence.

A gate reports what it observed. It does not report what it concluded.

The distinction is the whole point. A verdict — "evidence is required" — is a
restatement of the rule in the checker's own vocabulary. An agent cannot map it
onto anything it actually did, so its next attempt is a guess, and the guess is
usually the previous attempt reworded. Evidence — "3 evidence items, 0 with a
pointer" — is a fact about the artifact the agent produced. It can be acted on,
and it cannot be satisfied by rewording, because the numbers only move when the
work moves.

There is a second reason to prefer evidence, and it matters more. Guidance
teaches an agent to satisfy the checker; a critique is a description of what the
gate wants to see, so an agent optimising against it optimises the gate. Facts
about its own output give it nothing to optimise against but the work itself.

So a gate states three things and stops: which named check did not hold, what it
reads, and what it observed. It does not advise, rank causes, or suggest a fix —
those are the agent's job, and doing them here would make the boundary into a
decision-maker.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple, Union

__all__ = [
    "GateEvidence",
    "GateAttempt",
    "as_evidence",
    "record_attempt",
]


def _canonical(value: Any) -> str:
    """Stable text for a fact, so equal observations fingerprint equally."""
    try:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _render_fact(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        if not value:
            return "none"
        return ", ".join(str(item) for item in value)
    if value is None:
        return "none"
    return str(value)


@dataclass(frozen=True)
class GateEvidence:
    """Why a completion attempt did not satisfy a gate, stated as facts.

    Attributes:
        check: Name of the check that did not hold. Machine-readable and stable,
            so a repeat of the same failure is recognisable as a repeat.
        requirement: What the check reads, stated once and plainly.
        observed: What the agent actually produced, as named values.
    """

    check: str
    requirement: str = ""
    observed: Mapping[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Identity of this failure: same check, same observations."""
        facts = _canonical({str(k): v for k, v in sorted(self.observed.items())})
        return hashlib.sha256(f"{self.check}:{facts}".encode("utf-8")).hexdigest()

    def render(self) -> str:
        """The agent-facing form: the check, what it reads, what is there."""
        lines = [f"DONE_GATE_UNSATISFIED: {self.check}"]
        if self.requirement:
            lines.append(f"  requires  {self.requirement}")
        if self.observed:
            lines.append("  observed")
            width = max(len(str(key)) for key in self.observed)
            for key, value in self.observed.items():
                lines.append(f"    {str(key).ljust(width)}  {_render_fact(value)}")
        return "\n".join(lines)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "requirement": self.requirement,
            "observed": dict(self.observed),
        }


def as_evidence(reason: Union[str, GateEvidence, None]) -> GateEvidence:
    """Accept either form a gate may return.

    ``_can_complete`` has always returned ``(bool, str)``. A gate that still
    returns a bare string is reporting a verdict with no observations behind it,
    so it is carried through as exactly that — named ``unspecified`` rather than
    dressed up as evidence it did not provide.
    """
    if isinstance(reason, GateEvidence):
        return reason
    return GateEvidence(check="unspecified", requirement=str(reason or "").strip())


@dataclass(frozen=True)
class GateAttempt:
    """One rejected completion attempt, as recorded by the harness."""

    turn: int
    fingerprint: str
    payload_digest: str
    tool_calls: int

    def repeats(self, other: "GateAttempt") -> bool:
        """True when this attempt carries no information the last one lacked.

        Three things must all hold: the same check failed on the same observed
        values, the agent submitted the same artifact, and it performed no work
        in between. Any one of them changing means the attempt is new — an agent
        that is still moving is not stalled, however many times it has been
        rejected.
        """
        return (
            self.fingerprint == other.fingerprint
            and self.payload_digest == other.payload_digest
            and self.tool_calls == other.tool_calls
        )


def _payload_digest(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def record_attempt(
    history: list,
    *,
    turn: int,
    evidence: GateEvidence,
    payload: Any,
    tool_calls: int,
) -> Tuple[GateAttempt, int, Optional[GateAttempt]]:
    """Append this attempt to ``history`` and report how often it has repeated.

    ``history`` is a plain list of dicts so it rides along in ``KernelState`` and
    survives checkpointing. Returns the attempt, the length of the run of
    identical attempts ending here (1 when it is new), and the previous attempt
    if there was one.
    """
    attempt = GateAttempt(
        turn=turn,
        fingerprint=evidence.fingerprint(),
        payload_digest=_payload_digest(payload),
        tool_calls=tool_calls,
    )
    prior = [GateAttempt(**entry) for entry in history]
    streak = 1
    for earlier in reversed(prior):
        if attempt.repeats(earlier):
            streak += 1
        else:
            break
    history.append(attempt.__dict__.copy())
    return attempt, streak, prior[-1] if prior else None
