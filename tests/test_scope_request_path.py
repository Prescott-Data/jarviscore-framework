"""Provider-wide scope requirements close unmatched-endpoint gaps."""

import pytest
from test_scopes import ERP, authority

from jarviscore import OnBehalfOf, act_for
from jarviscore.control.policy import PolicyDenied

pytest_plugins = ["test_scopes"]

POLICY = {
    "scopes": {
        "require": [
            {
                "name": "selected-endpoints",
                "match": {"provider": "erp"},
                "requires": "sources.read",
                "limits": [{"field": "request_path", "kind": "exact", "one_of": "paths"}],
            }
        ]
    }
}


@pytest.mark.parametrize("path", ["/files/selected", "/legacy/files/selected", "/files/other"])
async def test_provider_endpoint_limit_precedes_credentials(broker, path):
    proxy, auth, _ = broker(document=POLICY)
    person = OnBehalfOf.of(
        "acme", "reader", scopes={"sources.read": {"paths": ["/files/selected"]}}
    )
    with act_for(person):
        if path == "/files/selected":
            response = await proxy.call(
                "conn-erp",
                "GET",
                ERP + path,
                authority=authority("erp_read_original", effect="read"),
            )
            assert response["ok"]
            auth.resolve_strategy.assert_awaited_once()
        else:
            with pytest.raises(PolicyDenied):
                await proxy.call(
                    "conn-erp",
                    "GET",
                    ERP + path,
                    authority=authority("erp_read_original", effect="read"),
                )
            auth.resolve_strategy.assert_not_awaited()
