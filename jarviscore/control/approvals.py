"""Who may approve a consequential action, and how their decision is known to be theirs.

An approval is only as good as the identity behind it. A decision arrives with
an :class:`Approver`, and how much it can be trusted depends on how it came:

- ``verified``: an approval assertion signed with a key this deployment holds
  (:func:`sign_assertion` on the application's backend, after its own sign-in),
  over the exact action the person saw; or a surface that authenticated them.
- ``asserted``: an :class:`Approver` built by application code calling the Mesh
  directly; trusted as far as that code is.
- ``unauthenticated``: a bare name (``resolved_by="ops@..."``). Recorded as such.

Deployment policy (``approvals:`` in the control policy file) decides which
actions need a person, which roles may approve them, that the approver is not
the person who asked (maker-checker), and the least assurance it accepts. An
integration's own ``approval`` is the default; a deployment can require more,
and can waive approval for anything except a destructive action.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

ASSURANCE = ("unauthenticated", "asserted", "verified")
ASSERTION_VERSION = "v1"
#: An assertion older than this is refused: the decision it carries is stale.
MAX_ASSERTION_AGE_SECONDS = 15 * 60


class ApprovalRefused(PermissionError):
    """A decision that does not meet what the deployment requires of an approver."""


@dataclass(frozen=True)
class Approver:
    subject: str
    roles: FrozenSet[str] = frozenset()
    assurance: str = "unauthenticated"
    authenticated_by: str = ""
    #: The approver's organisation scopes (control.scopes), from their sign-in.
    scopes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.scopes:
            from jarviscore.control.scopes import parse_grant

            object.__setattr__(self, "scopes", parse_grant(self.scopes))

    def as_record(self) -> Dict[str, Any]:
        return {
            "approver": self.subject,
            "approver_roles": sorted(self.roles),
            "assurance": self.assurance,
            "authenticated_by": self.authenticated_by,
            **({"approver_scopes": dict(self.scopes)} if self.scopes else {}),
        }

    def holder(self) -> Dict[str, Any]:
        """Who approved, and what they hold, as the broker checks an ``approved_by`` scope."""
        return {"subject": self.subject, "scopes": dict(self.scopes)}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Optional["Approver"]:
        subject = record.get("approver") or record.get("resolved_by") or ""
        if not subject:
            return None
        roles = record.get("approver_roles") or []
        if isinstance(roles, str):
            try:
                roles = json.loads(roles)
            except ValueError:
                roles = [roles]
        scopes = record.get("approver_scopes") or {}
        if isinstance(scopes, str):
            try:
                scopes = json.loads(scopes)
            except ValueError:
                scopes = {}
        return cls(
            subject=str(subject),
            roles=frozenset(str(role) for role in roles),
            assurance=str(record.get("assurance") or "unauthenticated"),
            authenticated_by=str(record.get("authenticated_by") or ""),
            scopes=scopes if isinstance(scopes, dict) else {},
        )


@dataclass(frozen=True)
class ApprovalRequirement:
    """What an action needs before it runs."""

    required: bool
    rule: str = "integration"
    roles: Tuple[str, ...] = ()
    distinct_from: Tuple[str, ...] = ()
    assurance: str = "unauthenticated"
    #: Scopes the approver must hold (``approved_by`` in control.scopes).
    scopes: Tuple[str, ...] = ()

    def as_record(self) -> Dict[str, Any]:
        return {
            "required": self.required, "rule": self.rule, "roles": list(self.roles),
            "distinct_from": list(self.distinct_from), "assurance": self.assurance,
            **({"scopes": list(self.scopes)} if self.scopes else {}),
        }

    @classmethod
    def from_record(cls, record: Optional[Mapping[str, Any]]) -> Optional["ApprovalRequirement"]:
        if not isinstance(record, Mapping):
            return None
        return cls(
            required=bool(record.get("required", True)),
            rule=str(record.get("rule") or "integration"),
            roles=tuple(record.get("roles") or ()),
            distinct_from=tuple(record.get("distinct_from") or ()),
            assurance=str(record.get("assurance") or "unauthenticated"),
            scopes=tuple(record.get("scopes") or ()),
        )


@dataclass(frozen=True)
class ApprovalRule:
    name: str
    match: Dict[str, Any] = field(default_factory=dict)
    require: str = "approval"  # "approval" or "none"
    roles: Tuple[str, ...] = ()
    distinct_from: Tuple[str, ...] = ()
    assurance: str = "unauthenticated"

    def applies(self, facts: Mapping[str, Any]) -> bool:
        for key, wanted in self.match.items():
            options = wanted if isinstance(wanted, list) else [wanted]
            if facts.get(key) not in options:
                return False
        return True


def requirement_for(
    *,
    provider: str,
    atom: str,
    effect: str,
    integration_requires: bool,
    rules: Iterable[ApprovalRule] = (),
    scopes: Any = None,
    operations: Any = None,
) -> ApprovalRequirement:
    """What this deployment requires before ``atom`` runs: the first matching rule, else the
    integration's own; and, where a scope requirement names ``approved_by``, an approver
    who holds that scope, whatever the rest says."""
    base = _requirement_for(provider, atom, effect, integration_requires, rules)
    needed = scopes.for_approval(provider, atom, effect, operations) if scopes is not None else ()
    if not needed:
        return base
    from dataclasses import replace

    floor = base.assurance if base.required else "unauthenticated"
    # A scope is only as good as who is known to hold it: never a bare name.
    assurance = floor if ASSURANCE.index(floor) >= ASSURANCE.index("asserted") else "asserted"
    return replace(base, required=True, scopes=needed, assurance=assurance,
                   rule=base.rule if base.required else f"scope:{','.join(needed)}")


def _requirement_for(provider, atom, effect, integration_requires, rules) -> ApprovalRequirement:
    facts = {"provider": provider, "system": provider, "atom": atom, "effect": effect}
    for rule in rules:
        if not rule.applies(facts):
            continue
        if rule.require == "none":
            if effect == "destructive":
                # A destructive action keeps its person; a waiver cannot remove that.
                return ApprovalRequirement(required=True, rule=f"integration (waiver {rule.name!r} refused for destructive)")
            return ApprovalRequirement(required=False, rule=f"deployment:{rule.name}")
        return ApprovalRequirement(
            required=True,
            rule=f"deployment:{rule.name}",
            roles=rule.roles,
            distinct_from=rule.distinct_from,
            assurance=rule.assurance if rule.assurance in ASSURANCE else "verified",
        )
    return ApprovalRequirement(required=bool(integration_requires) or effect == "destructive")


def check_approver(
    requirement: Optional[ApprovalRequirement],
    approver: Optional[Approver],
    *,
    requester: str = "",
    directory: Optional[Mapping[str, Iterable[str]]] = None,
    grants: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> Optional[str]:
    """Why ``approver`` may not decide on an action with this requirement, or None when they may."""
    if requirement is None or not requirement.required:
        return None
    if not (requirement.roles or requirement.distinct_from or requirement.scopes
            or requirement.assurance != "unauthenticated"):
        # Nothing is required of the approver beyond deciding: any decision stands.
        return None
    if approver is None or not approver.subject:
        return "The decision names no approver."
    if ASSURANCE.index(approver.assurance if approver.assurance in ASSURANCE else "unauthenticated") < ASSURANCE.index(
        requirement.assurance
    ):
        return (
            f"This action needs a {requirement.assurance} approver; {approver.subject!r} is "
            f"{approver.assurance} ({approver.authenticated_by or 'no authentication'})."
        )
    if requirement.roles:
        held = set(approver.roles) | set((directory or {}).get(approver.subject, ()))
        if not held & set(requirement.roles):
            return (
                f"This action needs an approver with one of the roles {sorted(requirement.roles)}; "
                f"{approver.subject!r} holds {sorted(held) or 'none'}."
            )
    if "requester" in requirement.distinct_from and requester and approver.subject == requester:
        return f"{approver.subject!r} asked for this action and may not also approve it."
    if requirement.scopes:
        if grants is None:
            from jarviscore.control.policy import current_policy

            section = current_policy().scopes
            grants = section.grants if section is not None else {}
        held = set(approver.scopes or {}) | set((grants or {}).get(approver.subject, {}))
        missing = [scope for scope in requirement.scopes if scope not in held]
        if missing:
            return (
                f"This action needs an approver who holds {', '.join(missing)}; "
                f"{approver.subject!r} does not."
            )
    return None


# ── Approval assertions ───────────────────────────────────────────────────


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_assertion(
    key: str,
    *,
    subject: str,
    decision: str,
    workflow_id: str,
    action_id: str,
    binding: str,
    roles: Iterable[str] = (),
    key_id: str = "default",
    issued_at: Optional[float] = None,
    scopes: Any = None,
) -> str:
    """An approval assertion, for an application's backend to sign after its own sign-in.

    It names the person, their decision and the exact action (``binding``, the
    action's binding digest, shown in the waiting step's result), so it cannot be
    reused for another action or another decision.
    """
    payload = {
        "kid": key_id, "sub": subject, "roles": sorted(set(roles)), "decision": decision,
        "workflow_id": workflow_id, "action_id": action_id, "binding": binding,
        "iat": int(issued_at if issued_at is not None else time.time()),
    }
    if scopes is not None:
        from jarviscore.control.scopes import parse_grant

        # What the approver may do in the organisation, signed with the decision.
        payload["scopes"] = parse_grant(scopes)
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signed = f"{ASSERTION_VERSION}.{body}"
    signature = hmac.new(key.encode("utf-8"), signed.encode("ascii"), hashlib.sha256).digest()
    return f"{signed}.{_b64(signature)}"


def verify_assertion(
    token: str,
    keys: Mapping[str, str],
    *,
    workflow_id: str,
    action_id: str,
    binding: str,
    decision: str,
    now: Optional[float] = None,
) -> Approver:
    """The approver an assertion proves, or :class:`ApprovalRefused` saying why it proves nothing."""
    try:
        version, body, signature = token.split(".")
        payload = json.loads(_unb64(body))
    except Exception as exc:  # noqa: BLE001
        raise ApprovalRefused("The approval assertion is not readable.") from exc
    if version != ASSERTION_VERSION:
        raise ApprovalRefused(f"Unknown approval assertion version {version!r}.")
    key = keys.get(str(payload.get("kid") or "default"))
    if not key:
        raise ApprovalRefused("The approval assertion was signed with a key this deployment does not hold.")
    expected = hmac.new(key.encode("utf-8"), f"{version}.{body}".encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _unb64(signature)):
        raise ApprovalRefused("The approval assertion's signature does not match.")
    for name, value in (("workflow_id", workflow_id), ("action_id", action_id), ("binding", binding)):
        if payload.get(name) != value:
            raise ApprovalRefused(f"The approval assertion is for another action ({name} differs).")
    from jarviscore.contracts.hitl import normalize_hitl_decision

    if normalize_hitl_decision(str(payload.get("decision"))) != normalize_hitl_decision(decision):
        raise ApprovalRefused("The approval assertion carries a different decision.")
    age = (now if now is not None else time.time()) - float(payload.get("iat") or 0)
    if age < -60 or age > MAX_ASSERTION_AGE_SECONDS:
        raise ApprovalRefused("The approval assertion is stale or from the future.")
    from jarviscore.control.scopes import ScopeError, parse_grant

    try:
        scopes = parse_grant(payload.get("scopes"))
    except ScopeError as exc:
        raise ApprovalRefused(f"The approval assertion's scopes cannot be read ({exc}).") from exc
    return Approver(
        subject=str(payload.get("sub") or ""),
        roles=frozenset(str(role) for role in payload.get("roles") or ()),
        assurance="verified",
        authenticated_by=f"assertion:{payload.get('kid') or 'default'}",
        scopes=scopes,
    )
