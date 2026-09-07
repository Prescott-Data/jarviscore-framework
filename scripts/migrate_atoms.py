"""Migrate shipped atoms from the `auth_info` shape to `nexus_call`.

Most atoms delegate to per-provider helpers: one builds headers from
`auth_info`, another wraps `requests`. So this rewrites the whole module, not
just the atom function:

  * request helpers become async wrappers around `nexus_call`
  * auth helpers lose the credential and keep the headers that are not auth
  * every caller of a now-async helper becomes async, to a fixpoint
  * `resp.status_code` / `.text` / `.json()` become keys on the response dict

Anything it cannot read with certainty is reported and left untouched, because a
silently mangled atom is worse than one that still needs work.

    python migrate_atoms.py                    # dry run, prints a report
    python migrate_atoms.py --only hubspot     # limit to some providers
    python migrate_atoms.py --write            # rewrite the files
"""
from __future__ import annotations

import argparse
import ast
import collections
import pathlib
import sys

ROOT = pathlib.Path("jarviscore/integrations/atoms")

#: `requests` response attributes and the response-dict keys that replace them.
RESPONSE_KEYS = {"text": "body", "content": "content", "status_code": "status_code",
                 "headers": "headers", "ok": "ok", "json": "json"}

HTTP_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}

#: Dropped because the call proxy owns them.
PROXY_OWNED = {"timeout", "verify", "auth", "allow_redirects", "stream", "cert"}


class Skip(Exception):
    """This atom cannot be migrated mechanically."""


def _requests_verb(node) -> str | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    target = node.func.value
    if isinstance(target, ast.Name) and target.id == "requests":
        return node.func.attr
    return None


def _mentions(node, *names: str) -> bool:
    wanted = set(names)
    return any(isinstance(sub, ast.Name) and sub.id in wanted for sub in ast.walk(node))


def _called_names(node) -> set[str]:
    return {sub.func.id for sub in ast.walk(node)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)}


def _is_request_helper(fn) -> bool:
    """A helper that returns one `requests.<verb>(...)` call, so callers get a response."""
    calls = [n for n in ast.walk(fn) if _requests_verb(n)]
    if len(calls) != 1:
        return False
    if _requests_verb(calls[0]) not in HTTP_VERBS | {"request"}:
        return False
    return any(isinstance(n, ast.Return) and n.value is calls[0] for n in ast.walk(fn))


def _nexus_call(verb: str, url, keywords) -> ast.Await:
    kept = [k for k in keywords if k.arg not in PROXY_OWNED and k.arg is not None]
    return ast.Await(value=ast.Call(
        func=ast.Name(id="nexus_call", ctx=ast.Load()),
        args=[ast.Constant(verb.upper()), url],
        keywords=kept,
    ))


class Rewriter(ast.NodeTransformer):
    """Rewrite requests calls, response attribute access, and helper awaits."""

    def __init__(self, response_names: set[str], async_helpers: set[str],
                 stripped: dict[str, int]):
        self.response_names = response_names
        self.async_helpers = async_helpers
        self.stripped = stripped
        self.in_atom = False
        self.calls = 0

    def _rebuilds_headers(self, keyword) -> bool:
        """`headers=dict(resp.request.headers)` copies auth the proxy now owns."""
        return any(
            isinstance(sub, ast.Attribute) and sub.attr == "request"
            and isinstance(sub.value, ast.Name) and sub.value.id in self.response_names
            for sub in ast.walk(keyword.value)
        )

    def visit_Import(self, node):
        remaining = [alias for alias in node.names if alias.name != "requests"]
        return ast.Import(names=remaining) if remaining else None

    def visit_ImportFrom(self, node):
        return None if node.module == "requests" else node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        if isinstance(node.value, ast.Name) and node.value.id in self.response_names:
            key = RESPONSE_KEYS.get(node.attr)
            if key is None:
                raise Skip(f"unhandled response attribute .{node.attr}")
            return ast.Subscript(value=node.value, slice=ast.Constant(key), ctx=node.ctx)
        return node

    def visit_Call(self, node):
        node.keywords = [k for k in node.keywords
                         if not (k.arg == "headers" and self._rebuilds_headers(k))]
        self.generic_visit(node)

        # `resp.json()` became `resp["json"]`; the call itself goes away.
        if isinstance(node.func, ast.Subscript) and not node.args and not node.keywords:
            return node.func

        verb = _requests_verb(node)
        if verb is not None:
            if verb == "request":
                # requests.request(method, url, ...) names the verb in an argument.
                if len(node.args) < 2:
                    raise Skip("requests.request() without method and url")
                self.calls += 1
                kept = [k for k in node.keywords
                        if k.arg not in PROXY_OWNED and k.arg is not None]
                return ast.Await(value=ast.Call(
                    func=ast.Name(id="nexus_call", ctx=ast.Load()),
                    args=[node.args[0], node.args[1]], keywords=kept,
                ))
            if verb not in HTTP_VERBS:
                raise Skip(f"unsupported requests.{verb}()")
            self.calls += 1
            return _nexus_call(verb, node.args[0], node.keywords)

        if isinstance(node.func, ast.Name) and node.func.id in self.stripped:
            index = self.stripped[node.func.id]
            if index < len(node.args):
                node.args = node.args[:index] + node.args[index + 1:]
            node.keywords = [k for k in node.keywords if k.arg != "auth_info"]

        if isinstance(node.func, ast.Name) and node.func.id in self.async_helpers:
            return ast.Await(value=node)
        return node

    def visit_Expr(self, node):
        call = node.value
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "raise_for_status"):
            # This was where the author checked the response, so the check stays
            # here rather than disappearing and leaving None to fail later.
            response = call.func.value
            failed = ast.UnaryOp(op=ast.Not(), operand=ast.Subscript(
                value=response, slice=ast.Constant("ok"), ctx=ast.Load()))
            body = ast.Subscript(value=response, slice=ast.Constant("body"),
                                 ctx=ast.Load())
            if self.in_atom:
                handler = ast.Return(value=ast.Dict(
                    keys=[ast.Constant("success"), ast.Constant("error")],
                    values=[ast.Constant(False), body]))
            else:
                handler = ast.Raise(exc=ast.Call(
                    func=ast.Name(id="RuntimeError", ctx=ast.Load()),
                    args=[body], keywords=[]), cause=None)
            return ast.If(test=failed, body=[handler], orelse=[])
        return self.generic_visit(node)

    def visit_Await(self, node):
        self.generic_visit(node)
        # Guard against double-awaiting a call already rewritten below.
        return node.value if isinstance(node.value, ast.Await) else node


#: What Nexus itself supplies. A read of one of these is satisfied after the
#: migration, because the call proxy attaches it. Anything else `auth_info`
#: carried was account configuration, which the caller has to pass instead.
CREDENTIAL_FIELDS = {
    "access_token", "refresh_token", "api_key", "api_token", "apikey", "token",
    "api_secret", "secret", "password", "username", "client_id", "client_secret",
    "session_token", "private_token", "key", "auth_token", "bearer",
}


def _credential_field(node) -> str | None:
    """The field name if this reads auth_info, else None."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in {"get", "pop"} \
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "auth_info":
        if node.args and isinstance(node.args[0], ast.Constant):
            return str(node.args[0].value)
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
            and node.value.id == "auth_info" and isinstance(node.slice, ast.Constant):
        return str(node.slice.value)
    return None


class _CredentialsArePresent(ast.NodeTransformer):
    """In a condition, a credential read is now true: the proxy supplies it."""

    def visit_Call(self, node):
        field = _credential_field(node)
        if field is not None and field.lower() in CREDENTIAL_FIELDS:
            return ast.Constant(True)
        self.generic_visit(node)
        return node

    def visit_Subscript(self, node):
        field = _credential_field(node)
        if field is not None and field.lower() in CREDENTIAL_FIELDS:
            return ast.Constant(True)
        self.generic_visit(node)
        return node

    def visit_Name(self, node):
        if node.id == "auth_info" and isinstance(node.ctx, ast.Load):
            return ast.Constant(True)
        return node


def _static_truth(node):
    """True, False, or None when the condition is not decidable here."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _static_truth(node.operand)
        return None if inner is None else not inner
    if isinstance(node, ast.BoolOp):
        values = [_static_truth(v) for v in node.values]
        if isinstance(node.op, ast.And):
            if any(v is False for v in values):
                return False
            return True if all(v is True for v in values) else None
        if any(v is True for v in values):
            return True
        return False if all(v is False for v in values) else None
    return None


class _PruneAuthDictEntries(ast.NodeTransformer):
    """Drop dict entries whose value comes from the credential, keep the rest."""

    def __init__(self, tainted: set[str]):
        self.tainted = tainted

    def visit_Dict(self, node):
        self.generic_visit(node)
        keys, values = [], []
        for key, value in zip(node.keys, node.values):
            if key is not None and _mentions(value, "auth_info", *self.tainted):
                continue
            keys.append(key)
            values.append(value)
        return ast.Dict(keys=keys, values=values)


class _AuthReadsToNone(ast.NodeTransformer):
    """`auth_info.get("x")` becomes None, so `a or auth_info.get("x") or b` still works.

    Each read is matched before descending, because rewriting the inner `auth_info`
    first would leave `None["domain"]` behind instead of `None`.
    """

    @staticmethod
    def _is_auth(node) -> bool:
        return isinstance(node, ast.Name) and node.id == "auth_info"

    def visit_Call(self, node):
        if (isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "pop"}
                and self._is_auth(node.func.value)):
            return ast.Constant(None)
        # requests.auth.HTTPBasicAuth(...) is a credential the proxy now applies.
        if (isinstance(node.func, ast.Attribute) and node.func.attr.startswith("HTTP")
                and node.func.attr.endswith("Auth")):
            return ast.Constant(None)
        self.generic_visit(node)
        return node

    def visit_Subscript(self, node):
        if self._is_auth(node.value):
            return ast.Constant(None)
        self.generic_visit(node)
        return node

    def visit_Attribute(self, node):
        if self._is_auth(node.value):
            return ast.Constant(None)
        self.generic_visit(node)
        return node

    def visit_Name(self, node):
        if node.id == "auth_info" and isinstance(node.ctx, ast.Load):
            return ast.Constant(None)
        return node


def _is_none(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _strip_credential(fn, require_return: bool = True) -> None:
    """Remove the credential from a helper, keeping everything that is not auth.

    `auth_info` carries two different things in the shipped corpus: the actual
    credential, and account configuration such as a Shopify shop domain or an
    Ads customer id that the atom already takes as a parameter. The first has to
    go, the second only loses its fallback.
    """
    tainted: set[str] = set()

    def clean_block(statements) -> list:
        cleaned = []
        for statement in statements:
            result = clean(statement)
            if result is None:
                continue
            cleaned.extend(result if isinstance(result, list) else [result])
            # Folding a credential check can leave the old failure path stranded
            # after a return, still naming auth_info in its message.
            if cleaned and isinstance(cleaned[-1], (ast.Return, ast.Raise)):
                break
        return cleaned

    def clean(node):
        node = _PruneAuthDictEntries(tainted).visit(node)
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "auth_info" for t in node.targets):
                return None
            if isinstance(node.value, ast.Dict):
                return node
            if _mentions(node.value, *tainted):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        tainted.add(target.id)
                return None
            if _mentions(node.value, "auth_info"):
                node.value = _AuthReadsToNone().visit(node.value)
                if _is_none(node.value):
                    # The whole value was the credential.
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            tainted.add(target.id)
                    return None
                return node
            if any(_mentions(t, *tainted) for t in node.targets):
                return None
            return node
        if isinstance(node, ast.If):
            if _mentions(node.test, *tainted):
                return clean_block(node.orelse)
            node.test = _CredentialsArePresent().visit(node.test)
            node.test = _AuthReadsToNone().visit(node.test)
            truth = _static_truth(node.test)
            if truth is True:
                return clean_block(node.body)
            if truth is False:
                return clean_block(node.orelse)
            node.body = clean_block(node.body) or [ast.Pass()]
            node.orelse = clean_block(node.orelse)
            return node
        if isinstance(node, (ast.Try, ast.For, ast.While, ast.With, ast.AsyncFor,
                            ast.AsyncWith)):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if block is not None:
                    setattr(node, field, clean_block(block))
            for handler in getattr(node, "handlers", []):
                handler.body = clean_block(handler.body) or [ast.Pass()]
            if not node.body:
                node.body = [ast.Pass()]
            return node
        if isinstance(node, ast.Return) and node.value is not None \
                and _mentions(node.value, *tainted):
            # Auth helpers return a tuple such as (headers, auth, error). Keep the
            # shape callers unpack and null only the part that was the credential.
            if isinstance(node.value, ast.Tuple):
                node.value.elts = [
                    ast.Constant(None) if _mentions(element, *tainted) else element
                    for element in node.value.elts
                ]
                return node
            return None
        if _mentions(node, *tainted):
            return None
        return _AuthReadsToNone().visit(node)

    kept = clean_block(fn.body)
    if require_return and not any(
            isinstance(s, ast.Return)
            for s in ast.walk(ast.Module(body=kept, type_ignores=[]))):
        raise Skip(f"`{fn.name}` has no return left once the credential is removed")
    fn.body = kept
    fn.args.args = [a for a in fn.args.args if a.arg != "auth_info"]


def _ensure_docstring(fn, provider: str) -> None:
    if ast.get_docstring(fn):
        return
    words = fn.name.split("_")
    action = " ".join(words[1:]) or fn.name
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "nexus_call" and len(node.args) >= 2):
            method, url = node.args[0], node.args[1]
            if isinstance(method, ast.Constant) and isinstance(url, ast.Constant):
                fn.body.insert(0, ast.Expr(value=ast.Constant(
                    f"{action.capitalize()}. {method.value} {url.value}")))
                return
            break
    fn.body.insert(0, ast.Expr(value=ast.Constant(
        f"{action.capitalize()} via the {provider} API.")))


def _to_async(fn):
    if isinstance(fn, ast.AsyncFunctionDef):
        return fn
    return ast.AsyncFunctionDef(
        name=fn.name, args=fn.args, body=fn.body,
        decorator_list=fn.decorator_list, returns=fn.returns, type_params=[],
    )


def _walk_own_scope(node):
    """Walk a statement without descending into nested function definitions."""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield from _walk_own_scope(child)


def _awaits_directly(fn) -> bool:
    """An await in this function's own body, not in a function nested inside it."""
    return any(isinstance(node, ast.Await)
               for statement in fn.body
               for node in _walk_own_scope(statement))


class _MakeAsync(ast.NodeTransformer):
    """Nested helpers await too, so they need to be async and awaited in turn."""

    def __init__(self):
        self.async_names: set[str] = set()
        self.changed = False

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        if _awaits_directly(node):
            self.async_names.add(node.name)
            self.changed = True
            return _to_async(node)
        return node

    def visit_AsyncFunctionDef(self, node):
        self.generic_visit(node)
        self.async_names.add(node.name)
        return node


class _AwaitCallsTo(ast.NodeTransformer):
    def __init__(self, names: set[str]):
        self.names = names
        self.changed = False

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id in self.names:
            self.changed = True
            return ast.Await(value=node)
        return node

    def visit_Await(self, node):
        self.generic_visit(node)
        return node.value if isinstance(node.value, ast.Await) else node


def _settle_async(module) -> None:
    """Make every function that awaits async, and await every call to one."""
    for _ in range(10):
        marker = _MakeAsync()
        module = marker.visit(module) or module
        awaiter = _AwaitCallsTo(marker.async_names)
        awaiter.visit(module)
        if not (marker.changed or awaiter.changed):
            return


def _drop_unused_helpers(body: list, keep: str) -> list:
    """Remove private helpers the rewrite orphaned, such as auth error messages."""
    while True:
        functions = {s.name: s for s in body
                     if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}
        referenced: set[str] = set()
        for statement in body:
            name = getattr(statement, "name", None)
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and node.id in functions and node.id != name:
                    referenced.add(node.id)
        orphans = {n for n in functions
                   if n.startswith("_") and n != keep and n not in referenced}
        if not orphans:
            return body
        body = [s for s in body if getattr(s, "name", None) not in orphans]


def migrate(source: str, expected_name: str, provider: str) -> str:
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    atom = next((f for f in functions if f.name == expected_name), None)
    if atom is None:
        # A few files name the function differently from the file. The file name
        # is what the registry uses, so it decides.
        public = [f for f in functions if not f.name.startswith("_")
                  and f.args.args and f.args.args[0].arg == "auth_info"]
        if len(public) != 1:
            raise Skip("no function matching the file name")
        old_name = public[0].name
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == old_name:
                node.id = expected_name
        public[0].name = expected_name
        atom = public[0]
    if isinstance(atom, ast.AsyncFunctionDef):
        raise Skip("already async")
    if not (atom.args.args and atom.args.args[0].arg == "auth_info"):
        raise Skip("atom does not take auth_info")

    helpers = [f for f in functions if f is not atom]
    request_helpers = {f.name for f in helpers if _is_request_helper(f)}
    stripped: dict[str, int] = {}
    for helper in helpers:
        if not _mentions(helper, "auth_info"):
            continue
        names = [a.arg for a in helper.args.args]
        if "auth_info" in names:
            stripped[helper.name] = names.index("auth_info")
        _strip_credential(helper)

    # The atom reads the credential directly as often as it delegates.
    _strip_credential(atom, require_return=False)

    # Anything holding a value that came from a request now holds a response dict.
    response_names: set[str] = set()
    for fn in functions:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if _requests_verb(value) is not None or (
                isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                and value.func.id in request_helpers
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        response_names.add(target.id)

    # Awaiting spreads: a caller of an async helper is itself async.
    async_helpers = set(request_helpers)
    while True:
        grown = False
        for fn in helpers:
            if fn.name in async_helpers:
                continue
            if _called_names(fn) & async_helpers:
                async_helpers.add(fn.name)
                grown = True
        if not grown:
            break

    rewriter = Rewriter(response_names, async_helpers, stripped)
    body = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rewriter.in_atom = statement.name == expected_name
            rewritten = rewriter.visit(statement)
            if statement.name in async_helpers or statement.name == expected_name:
                rewritten = _to_async(rewritten)
            body.append(rewritten)
        else:
            visited = rewriter.visit(statement)
            if visited is not None:
                body.append(visited)

    if rewriter.calls == 0:
        raise Skip("no requests call found to replace")

    atom_out = next(f for f in body if getattr(f, "name", None) == expected_name)
    defaults = atom_out.args.defaults
    if len(defaults) > len(atom_out.args.args):
        atom_out.args.defaults = defaults[-len(atom_out.args.args):] if atom_out.args.args else []
    _ensure_docstring(atom_out, provider)

    module = ast.Module(body=_drop_unused_helpers(body, expected_name), type_ignores=[])
    _settle_async(module)
    result = ast.unparse(ast.fix_missing_locations(module)) + "\n"
    # compile(), not ast.parse(): an await inside a sync def parses but never runs.
    try:
        compile(result, expected_name, "exec")
    except SyntaxError as exc:
        raise Skip(f"rewritten atom does not compile: {exc.msg}") from exc
    checked = ast.parse(result)
    for node in ast.walk(checked):
        if isinstance(node, ast.Name) and node.id == "auth_info":
            raise Skip("auth_info is still read after the rewrite")
        if isinstance(node, ast.arg) and node.arg == "auth_info":
            raise Skip("auth_info is still a parameter after the rewrite")
        if isinstance(node, ast.Name) and node.id == "requests":
            raise Skip("a requests call survives the rewrite")
        # A credential read that vanished mid-expression means the atom relied on
        # account configuration, such as a subdomain, that now needs a parameter.
        if isinstance(node, ast.FormattedValue) and _is_none(node.value):
            raise Skip("account configuration came from auth_info and needs a parameter")
        if isinstance(node, (ast.Subscript, ast.Attribute)) and _is_none(node.value):
            raise Skip("account configuration came from auth_info and needs a parameter")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--only", nargs="*", default=None, help="limit to these providers")
    parser.add_argument("--show", type=int, default=0, help="print N migrated samples")
    args = parser.parse_args()

    sys.path.insert(0, ".")
    from jarviscore.execution.atom_contract import read_contract

    migrated, skipped, invalid = 0, collections.Counter(), []
    samples = []

    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        if args.only and path.parent.name not in args.only:
            continue
        source = path.read_text(encoding="utf-8")
        if "auth_info" not in source:
            continue
        try:
            result = migrate(source, path.stem, path.parent.name)
        except Skip as exc:
            skipped[str(exc)] += 1
            continue
        except Exception as exc:  # noqa: BLE001 - report, never guess
            skipped[f"transform error: {type(exc).__name__}: {exc}"] += 1
            continue

        contract = read_contract(result, system=path.parent.name, expected_name=path.stem)
        if not contract.ok:
            invalid.append((str(path), contract.report()))
            continue
        migrated += 1
        if len(samples) < args.show:
            samples.append((path, result))
        if args.write:
            path.write_text(result, encoding="utf-8")

    total = migrated + sum(skipped.values()) + len(invalid)
    print(f"atoms seen:            {total}")
    print(f"migrated + verified:   {migrated}")
    print(f"needs review:          {sum(skipped.values())}")
    print(f"failed the contract:   {len(invalid)}")
    if skipped:
        print("\nreasons for review:")
        for reason, count in skipped.most_common(20):
            print(f"  {count:5d}  {reason[:110]}")
    if invalid:
        print("\ncontract failures:")
        for reason, count in collections.Counter(r for _, r in invalid).most_common(12):
            print(f"  {count:5d}  {reason[:110]}")
    for path, text in samples:
        print(f"\n───── {path} ─────\n{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
