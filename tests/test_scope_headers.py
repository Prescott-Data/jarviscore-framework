"""Header selectors are held to the same native scopes as query, body and path selectors."""

import json

import httpx
import pytest
from test_scopes import Client, authority, decisions

from jarviscore import OnBehalfOf, act_for
from jarviscore.control import scopes as s
from jarviscore.control.grounding import request_from
from jarviscore.control.operations import read_operations
from jarviscore.control.policy import PolicyDenied

pytest_plugins = ["test_scopes"]


def policy(header, method="POST"):
    return {
        "scopes": {
            "require": [
                {
                    "name": "selected-original",
                    "match": {"provider": "erp", "method": method, "path": "/files/download"},
                    "requires": "sources.read",
                    "limits": [
                        {
                            "field": f"headers.{header.lower()}",
                            "kind": "exact",
                            "one_of": "selectors",
                        }
                    ],
                }
            ]
        }
    }


def check(headers, allowed):
    scopes = s.parse_section(policy("X-Resource-ID")["scopes"])
    request = request_from("POST", "https://erp.example.test/files/download", {"headers": headers})
    person = s.person_holder(scopes, "org/owner", {"sources.read": {"selectors": allowed}})
    return s.check_call(
        scopes,
        s.Facts(provider="erp", method="POST", host=request.host, path=request.path),
        request,
        person,
        None,
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Resource-ID": "selected"},
        {"x-resource-id": "selected"},
        [("X-RESOURCE-ID", "selected")],
        httpx.Headers({"X-Resource-ID": "selected"}),
    ],
)
def test_header_selectors_use_effective_http_names_and_values(headers):
    assert check(headers, ["selected"]).allowed
    assert not check(headers, ["different"]).allowed


def test_duplicate_header_values_all_need_authority():
    headers = [("X-Resource-ID", "selected"), ("x-resource-id", "another")]
    assert not check(headers, ["selected"]).allowed
    assert check(headers, ["selected", "another"]).allowed


@pytest.mark.parametrize(
    "headers", [None, {}, {"X-Resource-ID": ""}, [("X-Resource-ID", object())]]
)
def test_absent_or_unreadable_header_selector_fails_closed(headers):
    assert not check(headers, ["selected"]).allowed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header,selected,other",
    [
        ("Dropbox-API-Arg", '{"path": "id:selected"}', '{"path": "id:other"}'),
        ("X-Resource-ID", "private-selector-fixture-271", "private-selector-fixture-999"),
    ],
)
@pytest.mark.parametrize(
    "method,origin,atom", [("GET", "model", None), ("POST", "shipped", "download")]
)
async def test_header_limits_hold_calls_before_credentials_and_do_not_log_values(
    broker, header, selected, other, method, origin, atom
):
    proxy, auth, root = broker("strict", policy(header, method))
    contract = read_operations(
        f'async def download():\n    return await nexus_call("{method}", "https://erp.example.test/files/download")',
        entry="download",
    )
    arriving = authority(atom, effect="read", code_origin=origin, contract=contract)
    person = OnBehalfOf.of("acme", "owner", scopes={"sources.read": {"selectors": [selected]}})
    with act_for(person):
        assert (
            await proxy.call(
                "conn-erp",
                method,
                "https://erp.example.test/files/download",
                headers={header: selected},
                authority=arriving,
            )
        )["ok"]
        with pytest.raises(PolicyDenied, match="beyond what"):
            await proxy.call(
                "conn-erp",
                method,
                "https://erp.example.test/files/download",
                headers={header.upper(): other},
                authority=arriving,
            )
    assert len(Client.sent) == 1
    assert auth.resolve_strategy.await_count == 1
    records = decisions(root)
    assert records[0]["scope"]["allowed"]
    assert records[1]["rule"] == "over-scope-limit"
    assert selected not in json.dumps(records)
    assert other not in json.dumps(records)
