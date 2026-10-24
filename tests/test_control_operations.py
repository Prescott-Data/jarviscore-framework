"""An atom's operation contract is what its own code can send, read before it runs."""
import pathlib

import pytest

from jarviscore.control.operations import (
    effect_rank,
    method_floor,
    method_within_effect,
    read_operations,
)
from jarviscore.execution.atom_contract import read_contract

HELPERS = '''
async def github_get_repo(owner: str, repo: str) -> dict:
    _base = "https://api.github.com"

    async def _get(p, params=None):
        return await nexus_call("GET", f"{_base}{p}", params=params or {})

    async def _delete(p):
        return await nexus_call("DELETE", f"{_base}{p}")

    return await _get(f"/repos/{owner}/{repo}")
'''

DISPATCHER = '''
_ROOT = "https://api.pagerduty.com"

async def pagerduty_get_incident(incident_id: str) -> dict:
    return await _request("get", _ROOT + f"/incidents/{incident_id}")

async def _request(method, url):
    if method == "get":
        return await nexus_call("GET", url)
    elif method == "put":
        return await nexus_call("PUT", url)
'''

CONSTANT_PATH = '''
_PATH = "/version1/messaging"

async def africas_talking_send(text: str) -> dict:
    root = "https://api.africastalking.com"
    return await nexus_call("POST", f"{root}{_PATH}", data={"message": text})
'''

RUNTIME_URL = '''
async def s3_put(url: str) -> dict:
    return await nexus_call("PUT", url)
'''

DYNAMIC_METHOD = '''
async def thing(verb: str) -> dict:
    return await nexus_call(verb, "https://api.example.com/things")
'''


def ops(source, entry):
    return sorted(f"{op.method} {op.template}" for op in read_operations(source, entry).operations)


def test_a_helper_defined_but_never_called_is_not_part_of_the_contract():
    assert ops(HELPERS, "github_get_repo") == ["GET https://api.github.com/repos/*/*"]


def test_a_dispatcher_branch_the_atom_never_takes_is_pruned():
    assert ops(DISPATCHER, "pagerduty_get_incident") == ["GET https://api.pagerduty.com/incidents/*"]


def test_module_constants_and_locals_are_followed():
    assert ops(CONSTANT_PATH, "africas_talking_send") == [
        "POST https://api.africastalking.com/version1/messaging"
    ]


def test_a_url_built_at_run_time_leaves_the_contract_unverified():
    contract = read_operations(RUNTIME_URL, "s3_put")

    assert not contract.verified
    assert ops(RUNTIME_URL, "s3_put") == ["PUT *"]


def test_a_method_in_a_variable_leaves_the_contract_incomplete():
    contract = read_operations(DYNAMIC_METHOD, "thing")

    assert not contract.complete and not contract.verified


def test_matching_ignores_query_strings_and_requires_the_method():
    contract = read_operations(HELPERS, "github_get_repo")

    assert contract.verified
    assert contract.allows("GET", "https://api.github.com/repos/acme/app?per_page=5")
    assert not contract.allows("DELETE", "https://api.github.com/repos/acme/app")
    assert not contract.allows("GET", "https://api.github.com/orgs/acme")


@pytest.mark.parametrize("method, declared, allowed", [
    ("GET", "read", True),
    ("POST", "write", True),
    ("POST", "notify", True),
    ("DELETE", "write", False),
    ("DELETE", "destructive", True),
    ("PUT", "read", False),
    ("PATCH", "propose", False),
])
def test_a_method_never_exceeds_the_declared_effect(method, declared, allowed):
    assert method_within_effect(method, declared, None, "https://x.example/a") is allowed


def test_a_read_may_post_only_to_a_query_its_own_verified_contract_names():
    query = '''
async def attio_list_people(limit: int = 25) -> dict:
    return await nexus_call("POST", "https://api.attio.com/v2/objects/people/records/query", json={"limit": limit})
'''
    contract = read_operations(query, "attio_list_people")

    assert method_within_effect("POST", "read", contract, "https://api.attio.com/v2/objects/people/records/query")
    assert not method_within_effect("POST", "read", contract, "https://api.attio.com/v2/objects/people/records")
    assert not method_within_effect("POST", "read", None, "https://api.attio.com/v2/objects/people/records/query")


def test_no_shipped_atom_can_send_more_than_it_declares():
    """Across the catalogue: reachable code never exceeds the declared effect.

    The one allowance is a read that POSTs (search and query endpoints); the broker
    holds those to the atom's verified contract at run time.
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "jarviscore" / "integrations" / "atoms"
    beyond = []
    checked = 0
    for path in sorted(root.glob("*/*.py")):
        if path.name.startswith("_"):
            continue
        source = path.read_text()
        atom = read_contract(source, system=path.parent.name, expected_name=path.stem).atom
        if atom is None or atom.legacy:
            continue
        checked += 1
        for op in read_operations(source, path.stem).operations:
            reach = effect_rank(method_floor(op.method))
            if reach > effect_rank(atom.policy.effect) and not (
                op.method == "POST" and atom.policy.effect in ("read", "propose")
            ):
                beyond.append(f"{atom.name} ({atom.policy.effect}): {op.method} {op.template}")
    assert checked > 1000
    assert beyond == []
