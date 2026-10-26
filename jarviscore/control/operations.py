"""What an atom can do to its provider, read from its own code.

An atom's declared effect (``ATOM_POLICY``) is a claim by its author. The
contract here is the set of HTTP operations its code can actually send through
``nexus_call``: method plus URL template, followed through module constants,
local variables and one level of helper calls, from the atom's entry function.
The provider broker checks every call against it, so an atom that says it reads
cannot delete, and one that says it writes cannot send what its code does not.

A template a static read cannot pin down (a URL built at run time, a method in a
variable) leaves the contract *unverified*. Calls through such an atom are still
held to the methods its declared effect allows, and are recorded as unverified.
"""
from __future__ import annotations

import ast
import collections
import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
EFFECT_ORDER = ("read", "propose", "write", "notify", "destructive")

_WILD = "\x00"
_MAX_DEPTH = 6


@dataclass(frozen=True)
class Operation:
    """One HTTP operation an atom's code can send."""

    method: str
    template: str  # "*" marks a span the code fills at run time

    @property
    def bounded(self) -> bool:
        """Whether the template pins a literal path, not only a host or root."""
        path = re.sub(r"^https?://[^/*]+", "", self.template)
        return bool(re.search(r"/[A-Za-z_]", path.replace("*", "")))

    def matches(self, method: str, url: str) -> bool:
        return method.upper() == self.method and _template_regex(self.template).fullmatch(
            _normalised(url)
        ) is not None


@dataclass(frozen=True)
class OperationContract:
    """Every operation an atom's code can send, and whether that set is fully known."""

    operations: FrozenSet[Operation]
    complete: bool  # False when some call site could not be read statically

    @property
    def verified(self) -> bool:
        """True when the set is complete and every operation is pinned to a literal path."""
        return self.complete and bool(self.operations) and all(op.bounded for op in self.operations)

    def allows(self, method: str, url: str) -> bool:
        return any(op.matches(method, url) for op in self.operations)

    def as_dict(self) -> Dict[str, object]:
        return {
            "operations": sorted(f"{op.method} {op.template}" for op in self.operations),
            "complete": self.complete,
            "verified": self.verified,
        }


def _normalised(url: str) -> str:
    """The URL a template is matched against: no query or fragment, no trailing slash."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return f"{parts.scheme}://{parts.netloc}{path}" if parts.scheme else path


@lru_cache(maxsize=4096)
def _template_regex(template: str) -> "re.Pattern[str]":
    """A leading run-time span is the provider's root; a later one is one or more path characters."""
    trimmed = template.split("?", 1)[0].rstrip("/") or "/"
    pieces = trimmed.split("*")
    pattern = []
    for index, piece in enumerate(pieces):
        pattern.append(re.escape(piece))
        if index < len(pieces) - 1:
            pattern.append(r".*" if index == 0 and piece == "" else r"[^?#]+")
    return re.compile("".join(pattern))


def _module_values(tree: ast.Module) -> Dict[str, ast.expr]:
    values: Dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id] = node.value
    return values


def _local_values(fn: ast.AST) -> Dict[str, List[ast.expr]]:
    values: Dict[str, List[ast.expr]] = collections.defaultdict(list)
    for node in _own_nodes(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id].append(node.value)
    return values


def _render(node: Optional[ast.expr], lookup: Callable[[str], object], depth: int = 0) -> str:
    """The string an expression builds, with ``_WILD`` where the value is only known at run time."""
    if node is None or depth > _MAX_DEPTH:
        return _WILD
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(part.value) if isinstance(part, ast.Constant) else _render(part.value, lookup, depth + 1)
            for part in node.values
        )
    if isinstance(node, ast.Name):
        value = lookup(node.id)
        if isinstance(value, str):
            return value
        return _render(value, lookup, depth + 1) if isinstance(value, ast.expr) else _WILD
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _render(node.left, lookup, depth + 1) + _render(node.right, lookup, depth + 1)
    return _WILD


def _own_nodes(fn: ast.AST):
    """Every node in ``fn``'s own body; a nested function is its own scope, reached only if called."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _parents(fn: ast.AST) -> Dict[int, ast.AST]:
    parents: Dict[int, ast.AST] = {}
    for node in _own_nodes(fn):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    for child in ast.iter_child_nodes(fn):
        parents[id(child)] = fn
    return parents


def _literal_test(test: ast.expr, bound: Dict[str, str]) -> Optional[bool]:
    """The value of a branch test on a bound literal argument, or None when it is not known."""
    if (
        isinstance(test, ast.Compare) and len(test.ops) == 1
        and isinstance(test.left, ast.Name) and test.left.id in bound
        and _WILD not in bound[test.left.id]
    ):
        value, (op,), (right,) = bound[test.left.id], test.ops, test.comparators
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            if isinstance(op, ast.Eq):
                return value == right.value
            if isinstance(op, ast.NotEq):
                return value != right.value
        if isinstance(right, (ast.Tuple, ast.List, ast.Set)) and all(
            isinstance(e, ast.Constant) for e in right.elts
        ):
            members = {e.value for e in right.elts}
            if isinstance(op, ast.In):
                return value in members
            if isinstance(op, ast.NotIn):
                return value not in members
    return None


def _feasible(site: ast.AST, parents: Dict[int, ast.AST], bound: Dict[str, str]) -> bool:
    """Whether the branches around ``site`` can all be taken with these argument values."""
    node = site
    while id(node) in parents:
        parent = parents[id(node)]
        if isinstance(parent, ast.If):
            known = _literal_test(parent.test, bound)
            if known is not None:
                in_body = any(node is child for child in parent.body)
                in_else = any(node is child for child in parent.orelse)
                if (in_body and not known) or (in_else and known):
                    return False
        node = parent
    return True


def _names(node: ast.AST) -> set:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _template(rendered: str) -> str:
    return re.sub(f"{_WILD}+", _WILD, rendered).replace(_WILD, "*")


def _reachable(functions: Dict[str, ast.AST], entry: str) -> set:
    if entry not in functions:
        return set(functions)
    seen, stack = set(), [entry]
    while stack:
        name = stack.pop()
        if name in seen or name not in functions:
            continue
        seen.add(name)
        for node in _own_nodes(functions[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions:
                stack.append(node.func.id)
    return seen


def read_operations(source: str, entry: str = "") -> OperationContract:
    """The operations ``source`` can send through ``nexus_call``, starting from ``entry``."""
    return _read_operations(hashlib.sha256(source.encode()).hexdigest(), source, entry)


@lru_cache(maxsize=2048)
def _read_operations(_digest: str, source: str, entry: str) -> OperationContract:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return OperationContract(frozenset(), False)
    module = _module_values(tree)
    functions = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    callers: Dict[str, List[ast.Call]] = collections.defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in functions:
            callers[node.func.id].append(node)
    # A nested helper reads its enclosing function's variables (closures).
    enclosing: Dict[str, str] = {}
    for name, fn in functions.items():
        for node in _own_nodes(fn):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing[node.name] = name
    locals_of = {name: _local_values(fn) for name, fn in functions.items()}

    operations = set()
    complete = True
    for name in _reachable(functions, entry):
        fn = functions[name]
        params = [arg.arg for arg in fn.args.args]
        local = locals_of[name]
        parents = _parents(fn)
        scopes = [local]
        outer = enclosing.get(name)
        while outer is not None:
            scopes.append(locals_of[outer])
            outer = enclosing.get(outer)

        def lookup_with(bound: Dict[str, str], scopes=scopes):
            def lookup(key: str):
                if key in bound:
                    return bound[key]
                for scope in scopes:
                    if key in scope:
                        return scope[key][0] if len(scope[key]) == 1 else None
                return module.get(key)
            return lookup

        for site in _own_nodes(fn):
            if not (
                isinstance(site, ast.Call) and isinstance(site.func, ast.Name)
                and site.func.id == "nexus_call" and len(site.args) >= 2
            ):
                continue
            method_node = site.args[0]
            method = (
                method_node.value.upper()
                if isinstance(method_node, ast.Constant) and isinstance(method_node.value, str)
                else None
            )
            if method not in HTTP_METHODS:
                complete = False
                continue
            used = _names(site.args[1])
            for value in [v for key in list(used) for v in local.get(key, ())]:
                used |= _names(value)
            node = site
            while id(node) in parents:
                node = parents[id(node)]
                if isinstance(node, ast.If):
                    used |= _names(node.test)
            path_params = [p for p in params if p in used]
            sites = callers.get(name) or []
            if path_params and sites:
                for call in sites:
                    bound = {}
                    for index, param in enumerate(params):
                        if param not in path_params:
                            continue
                        arg = call.args[index] if index < len(call.args) else next(
                            (kw.value for kw in call.keywords if kw.arg == param), None
                        )
                        bound[param] = _render(arg, module.get)
                    if _feasible(site, parents, bound):
                        operations.add(Operation(method, _template(_render(site.args[1], lookup_with(bound)))))
            else:
                operations.add(Operation(method, _template(_render(site.args[1], lookup_with({})))))
    return OperationContract(frozenset(operations), complete)


def effect_rank(effect: str) -> int:
    return EFFECT_ORDER.index(effect) if effect in EFFECT_ORDER else len(EFFECT_ORDER)


def method_floor(method: str) -> str:
    """The least effect an HTTP method can have, before a contract says what the call is."""
    method = method.upper()
    if method in READ_METHODS:
        return "read"
    if method == "DELETE":
        return "destructive"
    return "write"


def method_within_effect(
    method: str, declared: str, contract: Optional[OperationContract], url: str
) -> bool:
    """Whether a call's method stays within the effect its atom declared.

    A read atom may POST only to a POST its own verified contract names (search
    and query endpoints). Nothing that reads may PUT, PATCH or DELETE, and only
    a destructive atom may DELETE.
    """
    floor = method_floor(method)
    if effect_rank(floor) <= effect_rank(declared):
        return True
    if declared in {"read", "propose"} and method.upper() == "POST":
        return bool(contract and contract.verified and contract.allows(method, url))
    return False


def describe(url: str) -> Tuple[str, str]:
    """(host, path) of a call, for records that must not carry query strings."""
    parts = urlsplit(url)
    return parts.netloc.lower(), parts.path or "/"
