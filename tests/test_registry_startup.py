"""Opening the function registry costs milliseconds, not seconds.

Every agent start opened the registry and merged the shipped catalogue into it.
That executed all 1,229 atom modules to hold callables nothing asked for, parsed
each atom's contract twice even when the stored source was the shipped source,
and walked every expression node looking for a docstring. A warm start spent
about six seconds there and a cold one up to fourteen, before any work began.

These tests hold the shortcuts to the behaviour they replace: callables still
exist when asked for, a converged atom is still skipped, and a description is
still the one a full ``ast.walk`` would have found.
"""

import ast
import textwrap

import pytest

from jarviscore.execution import atom_contract
from jarviscore.execution.code_registry import create_function_registry
from jarviscore.integrations import seed_registry as seeding
from jarviscore.integrations.seed_registry import _extract_description, seed_registry

SIDE_EFFECT_ATOM = textwrap.dedent('''
    import builtins
    builtins._jarviscore_atom_executions = getattr(builtins, "_jarviscore_atom_executions", 0) + 1

    def acme_ping(auth_info=None):
        """Ping Acme."""
        return "pong"
''')


@pytest.fixture
def executions():
    import builtins

    builtins._jarviscore_atom_executions = 0
    yield lambda: builtins._jarviscore_atom_executions
    del builtins._jarviscore_atom_executions


class TestCallablesCompileOnFirstUse:
    def test_registering_source_runs_none_of_it(self, tmp_path, executions):
        registry = create_function_registry(str(tmp_path), seed=False)
        registry.register_function(
            "acme_ping", SIDE_EFFECT_ATOM,
            metadata={"system": "acme", "description": "Ping", "capabilities": ["ping"]},
        )
        assert executions() == 0
        assert registry.get_function_metadata("acme_ping")["load_status"] == "loaded"

    def test_the_callable_is_there_when_asked_for(self, tmp_path, executions):
        registry = create_function_registry(str(tmp_path), seed=False)
        registry.register_function(
            "acme_ping", SIDE_EFFECT_ATOM,
            metadata={"system": "acme", "description": "Ping", "capabilities": ["ping"]},
        )
        function = registry.get_function("acme_ping")
        assert function() == "pong"
        assert registry.get_function("acme_ping") is function
        assert executions() == 1

    def test_reopening_a_registry_runs_none_of_it(self, tmp_path, executions):
        create_function_registry(str(tmp_path), seed=False).register_function(
            "acme_ping", SIDE_EFFECT_ATOM,
            metadata={"system": "acme", "description": "Ping", "capabilities": ["ping"]},
        )
        reopened = create_function_registry(str(tmp_path), seed=False)
        assert executions() == 0
        assert reopened.get_function("acme_ping")() == "pong"

    def test_a_new_version_replaces_the_compiled_one(self, tmp_path):
        registry = create_function_registry(str(tmp_path), seed=False)
        meta = {"system": "acme", "description": "Ping", "capabilities": ["ping"]}
        registry.register_function("acme_ping", "def acme_ping():\n    return 1\n", metadata=meta)
        assert registry.get_function("acme_ping")() == 1
        registry.register_function("acme_ping", "def acme_ping():\n    return 2\n", metadata=meta)
        assert registry.get_function("acme_ping")() == 2

    def test_source_that_cannot_import_is_source_only(self, tmp_path):
        registry = create_function_registry(str(tmp_path), seed=False)
        registry.register_function(
            "acme_broken", "def acme_broken(:\n",
            metadata={"system": "acme", "description": "Broken", "capabilities": ["x"]},
        )
        assert registry.has_function("acme_broken")
        assert registry.get_function("acme_broken") is None

    def test_a_registered_callable_is_returned_as_given(self, tmp_path):
        registry = create_function_registry(str(tmp_path), seed=False)

        def acme_echo(value):
            return value

        registry.register_function(
            "acme_echo", acme_echo,
            metadata={"system": "acme", "description": "Echo", "capabilities": ["echo"]},
        )
        assert registry.get_function("acme_echo") is acme_echo

    def test_unregistered_functions_are_not_compiled_later(self, tmp_path, executions):
        registry = create_function_registry(str(tmp_path), seed=False)
        registry.register_function(
            "acme_ping", SIDE_EFFECT_ATOM,
            metadata={"system": "acme", "description": "Ping", "capabilities": ["ping"]},
        )
        registry.unregister_function("acme_ping")
        assert registry.get_function("acme_ping") is None
        assert executions() == 0


class TestConvergedAtomsAreNotReparsed:
    def test_identical_source_is_skipped_without_reading_contracts(self, tmp_path, monkeypatch):
        registry = create_function_registry(str(tmp_path), seed=False)
        seed_registry(registry, systems=["slack"], missing_only=True)
        before = {
            name: registry.get_function_metadata(name)["version"]
            for name in registry.list_function_names()
        }

        def must_not_parse(*args, **kwargs):
            raise AssertionError("a converged atom's contract was parsed")

        monkeypatch.setattr(atom_contract, "read_contract", must_not_parse)
        report = seed_registry(registry, systems=["slack"], missing_only=True)

        assert report["registered"] == [] and report["failed"] == []
        assert {entry["reason"] for entry in report["skipped"]} == {"already registered"}
        assert len(report["skipped"]) == len(before)
        assert {
            name: registry.get_function_metadata(name)["version"]
            for name in registry.list_function_names()
        } == before


def _reference_description(function_name: str, source: str) -> str:
    """The description rule as it was, with a full ast.walk."""
    try:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    return node.body[0].value.value[:200]
    except Exception:
        pass
    parts = function_name.split("_")
    if len(parts) >= 2:
        return f"{parts[0].title()}: {' '.join(parts[1:])}"
    return function_name


SHAPES = {
    "top_level": 'def acme_get():\n    "Top level."\n',
    "async_is_not_matched": 'async def acme_get():\n    "Async."\n',
    "nested_in_async": 'async def acme_get():\n    def acme_get():\n        "Inner."\n',
    "undocumented_top_then_nested": 'def acme_get():\n    def acme_get():\n        "Nested."\n',
    "class_method": 'class Acme:\n    def acme_get(self):\n        "Method."\n',
    "shallowest_wins": (
        'class A:\n    class B:\n        def acme_get():\n            "Deep."\n'
        'def other():\n    def acme_get():\n        "Shallow."\n'
    ),
    "in_handler": 'try:\n    pass\nexcept Exception:\n    def acme_get():\n        "Handler."\n',
    "in_star_handler": 'try:\n    pass\nexcept* ValueError:\n    def acme_get():\n        "Star."\n',
    "in_match": 'match x:\n    case 1:\n        def acme_get():\n            "Match."\n',
    "in_loops": 'with a:\n    while b:\n        for c in d:\n            def acme_get():\n                "Loop."\n',
    "non_string_docstring": 'def acme_get():\n    42\n',
    "syntax_error": 'def acme_get(:\n',
    "no_function": 'X = 1\n',
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_description_matches_the_full_walk(shape):
    source = SHAPES[shape]
    assert _extract_description("acme_get", source) == _reference_description("acme_get", source)


def test_description_matches_the_full_walk_for_the_shipped_catalogue():
    atoms = sorted(
        path for path in seeding._ATOMS_DIR.glob("*/*.py") if not path.name.startswith("__")
    )
    assert atoms
    for path in atoms:
        source = path.read_text(encoding="utf-8")
        assert _extract_description(path.stem, source) == _reference_description(path.stem, source), path
