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

CREATE_ATOM_SOURCE = '''\
ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["account_name"],
    "consequence": "Creates one account record.",
}

async def insightly_create_account(account_name: str) -> dict:
    """Create an organisation record in Insightly."""
    response = await nexus_call(
        "POST", "https://api.na1.insightly.com/v3.1/Organisations",
        json={"ORGANISATION_NAME": account_name},
    )
    return {"status": "success", "data": response["json"]}
'''

GMAIL_ATOM_SOURCE = '''\
async def gmail_list_messages(query: str = "") -> dict:
    """List Gmail messages matching a query."""
    response = await nexus_call(
        "GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        params={"q": query},
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
        {
            "insightly_get_account": {"system": "insightly", "code": ATOM_SOURCE},
            "insightly_create_account": {
                "system": "insightly", "code": CREATE_ATOM_SOURCE,
            },
            "gmail_list_messages": {
                "system": "gmail", "code": GMAIL_ATOM_SOURCE,
            },
        }
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
    assert set(coder._atom_tools) == {
        "insightly_get_account", "insightly_create_account",
    }


def test_provider_bound_outcome_offers_read_and_write_atoms_for_agent_reasoning(coder):
    coder._run_context = {
        "system": "insightly",
        "effect": "write",
        "systems": ["insightly"],
    }

    coder._offer_system_capabilities(coder._resolved_system())

    assert set(coder._atom_tools) == {
        "insightly_get_account", "insightly_create_account",
    }


def test_read_outcome_never_offers_write_atoms(coder):
    coder._run_context = {
        "system": "insightly",
        "effect": "read",
        "systems": ["insightly"],
    }

    coder._offer_system_capabilities(coder._resolved_system())

    assert coder._atom_tools == ["insightly_get_account"]


def test_multi_provider_read_offers_each_connected_system_atom(coder):
    coder._run_context = {
        "systems": ["insightly", "gmail"],
        "effect": "read",
    }

    coder._offer_system_capabilities_for(["insightly", "gmail"])

    assert set(coder._atom_tools) == {
        "insightly_get_account", "gmail_list_messages",
    }


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
