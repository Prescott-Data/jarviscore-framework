"""The decision on every effect that is not a provider call, made where it happens.

Provider calls are decided in the broker (``NexusCallProxy``). Everything else an
agent can do that outlives its step or leaves its sandbox goes through
:func:`mediated` at the point where it happens:

=========  ==============================================================
sink       what
=========  ==============================================================
code       a program run in the sandbox (model-written, a registry atom,
           an atom shipped with JarvisCore)
process    a command run outside the sandbox's child (the host)
artifact   a file published from the sandbox to blob storage
workspace  a step's changes to its files, exported for the next step or
           for review
memory     a fact kept for later sessions
peer       a message to another agent: sent, delegated, or broadcast
output     a step's result delivered to the steps and caller after it
browser    a page's navigation, or a request carrying data out of the
           browser (control.browser_requests)
=========  ==============================================================

Each effect is decided before it happens and recorded in the run's journal as a
``policy.decision`` followed by ``effect.attempt`` and ``effect.outcome``, the
same events as provider calls, so ``jarviscore verify`` holds every one of them
to "decided before it happened". Records hold sizes and digests, never content.

A deployment can refuse any effect with an ``effects:`` rule. In strict mode the
runtime also refuses, unless a rule allows it, running model-written code or
commands outside a confined child: without confinement such code reaches the
network and the host directly, past every broker.
"""
from __future__ import annotations

import contextvars
import fnmatch
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SINKS = ("code", "process", "artifact", "workspace", "memory", "peer", "output", "browser")
#: Where an effect's content came from: the framework itself, an atom shipped with
#: the package or kept in the registry, the model (code, commands, words), or a
#: web page's own scripts.
ORIGINS = ("runtime", "shipped", "registry", "model", "page")

#: The workflow step effects belong to when a site does not name it.
scope: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "jarviscore_effect_scope", default=None
)


class EffectDenied(PermissionError):
    """An effect the deployment's policy refused before it happened."""

    def __init__(self, decision):
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class Effect:
    sink: str
    action: str
    target: str = ""
    origin: str = "runtime"
    agent: Optional[str] = None
    #: Sizes, digests, flags (``confined``); never content.
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectRule:
    name: str
    decision: str  # "deny" or "allow"
    match: Tuple[Tuple[str, Any], ...] = ()

    def applies(self, effect: Effect) -> bool:
        actual = {
            "sink": effect.sink, "action": effect.action, "origin": effect.origin,
            "agent": effect.agent, "target": effect.target,
        }
        for key, wanted in self.match:
            options = wanted if isinstance(wanted, list) else [wanted]
            value = actual.get(key)
            if key == "target":
                if not any(fnmatch.fnmatchcase(str(value or ""), str(o)) for o in options):
                    return False
            elif key == "confined":
                if bool(effect.attributes.get("confined")) not in [bool(o) for o in options]:
                    return False
            elif value not in options:
                return False
        return True


def parse_rules(entries) -> Tuple[EffectRule, ...]:
    """``effects:`` rules. One that cannot be read refuses every effect."""
    rules = []
    for index, entry in enumerate(entries or []):
        name = str((entry or {}).get("name") or f"effect-{index}") if isinstance(entry, dict) else f"effect-{index}"
        decision = str((entry or {}).get("decision") or "").lower() if isinstance(entry, dict) else ""
        match = (entry or {}).get("match") if isinstance(entry, dict) else None
        if (
            decision not in ("deny", "allow")
            or not isinstance(match, dict)
            or set(match) - {"sink", "action", "origin", "agent", "target", "confined"}
            or any(isinstance(v, (dict, type(None))) for v in match.values())
        ):
            logger.error("Effect rule %s cannot be read; every effect is refused.", name)
            rules.append(EffectRule(name=f"{name} (unreadable)", decision="deny"))
            continue
        rules.append(EffectRule(name=name, decision=decision, match=tuple(sorted(match.items()))))
    return tuple(rules)


#: Built-in refusals a deployment may lift with an ``allow`` rule.
_LIFTABLE = frozenset({"unconfined-execution", "browser-send-off-site"})


def _builtin_refusal(effect: Effect) -> Optional[Tuple[str, str]]:
    if (
        effect.sink in ("code", "process")
        and effect.origin in ("model", "registry")
        and effect.attributes.get("confined") is False
    ):
        return (
            "unconfined-execution",
            f"{'Code' if effect.sink == 'code' else 'A command'} the model chose would run "
            "outside a confined sandbox, where it reaches the network and host past every "
            "broker. Run it confined, or allow it by deployment rule.",
        )
    if (
        effect.sink == "browser" and effect.action == "send"
        and effect.attributes.get("host") != effect.attributes.get("page")
    ):
        return (
            "browser-send-off-site",
            f"The page would send data to {effect.attributes.get('host')}, which is not the site "
            f"it is on ({effect.attributes.get('page') or 'none'}). Allow that host by deployment rule.",
        )
    return None


def decide(effect: Effect):
    """The decision on ``effect`` under the current policy."""
    from jarviscore.control.policy import Decision, current_policy

    policy = current_policy()
    enforced = policy.mode == "strict"
    for rule in policy.effect_rules:
        if rule.decision == "deny" and rule.applies(effect):
            return Decision(False, f"deployment:{rule.name}", f"Deployment rule {rule.name!r} refuses this {effect.sink} effect.", enforced)
    refusal = _builtin_refusal(effect)
    if refusal is not None:
        name, reason = refusal
        lifted = next(
            (r for r in policy.effect_rules if r.decision == "allow" and name in _LIFTABLE and r.applies(effect)),
            None,
        )
        if lifted is None:
            return Decision(False, name, reason, enforced)
        return Decision(True, f"deployment:{lifted.name}", f"Allowed by deployment rule {lifted.name!r} over {name}.", enforced)
    return Decision(True, "within-policy", "", enforced)


def content_digest(value: Any) -> Dict[str, Any]:
    """Size and SHA-256 of content, for the record (never the content itself)."""
    if isinstance(value, str):
        value = value.encode("utf-8", errors="replace")
    if not isinstance(value, (bytes, bytearray)):
        from jarviscore.evidence.journal import canonical

        value = canonical(value).encode("utf-8")
    return {"bytes": len(value), "digest": hashlib.sha256(value).hexdigest()}


class Mediation:
    """Decide on one effect, record its attempt and outcome. Use as a context manager."""

    __slots__ = ("effect", "run", "journal", "strict", "effect_id", "outcome", "active", "agent")

    def __init__(self, effect: Effect, workflow_id: Optional[str], step_id: Optional[str]):
        self.effect = effect
        self.outcome: Dict[str, Any] = {}
        self.effect_id = uuid.uuid4().hex
        self.journal = None
        self.strict = False
        self.active = False
        current = scope.get() or {}
        self.agent = effect.agent or current.get("agent")
        workflow = workflow_id or current.get("workflow_id")
        step = step_id or current.get("step_id")
        from jarviscore.nexus.call_proxy import _run_name

        self.run = _run_name({"workflow_id": workflow, "step_id": step})

    def __enter__(self) -> "Mediation":
        from jarviscore.control.policy import current_policy

        policy = current_policy()
        if policy.mode == "off":
            return self
        from jarviscore.evidence.journal import current_journal

        self.active = True
        self.strict = policy.mode == "strict"
        decision = decide(self.effect)
        self.journal = current_journal()
        record = {
            "call_id": self.effect_id,
            "sink": self.effect.sink,
            "action": self.effect.action,
            "target": self.effect.target,
            "origin": self.effect.origin,
            "agent": self.agent,
            "attributes": dict(self.effect.attributes),
            "outcome": decision.outcome,
            "rule": decision.rule,
            "enforced": decision.enforced,
            **({"reason": decision.reason} if decision.reason else {}),
        }
        self._append("policy.decision", record, required=True)
        if not decision.allowed:
            if decision.enforced:
                self.active = False
                raise EffectDenied(decision)
            logger.info("[control] would refuse %s %s %s: %s", self.effect.sink, self.effect.action,
                        self.effect.target, decision.reason)
        self._append("effect.attempt", {"call_id": self.effect_id}, required=True)
        return self

    def done(self, **outcome: Any) -> None:
        """What became of the effect, recorded when the block ends."""
        self.outcome.update(outcome)

    def __exit__(self, kind, error, traceback) -> None:
        if not self.active:
            return
        data = {"call_id": self.effect_id, **self.outcome}
        if kind is not None:
            data["error"] = kind.__name__
        self._append("effect.outcome", data, required=False)

    def _append(self, kind: str, data: Dict[str, Any], required: bool) -> None:
        if self.journal is None:  # the deployment switched the journal off
            return
        try:
            self.journal.append(self.run, kind, data)
        except Exception as exc:  # noqa: BLE001
            if required and self.strict:
                # Strict mode promises every effect is on record before it happens.
                raise RuntimeError(f"The effect did not happen: it could not be recorded ({exc}).") from exc
            logger.warning("Journal write failed for %s %s: %s", self.effect.sink, self.effect.action, exc)


async def run_mediated(effect: Effect, run, *, workflow_id=None, step_id=None, ok=None):
    """Await ``run()`` as ``effect``: decided first, its attempt and outcome recorded.

    ``ok(result)`` says whether it succeeded, for the record.
    """
    with mediated(effect, workflow_id=workflow_id, step_id=step_id) as mediation:
        result = await run()
        if ok is not None:
            mediation.done(ok=bool(ok(result)))
        return result


def mediated(effect: Effect, *, workflow_id: Optional[str] = None, step_id: Optional[str] = None) -> Mediation:
    """Decide on and record ``effect``; raises :class:`EffectDenied` in strict mode when refused."""
    return Mediation(effect, workflow_id, step_id)
