"""The capability loop: a migrated atom is offered, called, and run in the sandbox."""

import pytest

from jarviscore.execution.atom_contract import invocation, read_contract

ATOM = "jarviscore/integrations/atoms/hubspot/hubspot_list_contacts.py"


@pytest.fixture
def atom_source():
    with open(ATOM, encoding="utf-8") as handle:
        return handle.read()


class TestMigratedAtomIsCallable:

    def test_it_satisfies_the_contract(self, atom_source):
        result = read_contract(atom_source, system="hubspot",
                               expected_name="hubspot_list_contacts")
        assert result.ok, result.report()
        assert not result.atom.legacy

    def test_the_credential_is_gone_from_the_signature(self, atom_source):
        atom = read_contract(atom_source, system="hubspot",
                             expected_name="hubspot_list_contacts").atom
        assert [p.name for p in atom.parameters] == ["limit", "after"]
        assert "auth_info" not in atom_source

    async def test_it_runs_against_a_stubbed_nexus(self, atom_source):
        """The atom plus its invocation is exactly what the sandbox executes."""
        calls = []

        async def nexus_call(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return {"ok": True, "status_code": 200,
                    "json": {"results": [{"id": "1"}], "paging": None},
                    "body": "", "headers": {}}

        atom = read_contract(atom_source, system="hubspot",
                             expected_name="hubspot_list_contacts").atom
        namespace = {"nexus_call": nexus_call}
        exec(f"{atom_source}\n\n{invocation(atom, {'limit': 5})}", namespace)
        result = await namespace["main"]()

        assert result["success"] is True
        assert result["contacts"] == [{"id": "1"}]
        method, url, kwargs = calls[0]
        assert method == "GET"
        assert url == "https://api.hubapi.com/crm/v3/objects/contacts"
        assert kwargs["params"]["limit"] == 5

    async def test_a_provider_error_is_returned_not_raised(self, atom_source):
        async def nexus_call(method, url, **kwargs):
            return {"ok": False, "status_code": 401, "json": None,
                    "body": "unauthorised", "headers": {}}

        atom = read_contract(atom_source, system="hubspot",
                             expected_name="hubspot_list_contacts").atom
        namespace = {"nexus_call": nexus_call}
        exec(f"{atom_source}\n\n{invocation(atom, {})}", namespace)
        result = await namespace["main"]()

        assert result == {"success": False, "error": "unauthorised"}
