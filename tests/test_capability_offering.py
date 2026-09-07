"""A resolved provider makes its atoms callable, not merely quotable.

The registry-first path already identifies the exact system a task needs. Before
this was pinned, that identification arrived in the prompt as evidence while the
atoms stayed unregistered, so the agent could describe a capability it had no way
to call and would rewrite it from scratch instead.
"""

import pytest

from jarviscore.kernel.defaults.coder import CoderSubAgent


ATOM_SOURCE = '''\
async def insightly_get_account(account_id: str) -> dict:
    """Fetch an organisation record from Insightly by account id."""
    response = await nexus_call(
        "GET", f"https://api.na1.insightly.com/v3.1/Organisations/{account_id}"
    )
    return {"status": "success", "data": response["json"]}
'''


class FakeRegistry:
    """Minimal stand-in for the FunctionRegistry surface coder.py touches."""

    def __init__(self, functions):
        self._functions = functions

    def get_functions_by_system(self, system):
        return [
            {"function_name": name}
            for name, entry in self._functions.items()
            if entry["system"] == system
        ]

    def get_function_code(self, name):
        entry = self._functions.get(name)
        return entry["code"] if entry else None


@pytest.fixture
def coder():
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._tools = {}
    agent._atom_tools = []
    agent._atoms = {}
    agent._run_context = {}
    agent.code_registry = FakeRegistry(
        {"insightly_get_account": {"system": "insightly", "code": ATOM_SOURCE}}
    )

    def register_tool(name, fn, description, phase=None):
        agent._tools[name] = (fn, description, phase)

    agent.register_tool = register_tool

    class _Log:
        def info(self, *a, **k):
            pass

    agent._log = _Log()
    return agent


def test_declared_system_resolves(coder):
    coder._run_context = {"system": "insightly"}
    assert coder._resolved_system() == "insightly"


def test_registry_candidate_resolves_when_task_named_nothing(coder):
    coder._run_context = {
        "registry_candidate": {
            "function_name": "insightly_get_account",
            "system": "insightly",
        }
    }
    assert coder._resolved_system() == "insightly"


def test_declared_system_wins_over_candidate(coder):
    """A named provider is a constraint; an inferred one must not override it."""
    coder._run_context = {
        "system": "hubspot",
        "registry_candidate": {"system": "insightly"},
    }
    assert coder._resolved_system() == "hubspot"


def test_no_system_and_no_candidate_resolves_to_nothing(coder):
    coder._run_context = {"task": "summarise the quarter"}
    assert coder._resolved_system() is None


def test_candidate_without_system_resolves_to_nothing(coder):
    coder._run_context = {"registry_candidate": {"function_name": "orphan"}}
    assert coder._resolved_system() is None


def test_candidate_makes_the_atom_a_callable_tool(coder):
    """The regression itself: candidate present, atom must be registered."""
    coder._run_context = {
        "registry_candidate": {
            "function_name": "insightly_get_account",
            "system": "insightly",
        }
    }
    coder._offer_system_capabilities(coder._resolved_system())
    assert "insightly_get_account" in coder._tools
    assert coder._atom_tools == ["insightly_get_account"]


def test_unresolved_system_offers_nothing(coder):
    coder._run_context = {}
    coder._offer_system_capabilities(coder._resolved_system())
    assert coder._tools == {}


def test_offering_is_replaced_not_accumulated(coder):
    """Atoms from a previous dispatch must not linger into an unrelated one."""
    coder._offer_system_capabilities("insightly")
    assert "insightly_get_account" in coder._tools
    coder._offer_system_capabilities(None)
    assert "insightly_get_account" not in coder._tools
    assert coder._atom_tools == []
