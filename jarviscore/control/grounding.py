"""Grounding: a consequential call's arguments come from records the runtime read itself.

Approval asks a person; grounding asks the system of record. A deployment names,
for an operation such as a payment, which fields of the request leaving for the
provider must equal (or be one of, or be at most) fields of records the broker
itself received from a provider earlier in the same workflow. The model chooses
the call; it cannot choose those values. An instruction planted in a document,
an email or a record's free-text field can change what the model wants to send,
and the broker refuses it anyway.

What makes this sound rather than string matching:

- **Records come from the broker, not the model.** Only responses the broker
  received from a provider are observations. Code cannot hand it a record.
- **Relationships, not membership.** A binding selects one record (the invoice
  the call pays) and the next binding follows it (that invoice's supplier). A
  value that appears somewhere in the run proves nothing.
- **Selectors have an origin.** Which invoice may come from the request (the
  model's choice, recorded as such) or only from the caller's structured input
  (``selectors_from: [input]``).
- **Typed comparison.** IBANs are checked and compared by their ISO 13616 form,
  money and numbers as decimals, email by IDNA domain; text is compared exactly
  after NFC normalisation, never case-folded or confusable-folded.
- **Ambiguity is refused.** Two different records matching a selector, a field
  sent twice, a body grounding cannot read: all deny.
- **What the run wrote is not a source.** A record read after this workflow
  changed it is not used to ground anything.
- **What leaves is what is checked:** the request httpx will send (``content``
  wins over ``data`` wins over ``json``), not the arguments the model passed.

Residual risk, published with the claim: systems of record can be wrong, stale
or compromised; an attacker can still influence which permitted operation is
chosen unless selectors come from the caller's input.
"""
from __future__ import annotations

import collections
import functools
import itertools
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, unquote, urlsplit

RELATIONS = ("equals", "one_of", "at_most")
KINDS = ("exact", "id", "text", "iban", "money", "number", "email")
SELECTOR_ORIGINS = ("input", "request")
_NUMERIC = ("money", "number")


class Unusable(ValueError):
    """A value that cannot be compared as the kind the rule names."""


# ── Values ──────────────────────────────────────────────────────────────────


def _iban(value: Any) -> str:
    if not isinstance(value, str):
        raise Unusable("is not text")
    compact = re.sub(r"[\s-]", "", value).upper()
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", compact):
        raise Unusable("is not an IBAN")
    digits = "".join(str(int(ch, 36)) for ch in compact[4:] + compact[:4])
    if int(digits) % 97 != 1:
        raise Unusable("fails the IBAN check digits")
    return compact


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise Unusable("is not a number")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise Unusable("is not a number") from exc
    if not number.is_finite():
        raise Unusable("is not a finite number")
    return number


def _email(value: Any) -> str:
    if not isinstance(value, str) or not value or any(
        ch.isspace() or unicodedata.category(ch).startswith("C") for ch in value
    ):
        raise Unusable("is not an email address")
    local, at, domain = value.rpartition("@")
    if not at or not local or not domain:
        raise Unusable("is not an email address")
    try:
        domain = domain.rstrip(".").lower().encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise Unusable("has a domain that is not valid") from exc
    return f"{local}@{domain}"


def canonical_value(kind: str, value: Any) -> Any:
    """``value`` as the kind compares it, or :class:`Unusable`."""
    from jarviscore.evidence.journal import canonical

    if kind == "exact":
        return canonical(value)
    if kind == "id":
        if value is None or isinstance(value, (bool, dict, list, float)):
            raise Unusable("is not an identifier")
        return str(value)
    if kind == "text":
        if not isinstance(value, str):
            raise Unusable("is not text")
        return unicodedata.normalize("NFC", value)
    if kind == "iban":
        return _iban(value)
    if kind in _NUMERIC:
        return _decimal(value)
    if kind == "email":
        return _email(value)
    raise Unusable(f"has an unknown kind {kind!r}")


def _value_digest(value: Any) -> str:
    from jarviscore.evidence.journal import digest

    return digest(str(value.normalize()) if isinstance(value, Decimal) else value)


# ── Paths into JSON ─────────────────────────────────────────────────────────


def _tokens(path: str) -> List[str]:
    path = re.sub(r"\[(\*|\d+)\]", r".\1", path)
    return [token for token in path.split(".") if token != ""]


def resolve(scope: Dict[str, Any], expression: str) -> List[Any]:
    """Every value ``expression`` names in ``scope``; ``[*]`` expands a list."""
    found = [scope]
    for token in _tokens(expression):
        following = []
        for value in found:
            if token == "*":
                if isinstance(value, list):
                    following.extend(value)
            elif isinstance(value, dict):
                if token in value:
                    following.append(value[token])
            elif isinstance(value, list) and token.isdigit():
                index = int(token)
                if index < len(value):
                    following.append(value[index])
        found = following
    return found


@functools.lru_cache(maxsize=1024)
def _template(path: str) -> Tuple["re.Pattern[str]", Tuple[str, ...]]:
    """``/invoices/{id}`` as a pattern over request paths, and its variable names."""
    path = "/" + path.strip().strip("/")
    parts = re.split(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", path)
    names = parts[1::2]
    if len(set(names)) != len(names):
        raise ValueError(f"path {path!r} names a variable twice")
    if any("{" in literal or "}" in literal for literal in parts[0::2]):
        raise ValueError(f"path {path!r} has a brace that is not a {{variable}}")
    pattern = "".join(
        re.escape(part) if index % 2 == 0 else f"(?P<{part}>[^/]+)"
        for index, part in enumerate(parts)
    )
    return re.compile(f"^{pattern}/?$"), tuple(names)


def _path_params(pattern: "re.Pattern[str]", path: str) -> Optional[Dict[str, str]]:
    found = pattern.match(path)
    if found is None:
        return None
    return {name: unquote(value) for name, value in found.groupdict().items()}


# ── The request as it will leave ────────────────────────────────────────────


@dataclass(frozen=True)
class Request:
    method: str
    host: str
    path: str
    query: Dict[str, Any]
    json: Any = None
    form: Optional[Dict[str, Any]] = None
    #: The body is sent in a form grounding cannot read (raw content, files).
    opaque: bool = False

    def view(self) -> Dict[str, Any]:
        view: Dict[str, Any] = {"query": self.query}
        if self.json is not None:
            view["json"] = self.json
        if self.form is not None:
            view["form"] = self.form
        return view


def request_from(method: str, url: str, kwargs: Dict[str, Any]) -> Request:
    """The request httpx will send for ``method``, ``url`` and its keyword arguments."""
    parts = urlsplit(url)
    pairs = list(parse_qsl(parts.query, keep_blank_values=True))
    params = kwargs.get("params")
    if isinstance(params, dict):
        for key, value in params.items():
            pairs.extend((str(key), item) for item in (value if isinstance(value, (list, tuple)) else [value]))
    elif isinstance(params, (list, tuple)):
        pairs.extend((str(key), value) for key, value in params)
    query: Dict[str, Any] = {}
    for key, value in pairs:
        query[key] = [*query[key], value] if isinstance(query.get(key), list) else (
            [query[key], value] if key in query else value
        )
    content, data, files, body = (kwargs.get(name) for name in ("content", "data", "files", "json"))
    opaque = content is not None or bool(files) or (data is not None and not isinstance(data, dict))
    form = data if isinstance(data, dict) and data and not opaque else None
    json_body = body if not opaque and form is None else None
    return Request(
        method=method.upper(), host=parts.netloc.lower(), path=parts.path or "/",
        query=query, json=json_body, form=form, opaque=opaque,
    )


# ── Rules ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Source:
    """One record a rule follows: read from ``provider`` at ``path``, selected by ``where``."""

    name: str
    provider: str
    path: str
    where: Tuple[Tuple[str, str], ...]
    #: Where the record sits in the response (dot path), or the list of records.
    record: str = ""
    items: str = ""
    key: str = "id"

    @property
    def pattern(self) -> "re.Pattern[str]":
        return _template(self.path)[0]

    @property
    def variables(self) -> Tuple[str, ...]:
        return _template(self.path)[1]


@dataclass(frozen=True)
class Check:
    field: str
    relation: str
    reference: str
    kind: str = "exact"


@dataclass(frozen=True)
class GroundingRule:
    name: str
    match: Tuple[Tuple[str, Any], ...] = ()
    bind: Tuple[Source, ...] = ()
    require: Tuple[Check, ...] = ()
    selectors_from: Tuple[str, ...] = SELECTOR_ORIGINS
    other_fields: str = "allow"
    fresh: str = "run"
    max_age_seconds: Optional[float] = None
    #: Why the rule could not be read; a broken rule refuses every call it matches.
    invalid: str = ""

    def applies(self, provider: str, atom: Optional[str], request: Request) -> bool:
        for key, wanted in self.match:
            options = wanted if isinstance(wanted, list) else [wanted]
            if key in ("provider", "system"):
                if provider not in [str(o).lower() for o in options]:
                    return False
            elif key == "method":
                if request.method not in [str(o).upper() for o in options]:
                    return False
            elif key == "atom":
                if atom not in options:
                    return False
            elif key == "host":
                if request.host not in [str(o).lower() for o in options]:
                    return False
            elif key == "path":
                if not any(_path_params(_template(str(o))[0], request.path) is not None for o in options):
                    return False
        return True

    def path_params(self, request: Request) -> Dict[str, str]:
        for key, wanted in self.match:
            if key == "path":
                for option in wanted if isinstance(wanted, list) else [wanted]:
                    found = _path_params(_template(str(option))[0], request.path)
                    if found is not None:
                        return found
        return {}


def parse_rule(entry: Dict[str, Any], index: int) -> GroundingRule:
    """A rule from its policy entry. A rule that cannot be read refuses what it matches."""
    name = str((entry or {}).get("name") or f"grounding-{index}")
    match = (entry or {}).get("match") or {}
    if not isinstance(match, dict) or set(match) - {"provider", "system", "method", "atom", "host", "path"}:
        raise ValueError(f"grounding rule {name!r}: match takes provider, method, atom, host and path")
    rule = GroundingRule(name=name, match=tuple(sorted(match.items())))
    try:
        return _parse_body(rule, entry)
    except (ValueError, TypeError, KeyError, re.error) as exc:
        return GroundingRule(name=name, match=rule.match, invalid=str(exc))


def _parse_body(rule: GroundingRule, entry: Dict[str, Any]) -> GroundingRule:
    for _, value in rule.match:
        if isinstance(value, (dict, type(None))):
            raise ValueError("match values are strings or lists of strings")
    for key, value in rule.match:
        if key == "path":
            for option in value if isinstance(value, list) else [value]:
                _template(str(option))
    selectors_from = tuple(str(o) for o in entry.get("selectors_from") or SELECTOR_ORIGINS)
    if not selectors_from or set(selectors_from) - set(SELECTOR_ORIGINS):
        raise ValueError("selectors_from takes input and request")
    other_fields = str(entry.get("other_fields") or "allow")
    fresh = str(entry.get("fresh") or "run")
    if other_fields not in ("allow", "deny") or fresh not in ("run", "reread"):
        raise ValueError("other_fields is allow or deny; fresh is run or reread")
    max_age = entry.get("max_age_seconds")
    if max_age is not None and (isinstance(max_age, bool) or float(max_age) <= 0):
        raise ValueError("max_age_seconds is a positive number")
    names: List[str] = []
    sources: List[Source] = []
    for item in entry.get("bind") or []:
        source_name = str(item["name"])
        if source_name in ("request", "input") or source_name in names or not re.fullmatch(r"[A-Za-z_]\w*", source_name):
            raise ValueError(f"binding {source_name!r} needs a new name other than request and input")
        read = item["read"]
        where = item.get("where") or {}
        if not isinstance(where, dict) or not where:
            raise ValueError(f"binding {source_name!r} says which record by where")
        source = Source(
            name=source_name,
            provider=str(read["provider"]).lower(),
            path=str(read["path"]),
            where=tuple((str(k), str(v)) for k, v in where.items()),
            record=str(read.get("record") or ""),
            items=str(read.get("items") or ""),
            key=str(read.get("key") or "id"),
        )
        _template(source.path)
        for _, expression in source.where:
            root = _tokens(expression)[0] if _tokens(expression) else ""
            if root in ("request", "input"):
                if root not in selectors_from:
                    raise ValueError(f"binding {source_name!r} selects by {root}, which selectors_from excludes")
            elif root not in names:
                raise ValueError(f"binding {source_name!r} selects by {expression!r}, which names nothing bound before it")
        if fresh == "reread" and set(source.variables) - {k for k, _ in source.where}:
            raise ValueError(f"binding {source_name!r} cannot be re-read: its path is not fully selected")
        names.append(source_name)
        sources.append(source)
    checks: List[Check] = []
    for item in entry.get("require") or []:
        relations = [r for r in RELATIONS if r in item]
        if len(relations) != 1:
            raise ValueError("each requirement names one of equals, one_of, at_most")
        target = str(item["field"])
        if not target.startswith("request."):
            raise ValueError(f"requirement field {target!r} is a field of the request")
        reference = str(item[relations[0]])
        root = _tokens(reference)[0] if _tokens(reference) else ""
        if root not in names and root != "input":
            raise ValueError(f"requirement {target!r} refers to {reference!r}, which names nothing bound")
        kind = str(item.get("as") or "exact")
        if kind not in KINDS:
            raise ValueError(f"requirement {target!r}: as is one of {', '.join(KINDS)}")
        if relations[0] == "at_most" and kind not in _NUMERIC:
            raise ValueError(f"requirement {target!r}: at_most compares money or number")
        checks.append(Check(field=target, relation=relations[0], reference=reference, kind=kind))
    if not checks:
        raise ValueError("a grounding rule requires at least one field")
    return GroundingRule(
        name=rule.name, match=rule.match, bind=tuple(sources), require=tuple(checks),
        selectors_from=selectors_from, other_fields=other_fields, fresh=fresh,
        max_age_seconds=float(max_age) if max_age is not None else None,
    )


# ── Observations: what the broker itself read ───────────────────────────────


@dataclass(frozen=True)
class Observation:
    order: int
    at: float
    provider: str
    host: str
    path: str
    body: Any
    digest: str
    #: The journal event that recorded the response: run, seq, hash.
    ref: Optional[Dict[str, Any]] = None


class Observations:
    """Per-workflow record of provider responses the broker received, and what the run changed."""

    def __init__(self, max_workflows: int = 256, max_reads: int = 512):
        self._lock = threading.Lock()
        self._order = itertools.count()
        self._reads: "collections.OrderedDict[str, collections.deque]" = collections.OrderedDict()
        self._writes: Dict[str, List[Tuple[int, str, str]]] = {}
        self.max_workflows = max_workflows
        self.max_reads = max_reads

    def _touch(self, workflow: str) -> "collections.deque":
        reads = self._reads.get(workflow)
        if reads is None:
            reads = self._reads[workflow] = collections.deque(maxlen=self.max_reads)
            while len(self._reads) > self.max_workflows:
                dropped, _ = self._reads.popitem(last=False)
                self._writes.pop(dropped, None)
        else:
            self._reads.move_to_end(workflow)
        return reads

    def record_read(self, workflow: str, provider: str, host: str, path: str, body: Any,
                    digest: str, ref: Optional[Dict[str, Any]] = None) -> Observation:
        with self._lock:
            observation = Observation(next(self._order), time.time(), provider, host, path, body, digest, ref)
            self._touch(workflow).append(observation)
            return observation

    def record_change(self, workflow: str, provider: str, path: str) -> None:
        with self._lock:
            self._touch(workflow)
            self._writes.setdefault(workflow, []).append((next(self._order), provider, path))

    def reads(self, workflow: str, provider: str) -> List[Observation]:
        with self._lock:
            return [o for o in self._reads.get(workflow, ()) if o.provider == provider]

    def changed_before(self, workflow: str, observation: Observation) -> bool:
        """Whether this workflow changed what ``observation`` read before reading it."""
        with self._lock:
            writes = list(self._writes.get(workflow, ()))
        path = observation.path.rstrip("/") or "/"
        for order, provider, written in writes:
            written = written.rstrip("/") or "/"
            if order < observation.order and provider == observation.provider and (
                written == path or path.startswith(written + "/") or written.startswith(path + "/")
                or written == "/"
            ):
                return True
        return False

    def clear(self) -> None:
        with self._lock:
            self._reads.clear()
            self._writes.clear()


OBSERVATIONS = Observations()


# ── Caller input ────────────────────────────────────────────────────────────

_input_resolver: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None


def set_input_resolver(resolver: Optional[Callable[[str], Optional[Dict[str, Any]]]]) -> None:
    """Where the caller's structured input for a workflow comes from, when not the mesh's store."""
    global _input_resolver
    _input_resolver = resolver


def workflow_input(workflow: str) -> Optional[Dict[str, Any]]:
    """The structured context the caller submitted the workflow with, from the durable record."""
    if _input_resolver is not None:
        return _input_resolver(workflow)
    from jarviscore.orchestration.budget import current_workflow_budget

    account = current_workflow_budget()
    store = getattr(account, "store", None)
    lookup = getattr(store, "get_workflow_goal", None)
    if account is None or getattr(account, "workflow_id", None) != workflow or not callable(lookup):
        return None
    try:
        goal = lookup(workflow)
    except Exception:  # noqa: BLE001 - no input means selectors from input do not resolve
        return None
    context = (goal or {}).get("context")
    return context if isinstance(context, dict) else None


# ── Deciding ────────────────────────────────────────────────────────────────


@dataclass
class Grounding:
    """The outcome of every rule that applied to one call."""

    grounded: bool
    reason: str = ""
    rules: List[str] = field(default_factory=list)
    checks: List[Dict[str, Any]] = field(default_factory=list)
    citations: List[Dict[str, Any]] = field(default_factory=list)

    def record(self) -> Dict[str, Any]:
        return {
            "grounded": self.grounded,
            "rules": self.rules,
            "reason": self.reason,
            "checks": self.checks,
            "citations": self.citations,
        }


Fetch = Callable[[Source, Dict[str, str], str], Awaitable[None]]


def _records(source: Source, observation: Observation) -> List[Tuple[str, Any]]:
    """(identity, record) pairs one response holds for ``source``."""
    body = observation.body
    if source.record:
        found = resolve({"r": body}, "r." + source.record)
        body = found[0] if len(found) == 1 else None
    if not source.items:
        return [(observation.path, body)] if isinstance(body, dict) else []
    found = resolve({"r": body}, "r." + source.items)
    items = found[0] if len(found) == 1 and isinstance(found[0], list) else []
    pairs = []
    for item in items:
        if isinstance(item, dict):
            keys = resolve(item, source.key)
            identity = f"{observation.path}#{keys[0]}" if len(keys) == 1 else f"{observation.path}#?{id(item)}"
            pairs.append((identity, item))
    return pairs


def _origin(expression: str, origins: Dict[str, str]) -> str:
    root = _tokens(expression)[0] if _tokens(expression) else ""
    return root if root in ("request", "input") else origins.get(root, "request")


def _one(values: List[Any], what: str) -> Any:
    if not values:
        raise Unusable(f"{what} is missing")
    if len(values) > 1:
        raise Unusable(f"{what} has several values")
    return values[0]


async def _ground_rule(
    rule: GroundingRule, request: Request, workflow: str, inputs: Optional[Dict[str, Any]],
    observations: Observations, fetch: Optional[Fetch], grounding: Grounding,
) -> None:
    grounding.rules.append(rule.name)

    def fail(reason: str) -> None:
        grounding.grounded = False
        reason = f"{rule.name}: {reason}"
        grounding.reason = f"{grounding.reason}; {reason}" if grounding.reason else reason

    if rule.invalid:
        fail(f"the rule could not be read ({rule.invalid})")
        return
    if request.opaque:
        fail("the call sends its body in a form grounding cannot read")
        return
    scope: Dict[str, Any] = {"request": {**request.view(), "path": rule.path_params(request)}}
    if inputs is not None:
        scope["input"] = inputs
    origins: Dict[str, str] = {}
    now = time.time()
    for source in rule.bind:
        selectors: Dict[str, str] = {}
        try:
            for name, expression in source.where:
                selectors[name] = canonical_value("id", _one(resolve(scope, expression), f"which {source.name} ({expression})"))
        except Unusable as exc:
            fail(f"the call does not say which {source.name}: {exc}")
            return
        # A record is the model's choice if anything that selected it was.
        chosen_by = {_origin(expression, origins) for _, expression in source.where}
        origins[source.name] = "request" if "request" in chosen_by else "input"
        if rule.fresh == "reread" and fetch is not None:
            reads = observations.reads(workflow, source.provider)
            host = next((o.host for o in reversed(reads) if source.pattern.match(o.path)), request.host)
            try:
                await fetch(source, selectors, host)
            except Exception as exc:  # noqa: BLE001 - an unreadable source grounds nothing
                fail(f"{source.name} could not be read again before acting ({type(exc).__name__})")
                return
        latest: Dict[str, Tuple[Observation, Any]] = {}
        changed = False
        for observation in observations.reads(workflow, source.provider):
            params = _path_params(source.pattern, observation.path)
            if params is None:
                continue
            if rule.max_age_seconds is not None and now - observation.at > rule.max_age_seconds:
                continue
            if observations.changed_before(workflow, observation):
                changed = True
                continue
            for identity, record in _records(source, observation):
                if all(
                    _selected(name, wanted, params, record)
                    for name, wanted in selectors.items()
                ):
                    latest[identity] = (observation, record)
        if not latest:
            fail(
                f"no {source.name} matching {selectors} was read from {source.provider} in this run"
                + (" (only after this run changed it)" if changed else "")
            )
            return
        if len(latest) > 1:
            fail(f"{len(latest)} different {source.name} records match {selectors}")
            return
        observation, record = next(iter(latest.values()))
        scope[source.name] = record
        grounding.citations.append({
            "rule": rule.name,
            "binding": source.name,
            "provider": source.provider,
            "path": observation.path,
            "selected_by": origins[source.name],
            "observed": observation.digest,
            **({"event": observation.ref} if observation.ref else {}),
        })
    referenced = set()
    for check in rule.require:
        referenced.add(check.field)
        outcome = {"rule": rule.name, "field": check.field, check.relation: check.reference, "as": check.kind}
        try:
            actual = canonical_value(check.kind, _one(resolve(scope, check.field), check.field))
            outcome["value"] = _value_digest(actual)
            expected = resolve(scope, check.reference)
            if check.relation == "one_of":
                if len(expected) == 1 and isinstance(expected[0], list):
                    expected = expected[0]
                if not expected:
                    raise Unusable(f"{check.reference} is missing")
                allowed = [canonical_value(check.kind, value) for value in expected]
                ok = actual in allowed
            else:
                reference = canonical_value(check.kind, _one(expected, check.reference))
                ok = actual == reference if check.relation == "equals" else actual <= reference
        except Unusable as exc:
            outcome.update(ok=False, reason=str(exc))
            fail(f"{check.field}: {exc}")
        else:
            outcome["ok"] = ok
            if not ok:
                word = {"equals": "is not", "one_of": "is not one of", "at_most": "is more than"}[check.relation]
                fail(f"{check.field} {word} {check.reference}")
        grounding.checks.append(outcome)
    if rule.other_fields == "deny":
        for _, expression in itertools.chain(*(s.where for s in rule.bind)):
            referenced.add(expression)
        for part, body in (("json", request.json), ("form", request.form)):
            if isinstance(body, dict):
                extra = sorted(k for k in body if f"request.{part}.{k}" not in referenced)
                if extra:
                    fail(f"the call also sends {', '.join(extra)}, which no requirement grounds")
            elif body is not None:
                fail(f"the call's {part} body is not an object, so its fields cannot be grounded")


def _selected(name: str, wanted: str, params: Dict[str, str], record: Any) -> bool:
    if name in params:
        return params[name] == wanted
    values = resolve(record, name) if isinstance(record, dict) else []
    try:
        return len(values) == 1 and canonical_value("id", values[0]) == wanted
    except Unusable:
        return False


async def ground(
    rules: List[GroundingRule], request: Request, workflow: str, *,
    inputs: Optional[Dict[str, Any]] = None,
    observations: Optional[Observations] = None,
    fetch: Optional[Fetch] = None,
) -> Grounding:
    """Hold ``request`` to every rule; grounded only if every one holds."""
    grounding = Grounding(grounded=True)
    for rule in rules:
        await _ground_rule(rule, request, workflow, inputs, observations or OBSERVATIONS, fetch, grounding)
    return grounding


def rules_for(rules: Tuple[GroundingRule, ...], provider: str) -> List[GroundingRule]:
    """The rules that could apply to a call to ``provider``."""
    found = []
    for rule in rules:
        named = [value for key, value in rule.match if key in ("provider", "system")]
        options = [str(o).lower() for value in named for o in (value if isinstance(value, list) else [value])]
        if not named or (provider or "").lower() in options:
            found.append(rule)
    return found


def sources_matching(rules: Tuple[GroundingRule, ...], provider: str, path: str) -> bool:
    """Whether a read of ``path`` from ``provider`` could ground some rule, so it is kept."""
    return any(
        source.provider == provider and source.pattern.match(path)
        for rule in rules for source in rule.bind
    )


def fill(source: Source, selectors: Dict[str, str]) -> str:
    """The path of the record ``selectors`` pick, for reading it again."""
    from urllib.parse import quote

    path = "/" + source.path.strip().strip("/")
    for name in source.variables:
        path = path.replace("{" + name + "}", quote(selectors[name], safe=""))
    return path
