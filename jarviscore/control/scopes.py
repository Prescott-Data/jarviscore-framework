"""Custom scopes: what each person may do in their organisation, held at every call made for them.

A provider's own scopes (``read``, ``write``) say what a credential can reach.
They cannot say that only Carol may approve claims, and only up to 10,000; that
suspicious-activity reports go only to the MLRO; that only finance may open
financial reports. Those are your organisation's scopes, defined by you, and an
agent working for a person holds exactly the person's:

    scopes:
      require:                        # which operations need which scope
        - name: claim-approval        # the operation itself: whatever code reaches it is held
          match: {provider: guidewire, method: POST, path: "/claims/{id}/approve"}
          requires: claims.approve
          limits:
            - {field: json.amount, kind: money, at_most: amount}
        - name: claim-payment
          match: {provider: guidewire, method: POST, path: "/claims/{id}/payments"}
          requires: claims.pay
          approved_by: claims.approve   # whoever approves must hold this, within its limits
          limits:
            - {field: json.amount, kind: money, at_most: amount}
        - name: sar-recipients
          match: {provider: casework, method: POST, path: "/sars/{id}/send"}
          requires: fincrime.sar.send
          limits:
            - {field: json.to, kind: email, one_of: recipients}
        - name: finance-portal
          match: {sink: browser, target: "finance.acme.com/*"}
          requires: finance.reports.read
      grants:                         # people whose sign-in does not carry their scopes
        acme/carol: {claims.vet: {}, claims.approve: {amount: "10000"}}
      unattended: {}                  # what work done for no one holds

A person's scopes come from your application (``OnBehalfOf(..., scopes=...)``),
which is authoritative for every scope it names; ``grants`` adds the scopes it
does not name. A mandate's ``scopes`` narrows them for one piece of work, never
widens them.

Match on the operation (``method`` and ``path``) so that any code reaching it,
an integration, code the model wrote or your own client, is held to the scope;
``atom`` alone holds only that integration's calls.

Every requirement a call matches must hold:

- ``requires``: the person the work is for holds the scope (work for no one:
  ``unattended``). Otherwise ``scope-missing``.
- ``limits``: each is checked against the request as it will leave, in the
  terms of the holder's grant. A grant that does not state the term is refused;
  ``"*"`` states that there is no limit. A value the request does not carry, or
  carries in a form that cannot be read, is refused. Lists are checked item by
  item. Otherwise ``over-scope-limit``.
- ``approved_by``: the call carries an approval by someone who holds that scope,
  within its limits. The approval is then required whatever else the policy says.

Both refusals hold in report mode as well as strict: the application said what
the person may do. No deployment rule lifts them.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

#: A term stating that a scope has no limit on it.
UNLIMITED = "*"
RELATIONS = ("at_most", "one_of", "equals")
#: What a requirement may match on: a provider call, or any other effect.
CALL_KEYS = frozenset({"provider", "system", "atom", "effect", "method", "host", "path"})
EFFECT_KEYS = frozenset({"sink", "action", "target", "origin", "agent"})
#: Keys an approval request knows before the call is made.
_STATIC_CALL_KEYS = frozenset({"provider", "system", "atom", "effect"})
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")


class ScopeError(ValueError):
    """A grant or requirement that cannot be read."""


# ── Grants ────────────────────────────────────────────────────────────────


def parse_grant(raw: Any) -> Dict[str, Dict[str, Any]]:
    """``{scope: terms}`` from a mapping or a list of scope names; :class:`ScopeError` if unreadable."""
    if raw is None:
        return {}
    if isinstance(raw, (list, tuple, set, frozenset)):
        raw = {name: {} for name in raw}
    if not isinstance(raw, Mapping):
        raise ScopeError("scopes are a mapping of scope to terms, or a list of scope names")
    grant: Dict[str, Dict[str, Any]] = {}
    for name, terms in raw.items():
        if not isinstance(name, str) or not _NAME.match(name):
            raise ScopeError(f"scope name {name!r} must be letters, digits and . _ : -")
        if terms is None:
            terms = {}
        if not isinstance(terms, Mapping):
            raise ScopeError(f"scope {name!r}: its terms are a mapping, e.g. {{amount: \"10000\"}}")
        for key in terms:
            if not isinstance(key, str) or not key:
                raise ScopeError(f"scope {name!r}: term names are text")
        grant[name] = dict(terms)
    return grant


def grant_digest(grant: Optional[Mapping[str, Any]]) -> str:
    if grant is None:
        return ""
    text = json.dumps(grant, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Requirements ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Limit:
    field: str
    kind: str
    relation: str
    term: str

    def describe(self) -> str:
        return f"{self.field} {self.relation.replace('_', ' ')} {self.term}"


@dataclass(frozen=True)
class Requirement:
    name: str
    match: Tuple[Tuple[str, Any], ...] = ()
    requires: Optional[str] = None
    approved_by: Optional[str] = None
    limits: Tuple[Limit, ...] = ()
    #: Why it could not be read: a broken requirement refuses every call it matches,
    #: and every call when its match cannot be read.
    invalid: str = ""

    @property
    def on_effects(self) -> bool:
        return any(key in EFFECT_KEYS for key, _ in self.match)

    def applies_to_call(self, call: "Facts") -> bool:
        if self.on_effects:
            return False
        for key, wanted in self.match:
            options = wanted if isinstance(wanted, list) else [wanted]
            if key in ("provider", "system"):
                ok = (call.provider or "").lower() in [str(o).lower() for o in options]
            elif key == "method":
                ok = (call.method or "").upper() in [str(o).upper() for o in options]
            elif key == "host":
                ok = (call.host or "").lower() in [str(o).lower() for o in options]
            elif key == "path":
                ok = any(_path_matches(str(o), call.path or "") for o in options)
            elif key == "atom":
                ok = call.atom in options
            elif key == "effect":
                ok = call.effect in options
            else:
                ok = False
            if not ok:
                return False
        return True

    def may_apply_to_action(self, provider: str, atom: Optional[str], effect: str) -> bool:
        """Whether any call this action makes could match (keys it cannot know count as matching)."""
        if self.on_effects:
            return False
        facts = Facts(provider=provider, atom=atom, effect=effect)
        return Requirement(self.name, tuple((k, v) for k, v in self.match if k in _STATIC_CALL_KEYS)
                           ).applies_to_call(facts)

    def applies_to_effect(self, effect) -> bool:
        if not self.on_effects:
            return False
        actual = {"sink": effect.sink, "action": effect.action, "origin": effect.origin,
                  "agent": effect.agent, "target": effect.target}
        for key, wanted in self.match:
            options = wanted if isinstance(wanted, list) else [wanted]
            if key == "target":
                if not any(fnmatch.fnmatchcase(str(actual["target"] or ""), str(o)) for o in options):
                    return False
            elif actual.get(key) not in options:
                return False
        return True


def _path_matches(template: str, path: str) -> bool:
    """Whether any reading of ``path`` a server might route on is this operation (fails closed)."""
    from jarviscore.control.grounding import _path_params, _template, path_variants

    try:
        pattern, lowered = _template(template)[0], _template(template.lower())[0]
    except ValueError:
        return True  # an unreadable path is reported by policy check, and refuses what it may match
    for variant in path_variants(path):
        if _path_params(pattern, variant) is not None or _path_params(lowered, variant.lower()) is not None:
            return True
    return False


def parse_requirement(entry: Any, index: int) -> Requirement:
    name = str(entry.get("name") or f"scope-{index}") if isinstance(entry, dict) else f"scope-{index}"
    if not isinstance(entry, dict):
        return Requirement(name=name, invalid="a requirement is a mapping")
    match = entry.get("match")
    if not isinstance(match, dict) or not match:
        return Requirement(name=name, invalid="match is a non-empty mapping (an unreadable match refuses every call)")
    keys = set(match)
    if keys - CALL_KEYS - EFFECT_KEYS:
        return Requirement(name=name, invalid=f"match takes {', '.join(sorted(CALL_KEYS | EFFECT_KEYS))}, not {sorted(keys - CALL_KEYS - EFFECT_KEYS)}")
    if keys & CALL_KEYS and keys & EFFECT_KEYS:
        return Requirement(name=name, invalid="match is on a provider call or on another effect (sink), not both")
    if any(isinstance(v, (dict, type(None))) for v in match.values()):
        return Requirement(name=name, invalid="match values are text or lists of text")
    rule = Requirement(name=name, match=tuple(sorted(match.items())))
    try:
        unknown = set(entry) - {"name", "match", "requires", "approved_by", "limits"}
        if unknown:
            raise ScopeError(f"unknown keys {sorted(unknown)}")
        requires, approved_by = entry.get("requires"), entry.get("approved_by")
        for label, value in (("requires", requires), ("approved_by", approved_by)):
            if value is not None and (not isinstance(value, str) or not _NAME.match(value)):
                raise ScopeError(f"{label} is a scope name")
        if requires is None and approved_by is None:
            raise ScopeError("a requirement names requires, approved_by or both")
        if approved_by is not None and rule.on_effects:
            raise ScopeError("approved_by applies to provider calls, which carry an approval")
        limits = []
        from jarviscore.control.grounding import KINDS

        for item in entry.get("limits") or []:
            if not isinstance(item, dict):
                raise ScopeError("each limit is a mapping")
            relations = [r for r in RELATIONS if r in item]
            if len(relations) != 1 or set(item) - {"field", "kind", *RELATIONS}:
                raise ScopeError("a limit is {field, kind, and one of at_most, one_of, equals: <term>}")
            relation = relations[0]
            kind = str(item.get("kind") or "exact")
            if kind not in KINDS:
                raise ScopeError(f"limit kind is one of {', '.join(KINDS)}")
            if relation == "at_most" and kind not in ("money", "number"):
                raise ScopeError("at_most compares money or number")
            if not isinstance(item.get("field"), str) or not item["field"]:
                raise ScopeError("a limit names the request field it holds, e.g. json.amount")
            if not isinstance(item[relation], str) or not item[relation]:
                raise ScopeError(f"{relation} names the grant's term, e.g. amount")
            limits.append(Limit(field=item["field"], kind=kind, relation=relation, term=item[relation]))
        return Requirement(name=name, match=rule.match, requires=requires, approved_by=approved_by,
                           limits=tuple(limits))
    except (ScopeError, TypeError, ValueError) as exc:
        return Requirement(name=name, match=rule.match, invalid=str(exc))


@dataclass(frozen=True)
class Scopes:
    """The ``scopes:`` section of a control policy."""

    require: Tuple[Requirement, ...] = ()
    grants: Dict[str, Dict[str, Dict[str, Any]]] = field(default_factory=dict)
    unattended: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: Problems reading the section; any makes it refuse every call it could match.
    problems: Tuple[str, ...] = ()

    @property
    def active(self) -> bool:
        return bool(self.require) or bool(self.problems)

    def for_approval(self, provider: str, atom: Optional[str], effect: str, operations=None) -> Tuple[str, ...]:
        """Scopes an approver of this action must hold (``approved_by`` of what it may match).

        A requirement on method, host or path applies when one of the action's
        ``operations`` (its verified contract) matches it; when they are unknown,
        it applies, so the action waits for an approver rather than being refused.
        """
        samples = operation_facts(provider, atom, effect, operations)
        needed = set()
        for r in self.require:
            if not r.approved_by or r.invalid or not r.may_apply_to_action(provider, atom, effect):
                continue
            dynamic = any(key not in _STATIC_CALL_KEYS for key, _ in r.match)
            if dynamic and operations is not None and not any(r.applies_to_call(f) for f in samples):
                continue
            needed.add(r.approved_by)
        return tuple(sorted(needed))


def parse_section(raw: Any) -> Scopes:
    if raw is None:
        return Scopes()
    if not isinstance(raw, dict) or set(raw) - {"require", "grants", "unattended"}:
        return Scopes(problems=("scopes is a mapping of require, grants and unattended",))
    problems: List[str] = []
    entries = raw.get("require") or []
    if not isinstance(entries, list):
        return Scopes(problems=("scopes.require is a list of requirements",))
    require = tuple(parse_requirement(entry, index) for index, entry in enumerate(entries))
    grants: Dict[str, Dict[str, Dict[str, Any]]] = {}
    raw_grants = raw.get("grants") or {}
    if not isinstance(raw_grants, dict):
        problems.append("scopes.grants is a mapping of person to scopes")
        raw_grants = {}
    for person, grant in raw_grants.items():
        try:
            grants[str(person)] = parse_grant(grant)
        except ScopeError as exc:
            # The person holds nothing from this file rather than something misread.
            problems.append(f"scopes.grants[{person!r}]: {exc}")
    try:
        unattended = parse_grant(raw.get("unattended"))
    except ScopeError as exc:
        problems.append(f"scopes.unattended: {exc}")
        unattended = {}
    return Scopes(require=require, grants=grants, unattended=unattended, problems=tuple(problems))


# ── Checking ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Facts:
    """What a scope requirement can see of a call."""

    provider: str = ""
    atom: Optional[str] = None
    effect: str = ""
    method: str = ""
    host: str = ""
    path: str = ""


@dataclass(frozen=True)
class Holder:
    """Someone whose scopes a call is checked against."""

    label: str  # "person" or "approver"
    subject: Optional[str]
    grant: Dict[str, Dict[str, Any]]
    #: Scopes a mandate narrowed this work to; None when it does not narrow them.
    within: Optional[FrozenSet[str]] = None

    def holds(self, scope: str) -> bool:
        return scope in self.grant and (self.within is None or scope in self.within)


def person_holder(scopes: Scopes, person: Optional[str], app_grant: Optional[Mapping[str, Any]],
                  mandate=None) -> Holder:
    """The person the work is for, with what they hold: your application's grant, then the policy's."""
    if person:
        grant = {**scopes.grants.get(person, {}), **dict(app_grant or {})}
    else:
        grant = dict(scopes.unattended)
    within = getattr(mandate, "scopes", None)
    return Holder("person", person, grant, within)


def approver_holder(scopes: Scopes, approver: Optional[Mapping[str, Any]]) -> Optional[Holder]:
    if not approver or not approver.get("subject"):
        return None
    subject = str(approver["subject"])
    try:
        carried = parse_grant(approver.get("scopes"))
    except ScopeError:
        carried = {}
    return Holder("approver", subject, {**scopes.grants.get(subject, {}), **carried})


@dataclass
class ScopeCheck:
    """The outcome of every scope requirement that applied to one call or effect."""

    allowed: bool = True
    rule: str = ""
    reason: str = ""
    requirements: List[str] = field(default_factory=list)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    grant: str = ""

    def record(self) -> Dict[str, Any]:
        return {"allowed": self.allowed, "requirements": self.requirements, "checks": self.checks,
                "grant": self.grant, **({"reason": self.reason} if self.reason else {})}

    def refuse(self, rule: str, reason: str) -> None:
        if self.allowed:
            self.allowed, self.rule, self.reason = False, rule, reason


def _who(holder: Holder) -> str:
    if holder.label == "approver":
        return f"the approver ({holder.subject})"
    return f"{holder.subject}" if holder.subject else "work done for no one"


def _check_holder(check: ScopeCheck, requirement: Requirement, scope: str, holder: Holder,
                  view: Optional[Dict[str, Any]]) -> None:
    from jarviscore.control.grounding import Unusable, canonical_value, resolve

    entry: Dict[str, Any] = {"requirement": requirement.name, "scope": scope, "holder": holder.label,
                             "subject": holder.subject, "held": holder.holds(scope), "limits": []}
    check.checks.append(entry)
    if not entry["held"]:
        narrowed = holder.within is not None and scope in holder.grant
        check.refuse("scope-missing", (
            f"{_who(holder)} does not hold {scope}"
            + (" for this work (the mandate does not include it)" if narrowed else "")
            + f", which {requirement.name} requires."
        ))
        return
    terms = holder.grant.get(scope) or {}
    for limit in requirement.limits:
        result = {"field": limit.field, "relation": limit.relation, "term": limit.term}
        entry["limits"].append(result)
        bound = terms.get(limit.term)
        if bound is None:
            result["outcome"] = "no-term"
            check.refuse("over-scope-limit", (
                f"{_who(holder)} holds {scope} without stating its {limit.term!r} "
                f"(\"*\" if it has no limit), so {limit.field} cannot be held to it."))
            continue
        if bound == UNLIMITED:
            result["outcome"] = "unlimited"
            continue
        if view is None:
            result["outcome"] = "unreadable"
            check.refuse("over-scope-limit", f"The request's body cannot be read, so {limit.describe()} cannot be checked.")
            continue
        values = []
        for value in resolve(view, limit.field):
            values.extend(value if isinstance(value, list) else [value])
        if not values:
            result["outcome"] = "absent"
            check.refuse("over-scope-limit", f"The request does not carry {limit.field}, so its limit under {scope} cannot be checked.")
            continue
        try:
            sent = [canonical_value(limit.kind, value) for value in values]
            if limit.relation == "one_of":
                allowed = bound if isinstance(bound, list) else [bound]
                permitted = {canonical_value(limit.kind, item) for item in allowed}
                ok = all(value in permitted for value in sent)
            elif limit.relation == "equals":
                ok = all(value == canonical_value(limit.kind, bound) for value in sent)
            else:
                ok = all(value <= canonical_value(limit.kind, bound) for value in sent)
        except (Unusable, TypeError) as exc:
            result["outcome"] = "unusable"
            check.refuse("over-scope-limit", f"{limit.field} or the {limit.term!r} term {exc}, so it cannot be held to {scope}.")
            continue
        result["outcome"] = "within" if ok else "beyond"
        if not ok:
            check.refuse("over-scope-limit", (
                f"{limit.field} is beyond what {_who(holder)} may do under {scope} "
                f"({limit.term} {'is' if limit.relation != 'one_of' else 'lists'} the limit)."))


def check_call(scopes: Scopes, facts: Facts, request, person: Holder, approver: Optional[Holder],
               preview: bool = False) -> Optional[ScopeCheck]:
    """The scope requirements ``facts`` matches, checked; None when none applies."""
    if not scopes.active:
        return None
    check = ScopeCheck(grant=grant_digest(person.grant))
    if scopes.problems:
        check.requirements.append("(unreadable scopes)")
        check.refuse("scope-missing", f"The policy's scopes cannot be read ({scopes.problems[0]}); nothing that may need a scope is allowed.")
        return check
    applying = [r for r in scopes.require if r.invalid and not r.match or r.applies_to_call(facts)]
    if not applying:
        return None
    view = None
    if request is not None and not getattr(request, "opaque", False):
        view = {**request.view(), "path": _path_values(applying, facts.path)}
    for requirement in applying:
        check.requirements.append(requirement.name)
        if requirement.invalid:
            check.refuse("scope-missing", f"Scope requirement {requirement.name!r} cannot be read ({requirement.invalid}).")
            continue
        if requirement.requires:
            _check_holder(check, requirement, requirement.requires, person, view)
        if requirement.approved_by and not preview:
            if approver is None:
                check.checks.append({"requirement": requirement.name, "scope": requirement.approved_by,
                                     "holder": "approver", "subject": None, "held": False, "limits": []})
                check.refuse("scope-missing", (
                    f"{requirement.name} needs the approval of someone who holds "
                    f"{requirement.approved_by}, and this call carries none."))
            else:
                _check_holder(check, requirement, requirement.approved_by, approver, view)
    return check


def check_effect(scopes: Scopes, effect, person: Holder) -> Optional[ScopeCheck]:
    """The scope requirements an effect (browser, peer, memory, ...) matches, checked."""
    if not scopes.active:
        return None
    check = ScopeCheck(grant=grant_digest(person.grant))
    if scopes.problems:
        check.requirements.append("(unreadable scopes)")
        check.refuse("scope-missing", f"The policy's scopes cannot be read ({scopes.problems[0]}).")
        return check
    applying = [r for r in scopes.require if r.invalid and not r.match or r.applies_to_effect(effect)]
    if not applying:
        return None
    view = {"attributes": dict(effect.attributes or {}), "target": effect.target}
    for requirement in applying:
        check.requirements.append(requirement.name)
        if requirement.invalid:
            check.refuse("scope-missing", f"Scope requirement {requirement.name!r} cannot be read ({requirement.invalid}).")
        elif requirement.requires:
            _check_holder(check, requirement, requirement.requires, person, view)
    return check


def _path_values(applying: List[Requirement], path: str) -> Dict[str, str]:
    from jarviscore.control.grounding import _path_params, _template

    for requirement in applying:
        for key, wanted in requirement.match:
            if key != "path":
                continue
            for option in wanted if isinstance(wanted, list) else [wanted]:
                try:
                    found = _path_params(_template(str(option))[0], path)
                except ValueError:
                    continue
                if found is not None:
                    return found
    return {}


def out_of_reach(scopes: Scopes, person: Holder, provider: str, atom: str, effect: str,
                 operations=None) -> Optional[str]:
    """The scope ``atom`` always needs and this person does not hold, or None.

    A requirement on provider, atom and effect alone decides it. One on method,
    host or path does only when the atom's operations are all known
    (``operations``, from its verified contract) and every one of them matches.
    Anything less leaves the atom offered; the broker still decides every call.
    """
    if not scopes.active or scopes.problems:
        return None
    samples = operation_facts(provider, atom, effect, operations)
    for requirement in scopes.require:
        if requirement.invalid or not requirement.requires or requirement.on_effects:
            continue
        if person.holds(requirement.requires):
            continue
        static = all(key in _STATIC_CALL_KEYS for key, _ in requirement.match)
        if static and requirement.applies_to_call(Facts(provider=provider, atom=atom, effect=effect)):
            return requirement.requires
        if not static and samples and all(requirement.applies_to_call(f) for f in samples):
            return requirement.requires
    return None


def operation_facts(provider: str, atom: Optional[str], effect: str, operations) -> List[Facts]:
    """What a requirement sees of each operation an atom's code sends (a ``*`` span as one segment)."""
    from urllib.parse import urlsplit

    facts = []
    for operation in operations or ():
        url = urlsplit(operation.template.replace("*", "x"))
        facts.append(Facts(provider=provider, atom=atom, effect=effect, method=operation.method,
                           host=(url.hostname or "").lower(), path=url.path or "/"))
    return facts


def current_person(scopes: Scopes) -> Holder:
    """The person the current work is for, with what they hold."""
    from jarviscore.auth.principal import acting_for, scopes as held
    from jarviscore.control.mandate import current as current_mandate

    return person_holder(scopes, acting_for.get(), held.get(), current_mandate())


#: Scope refusals hold whenever control is on: the application said what the person may do.
PERSONAL_RULES = frozenset({"outside-mandate", "scope-missing", "over-scope-limit"})
