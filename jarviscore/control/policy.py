"""The decision on one provider call, made where the call leaves for the network.

Every call a sub-agent makes to a connected provider goes through
``NexusCallProxy``. Before any I/O the proxy builds a :class:`ProviderCall` from
what is actually about to be sent (provider, method, URL) and from the authority
it arrives with (the atom, its declared effect, where its code came from), and
asks :func:`decide`. The answer is recorded in the run's journal; in strict mode
a refusal stops the call before it reaches the network.

Who is trusted for what:

- The model is not. It chooses atoms and their arguments, never their code.
- Atoms shipped with JarvisCore are reviewed code with static contracts, so a
  shipped atom is held to the methods its declared effect allows.
- Code the model wrote or repaired is not trusted: every call it makes must be
  one of the operations its own code verifiably sends, within its declared effect.
- A deployment can refuse more (``deny`` rules); it cannot quietly widen what
  model-written code may do.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from jarviscore.control.operations import (
    READ_METHODS,
    OperationContract,
    effect_rank,
    method_floor,
    method_within_effect,
)

#: Code reviewed with the package: its declared effect is what the call is.
TRUSTED_ORIGINS = ("shipped", "runtime")

logger = logging.getLogger(__name__)

MODES = ("off", "report", "strict")
#: Where the calling code came from: the framework's own transports ("runtime"),
#: an atom shipped with the package, one stored in the function registry, code the
#: model wrote or repaired, or an application calling the proxy itself ("direct").
CODE_ORIGINS = ("runtime", "shipped", "registry", "model", "direct")


class PreviewHeld(RuntimeError):
    """A change previewed, not made: decided on, then held before anything left."""

    def __init__(self, decision: "Decision"):
        super().__init__(f"Previewed only, not sent ({decision.outcome}: {decision.rule}).")
        self.decision = decision


class PolicyDenied(RuntimeError):
    """A call the deployment's policy refused before it reached the network."""

    def __init__(self, decision: "Decision"):
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class ProviderCall:
    """One call to a provider, as it is about to be sent."""

    provider: str
    method: str
    url: str
    atom: Optional[str] = None
    declared_effect: Optional[str] = None
    code_origin: str = "direct"
    contract: Optional[OperationContract] = None
    action_id: Optional[str] = None
    #: Whether policy requires a person's approval for this action, and the
    #: binding of the approval it carries (see control.approvals).
    approval_required: bool = False
    approval: Optional[str] = None
    #: How the call's arguments were held to records the runtime read (control.grounding).
    grounding: Any = None
    #: The person the work acts for, and what they delegated (control.mandate).
    acting_for: Optional[str] = None
    mandate: Any = None

    @property
    def effect(self) -> str:
        """What the call does: as declared by reviewed code; for anything else, never
        less than its method implies (a "read" that POSTs is a write)."""
        floor = method_floor(self.method)
        declared = self.declared_effect
        if not declared:
            return floor
        if self.code_origin in TRUSTED_ORIGINS:
            return declared
        return floor if effect_rank(floor) > effect_rank(declared) else declared

    @property
    def verified(self) -> bool:
        return bool(self.contract and self.contract.verified and self.contract.allows(self.method, self.url))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    rule: str
    reason: str
    enforced: bool

    @property
    def outcome(self) -> str:
        return "allow" if self.allowed else "deny"


@dataclass(frozen=True)
class Rule:
    """A deployment rule: when ``match`` holds, ``decision`` applies."""

    name: str
    decision: str  # "deny" or "allow"
    match: Dict[str, Any] = field(default_factory=dict)

    def applies(self, call: ProviderCall) -> bool:
        for key, wanted in self.match.items():
            actual = {
                "provider": call.provider,
                "system": call.provider,
                "atom": call.atom,
                "effect": call.effect,
                "method": call.method.upper(),
                "code_origin": call.code_origin,
                "verified": call.verified,
            }.get(key)
            options = wanted if isinstance(wanted, list) else [wanted]
            if actual not in options:
                return False
        return True


@dataclass
class ControlPolicy:
    mode: str = "report"
    rules: Tuple[Rule, ...] = ()
    #: Which actions need a person, and who may decide (see control.approvals).
    approvals: Tuple[Any, ...] = ()
    #: Roles each approver holds, when their sign-in does not carry them.
    principals: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    #: Which request fields must come from records the runtime read (control.grounding).
    grounding: Tuple[Any, ...] = ()
    #: Rules on effects other than provider calls (control.effects).
    effect_rules: Tuple[Any, ...] = ()
    #: Digest of the policy file, recorded with every decision made under it.
    digest: str = ""

    def decide(self, call: ProviderCall) -> Decision:
        enforced = self.mode == "strict"
        for rule in self.rules:
            if rule.decision == "deny" and rule.applies(call):
                return Decision(False, f"deployment:{rule.name}", f"Deployment rule {rule.name!r} refuses this call.", enforced)
        refusal = _builtin_refusal(call)
        if refusal is not None:
            rule, reason = refusal
            lifted = next(
                (r for r in self.rules if r.decision == "allow" and r.applies(call) and rule in _LIFTABLE),
                None,
            )
            if lifted is None:
                return Decision(False, rule, reason, enforced)
            return Decision(True, f"deployment:{lifted.name}", f"Allowed by deployment rule {lifted.name!r} over {rule}.", enforced)
        return Decision(True, "within-policy", "", enforced)


#: Built-in refusals a deployment may lift for a named provider: a deliberate,
#: reviewed decision to let its own trusted code mutate without an atom.
_LIFTABLE = frozenset({"mutation-without-atom"})


def _builtin_refusal(call: ProviderCall) -> Optional[Tuple[str, str]]:
    method = call.method.upper()
    mutation = method not in READ_METHODS
    if call.mandate is not None:
        # Not liftable: no deployment rule widens what a person delegated.
        outside = call.mandate.refusal(call.provider, call.effect)
        if outside:
            return ("outside-mandate", outside)
    if call.approval_required and not call.approval:
        return (
            "approval-missing",
            f"{call.atom} needs a person's approval and this call carries none.",
        )
    if call.grounding is not None and not call.grounding.grounded:
        # Not liftable: grounding is what the deployment asked for on this operation.
        return ("ungrounded-argument", call.grounding.reason)
    if mutation and not call.atom:
        return (
            "mutation-without-atom",
            f"{method} to {call.provider} does not come from an atom with a declared "
            "effect and idempotency identity.",
        )
    untrusted = call.code_origin in ("registry", "model")
    contract = call.contract
    # Shipped atoms are held to their declared effect below and, catalogue-wide, by a
    # test that no reachable code in them can exceed it. A mismatch with their
    # contract is imprecision in reading it, not authority; for code the model wrote
    # the contract is the authority.
    if untrusted and contract is not None and contract.verified and not contract.allows(method, call.url):
        return (
            "outside-contract",
            f"{call.atom} does not send {method} to this path: it is not one of the "
            "operations its code declares.",
        )
    # Only reviewed code earns "a read may POST to the search endpoint its contract
    # names": for untrusted code the contract is whatever that code says.
    if call.atom and call.declared_effect and not method_within_effect(
        method, call.declared_effect, contract if call.code_origin in TRUSTED_ORIGINS else None, call.url
    ):
        if not (
            call.code_origin in ("shipped", "runtime")
            and call.declared_effect in ("read", "propose") and method == "POST"
        ):
            return (
                "beyond-declared-effect",
                f"{call.atom} declares a {call.declared_effect} effect; {method} goes beyond it.",
            )
    if untrusted and mutation and not call.verified:
        return (
            "unverified-model-code",
            f"{call.atom} was written by the model and its code does not verifiably "
            f"send {method} to this path, so it may not mutate {call.provider}.",
        )
    if call.code_origin == "model" and mutation and not call.approval:
        # Whatever path brought it here, code the model wrote in this run does not act
        # on the world without a person's approval of that exact action.
        return (
            "unapproved-model-effect",
            f"{call.atom or 'Code the model wrote'} would {method} to {call.provider} "
            "with no approval of this exact action.",
        )
    return None


_cached: Optional[Tuple[Tuple[str, str, float], ControlPolicy]] = None


def current_policy() -> ControlPolicy:
    """The deployment's policy: mode from settings, rules from ``control_policy_path``.

    Read again only when the mode, the path or the file's modification time changes.
    """
    global _cached
    import importlib

    settings_module = importlib.import_module("jarviscore.config.settings")

    settings = settings_module.settings
    mode = str(os.environ.get("JARVISCORE_CONTROL_MODE") or getattr(settings, "control_mode", "report")).lower()
    if mode not in MODES:
        logger.warning("Unknown control mode %r; using strict.", mode)
        mode = "strict"
    path = str(os.environ.get("JARVISCORE_CONTROL_POLICY") or getattr(settings, "control_policy_path", "") or "")
    try:
        stamp = os.path.getmtime(path) if path else 0.0
    except OSError:
        stamp = -1.0
    key = (mode, path, stamp)
    if _cached is not None and _cached[0] == key:
        return _cached[1]
    rules: List[Rule] = []
    approvals: List[Any] = []
    principals: Dict[str, Tuple[str, ...]] = {}
    grounding: List[Any] = []
    effect_rules: Tuple[Any, ...] = ()
    digest = ""
    if path:
        rules, approvals, principals, digest = _load_document(path)
        grounding = _load_grounding(path)
        effect_rules = _load_effect_rules(path, broken=any(r.name == "unreadable-policy" for r in rules))
    policy = ControlPolicy(
        mode=mode, rules=tuple(rules), approvals=tuple(approvals),
        principals=principals, grounding=tuple(grounding), effect_rules=effect_rules, digest=digest,
    )
    _cached = (key, policy)
    return policy


def _load_rules(path: str) -> List[Rule]:
    """The call rules of a policy file."""
    return _load_document(path)[0]


def _load_effect_rules(path: str, broken: bool) -> Tuple[Any, ...]:
    """The ``effects:`` rules of a policy file; a file that cannot be read refuses every effect."""
    from jarviscore.control.effects import EffectRule, parse_rules

    if broken:
        return (EffectRule(name="unreadable-policy", decision="deny"),)
    try:
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8")
        data = json.loads(text) if path.endswith(".json") else __import__("yaml").safe_load(text)
        entries = (data or {}).get("effects")
    except Exception:  # noqa: BLE001 - reported by _load_document
        return (EffectRule(name="unreadable-policy", decision="deny"),)
    if entries is not None and not isinstance(entries, list):
        return (EffectRule(name="unreadable-effects", decision="deny"),)
    return parse_rules(entries)


def _load_grounding(path: str) -> List[Any]:
    """The grounding rules of a policy file. One that cannot be read refuses what it
    matches; one whose match cannot be read refuses every call."""
    from jarviscore.control.grounding import GroundingRule, parse_rule

    try:
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8")
        data = json.loads(text) if path.endswith(".json") else __import__("yaml").safe_load(text)
        entries = (data or {}).get("grounding") or []
        if not isinstance(entries, list):
            raise ValueError("grounding is a list of rules")
    except Exception as exc:  # noqa: BLE001 - _load_document already refuses everything
        logger.debug("No grounding rules read from %s: %s", path, exc)
        return []
    rules = []
    for index, entry in enumerate(entries):
        try:
            rule = parse_rule(entry if isinstance(entry, dict) else {}, index)
        except Exception as exc:  # noqa: BLE001 - a broken policy fails closed
            rule = GroundingRule(name=f"grounding-{index}", invalid=str(exc))
        if rule.invalid:
            logger.error("Grounding rule %s is invalid (%s); calls it matches are refused.", rule.name, rule.invalid)
        rules.append(rule)
    return rules


def _load_document(path: str):
    """(rules, approval rules, principals, digest) from a JSON or YAML file.

    A file that cannot be read refuses every call and requires a verified
    approver for every action: a broken policy fails closed.
    """
    from jarviscore.control.approvals import ApprovalRule

    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        text = raw.decode("utf-8")
        data = json.loads(text) if path.endswith(".json") else __import__("yaml").safe_load(text)
        if data is not None and not isinstance(data, dict):
            raise ValueError("the policy is not a mapping")
    except Exception as exc:  # noqa: BLE001 - a broken policy must fail closed
        logger.error("Control policy %s could not be read (%s); every provider call is refused.", path, exc)
        return (
            [Rule(name="unreadable-policy", decision="deny", match={})],
            [ApprovalRule(name="unreadable-policy", assurance="verified")],
            {},
            "",
        )
    import hashlib

    digest = hashlib.sha256(raw).hexdigest()
    approvals = []
    for index, entry in enumerate((data or {}).get("approvals") or []):
        require = str(entry.get("require") or "approval").lower()
        approvals.append(ApprovalRule(
            name=str(entry.get("name") or f"approval-{index}"),
            match=dict(entry.get("match") or {}),
            require="none" if require == "none" else "approval",
            roles=tuple(str(r) for r in entry.get("roles") or ()),
            distinct_from=tuple(str(d) for d in entry.get("distinct_from") or ()),
            assurance=str(entry.get("assurance") or "unauthenticated"),
        ))
    principals = {
        str(subject): tuple(str(role) for role in (roles or ()))
        for subject, roles in ((data or {}).get("principals") or {}).items()
    }
    rules = []
    for index, entry in enumerate((data or {}).get("rules") or []):
        decision = str(entry.get("decision") or "").lower()
        if decision not in {"deny", "allow"}:
            logger.error("Control policy rule %s has decision %r; it is treated as deny.", index, decision)
            decision = "deny"
        rules.append(Rule(
            name=str(entry.get("name") or f"rule-{index}"),
            decision=decision,
            match=dict(entry.get("match") or {}),
        ))
    return rules, approvals, principals, digest


_SECTIONS = {"rules", "approvals", "principals", "grounding", "effects"}
_RULE_MATCH = {"provider", "system", "atom", "effect", "method", "code_origin", "verified"}
_APPROVAL_KEYS = {"name", "match", "require", "roles", "distinct_from", "assurance"}
_APPROVAL_MATCH = {"provider", "system", "atom", "effect"}


def check_policy(path: str) -> Tuple[List[str], Dict[str, Any]]:
    """What is wrong with a control policy file, and what it holds.

    Everything a running deployment would refuse silently (a rule it cannot read
    fails closed and is only logged) is named here, before it is deployed.
    Returns ``(problems, summary)``; no problems means every rule reads as written.
    """
    from jarviscore.control.effects import parse_rules
    from jarviscore.control.grounding import parse_rule

    problems: List[str] = []
    try:
        with open(path, "rb") as handle:
            text = handle.read().decode("utf-8")
        data = json.loads(text) if path.endswith(".json") else __import__("yaml").safe_load(text)
    except Exception as exc:  # noqa: BLE001
        return [f"{path} cannot be read ({exc}); a deployment using it refuses every call and effect."], {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return [f"{path} is not a mapping of sections; every call and effect would be refused."], {}
    for key in sorted(set(data) - _SECTIONS):
        problems.append(f"Unknown section {key!r}: it is ignored. Sections: {', '.join(sorted(_SECTIONS))}.")

    for index, entry in enumerate(data.get("rules") or []):
        name = (entry or {}).get("name") or f"rules[{index}]"
        if str((entry or {}).get("decision") or "").lower() not in ("deny", "allow"):
            problems.append(f"rules: {name!r} has decision {(entry or {}).get('decision')!r}; it is treated as deny.")
        unknown = set((entry or {}).get("match") or {}) - _RULE_MATCH
        if unknown:
            problems.append(f"rules: {name!r} matches on {sorted(unknown)}, which calls do not have, so it never applies.")
    for index, entry in enumerate(data.get("approvals") or []):
        name = (entry or {}).get("name") or f"approvals[{index}]"
        unknown = set(entry or {}) - _APPROVAL_KEYS
        if unknown:
            problems.append(f"approvals: {name!r} has unknown keys {sorted(unknown)}.")
        unmatched = set((entry or {}).get("match") or {}) - _APPROVAL_MATCH
        if unmatched:
            problems.append(f"approvals: {name!r} matches on {sorted(unmatched)}, which actions do not have.")
        if str((entry or {}).get("assurance") or "unauthenticated") not in ("unauthenticated", "asserted", "verified"):
            problems.append(f"approvals: {name!r} assurance must be unauthenticated, asserted or verified.")
    grounding = []
    for index, entry in enumerate(data.get("grounding") or []):
        try:
            rule = parse_rule(entry if isinstance(entry, dict) else {}, index)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"grounding[{index}]: {exc}; every call would be refused.")
            continue
        grounding.append(rule)
        if rule.invalid:
            problems.append(f"grounding: {rule.name!r} cannot be read ({rule.invalid}); the calls it matches are refused.")
    effect_rules = parse_rules(data.get("effects") or [])
    for rule in effect_rules:
        if rule.name.endswith("(unreadable)"):
            problems.append(
                f"effects: {rule.name[:-13]!r} cannot be read (decision deny or allow; match on sink, action, "
                "origin, agent, target, confined); every effect would be refused."
            )
    summary = {
        "rules": len(data.get("rules") or []),
        "approvals": len(data.get("approvals") or []),
        "principals": len(data.get("principals") or {}),
        "grounding": len(grounding),
        "effects": len(effect_rules),
    }
    return problems, summary


#: What to do about a refusal strict mode would make, by rule.
REMEDIES = {
    "unconfined-execution": "Run where the sandbox is confined (macOS sandbox-exec, Linux bubblewrap), or accept the risk: effects: allow {sink: code}.",
    "browser-send-off-site": "If the site really sends there, allow the host: effects: allow {sink: browser, target: \"<host>/*\"}.",
    "mutation-without-atom": "Call it through an integration (atom), or for your own reviewed client: rules: allow {provider: <provider>, code_origin: direct}.",
    "approval-missing": "The action needs a person's approval; route it through the agent's approval gate.",
    "ungrounded-argument": "The request's values do not come from the records the grounding rule names; check the rule or the agent's sources.",
    "beyond-declared-effect": "The integration sends more than its declared effect; fix the integration or its ATOM_POLICY.",
    "outside-contract": "Model-written code sent an operation its own code does not contain.",
    "unverified-model-code": "Model-written code mutating where its operations cannot be read; register a reviewed integration.",
    "unapproved-model-effect": "Code the model wrote may not act without a person's approval of that exact action.",
}


def review_journal(root: str) -> List[Dict[str, Any]]:
    """Refusals in a journal, grouped by rule and target: what strict mode would refuse
    (from report mode), what it refused, and what was refused before approval."""
    import glob
    from collections import OrderedDict

    groups: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()
    for path in sorted(glob.glob(os.path.join(root, "runs", "*.jsonl"))):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                data = event.get("data") or {}
                if event.get("kind") not in ("policy.decision", "policy.preview") or data.get("outcome") != "deny":
                    continue
                where = data.get("sink") or "provider"
                target = data.get("target") or f"{data.get('host', '')}{data.get('path', '')}"
                state = (
                    "refused before approval" if event["kind"] == "policy.preview"
                    else "refused" if data.get("enforced") else "would refuse"
                )
                key = (state, data.get("rule"), where, data.get("action") or data.get("method"), target)
                group = groups.setdefault(key, {
                    "state": state, "rule": data.get("rule"), "sink": where,
                    "action": data.get("action") or data.get("method"), "target": target,
                    "count": 0, "first_run": event.get("run"), "reason": data.get("reason") or "",
                    "remedy": REMEDIES.get(str(data.get("rule")), "") if not str(data.get("rule")).startswith("deployment:") else "A deployment rule refuses it.",
                })
                group["count"] += 1
    return sorted(groups.values(), key=lambda g: (-g["count"], g["rule"] or ""))
