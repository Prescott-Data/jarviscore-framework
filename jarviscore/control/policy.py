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
    method_floor,
    method_within_effect,
)

logger = logging.getLogger(__name__)

MODES = ("off", "report", "strict")
#: Where the calling code came from: the framework's own transports ("runtime"),
#: an atom shipped with the package, one stored in the function registry, code the
#: model wrote or repaired, or an application calling the proxy itself ("direct").
CODE_ORIGINS = ("runtime", "shipped", "registry", "model", "direct")


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

    @property
    def effect(self) -> str:
        return self.declared_effect or method_floor(self.method)

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
    if call.approval_required and not call.approval:
        return (
            "approval-missing",
            f"{call.atom} needs a person's approval and this call carries none.",
        )
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
    if call.atom and call.declared_effect and not method_within_effect(
        method, call.declared_effect, contract, call.url
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
    digest = ""
    if path:
        rules, approvals, principals, digest = _load_document(path)
    policy = ControlPolicy(
        mode=mode, rules=tuple(rules), approvals=tuple(approvals),
        principals=principals, digest=digest,
    )
    _cached = (key, policy)
    return policy


def _load_rules(path: str) -> List[Rule]:
    """The call rules of a policy file."""
    return _load_document(path)[0]


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
