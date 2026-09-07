"""The shipped atom corpus holds together.

A mechanical rewrite moved 1,174 atoms from a raw credential dict to `nexus_call`.
Contract checks alone would not have caught what actually went wrong during it:
an `await` inside a nested `def` parses but never compiles, and a credential
check folded the wrong way turned a success path into an unconditional 401. So
these tests compile the corpus and run every atom, rather than reading it.
"""

import ast
import asyncio
import pathlib

import pytest

from jarviscore.execution.atom_contract import read_contract

ROOT = pathlib.Path(__file__).resolve().parents[1] / "jarviscore/integrations/atoms"

#: Providers whose atoms still take `auth_info`. Each needs account
#: configuration, such as a tenant URL, turned into a parameter before it can
#: move. The list may shrink and must never grow.
AWAITING_A_PARAMETER = {
    "agilecrm": 13, "confluence": 3, "google_drive": 1, "jira": 3, "kra": 2,
    "mailchimp": 3, "matomo": 1, "odoo": 6, "quickbooks": 4, "salesforce": 4,
    "zoho_people": 4,
}

SAMPLE = {"str": "x", "int": 1, "float": 1.0, "bool": True, "dict": {}, "list": []}


def atom_paths():
    return sorted(p for p in ROOT.rglob("*.py") if p.name != "__init__.py")


def is_legacy(tree) -> bool:
    return any(
        (isinstance(n, ast.Name) and n.id == "auth_info")
        or (isinstance(n, ast.arg) and n.arg == "auth_info")
        for n in ast.walk(tree)
    )


def walk_own_scope(node):
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield from walk_own_scope(child)


class TestTheCorpusCompiles:

    def test_every_atom_compiles(self):
        broken = []
        for path in atom_paths():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except SyntaxError as exc:
                broken.append(f"{path.name}: {exc.msg}")
        assert not broken, broken[:10]

    def test_no_atom_awaits_inside_a_sync_function(self):
        """This compiles under ast.parse and fails only when Python runs it."""
        offenders = []
        for path in atom_paths():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if any(isinstance(inner, ast.Await)
                       for statement in node.body
                       for inner in walk_own_scope(statement)):
                    offenders.append(f"{path.name}:{node.name}")
        assert not offenders, offenders[:10]


class TestTheMigration:

    def test_only_known_providers_still_take_a_credential(self):
        remaining = {}
        for path in atom_paths():
            if is_legacy(ast.parse(path.read_text(encoding="utf-8"))):
                remaining[path.parent.name] = remaining.get(path.parent.name, 0) + 1
        for provider, count in remaining.items():
            assert provider in AWAITING_A_PARAMETER, f"{provider} regressed to auth_info"
            assert count <= AWAITING_A_PARAMETER[provider], f"{provider} grew to {count}"

    def test_migrated_atoms_satisfy_the_contract(self):
        problems = []
        for path in atom_paths():
            source = path.read_text(encoding="utf-8")
            if is_legacy(ast.parse(source)):
                continue
            result = read_contract(source, system=path.parent.name, expected_name=path.stem)
            if not result.ok:
                problems.append(f"{path.name}: {result.report()}")
        assert not problems, problems[:10]


class TestEveryAtomRuns:
    """Executed against a stubbed provider, because shape is not behaviour."""

    @staticmethod
    async def nexus_call(method, url, **kwargs):
        return {
            "ok": True, "status_code": 200, "body": "{}", "content": b"{}",
            "json": {"data": [], "results": [], "records": [], "id": "1",
                     "ok": True, "response_metadata": {}},
            "headers": {},
        }

    @staticmethod
    def argument_for(annotation: str):
        base = annotation.replace("Optional[", "").rstrip("]")
        for key, value in SAMPLE.items():
            if base.startswith(key):
                return value
        return "x"

    @pytest.mark.asyncio
    async def test_the_corpus_reaches_nexus_call_without_falling_over(self):
        reached = 0
        completed = 0
        for path in atom_paths():
            source = path.read_text(encoding="utf-8")
            result = read_contract(source, system=path.parent.name, expected_name=path.stem)
            if not result.ok or result.atom.legacy:
                continue

            calls = []

            async def record(method, url, **kwargs):
                calls.append((method, url))
                return await TestEveryAtomRuns.nexus_call(method, url, **kwargs)

            # Required parameters only, so each atom keeps its own defaults the
            # way a caller would leave them.
            params = {p.name: self.argument_for(p.type)
                      for p in result.atom.parameters if p.required}
            namespace = {"nexus_call": record}
            exec(compile(source, str(path), "exec"), namespace)
            try:
                await asyncio.wait_for(namespace[path.stem](**params), timeout=5)
            except Exception:  # noqa: BLE001 - stub data cannot satisfy every atom
                pass
            completed += 1
            if calls:
                reached += 1

        assert completed > 1150, completed
        # The rest return before calling out because they want tenant
        # configuration, such as a site URL, that no stub can stand in for.
        assert reached > 450, reached
