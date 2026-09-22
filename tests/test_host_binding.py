"""A credential may only be sent to a host its provider owns.

A HubSpot token was sent to slack.com because the connection is bound to the
task while the URL is chosen by generated code. Anything a model picks can be
wrong or influenced, so the destination is checked rather than trusted.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarviscore.nexus.call_proxy import NexusCallProxy
from jarviscore.nexus.hosts import (
    HostNotAllowed,
    allowed_hosts,
    ensure_host_allowed,
)
from jarviscore.nexus.models import DynamicStrategy


# ── The refusal itself ───────────────────────────────────────────────────────

def test_a_credential_may_not_cross_to_another_provider():
    with pytest.raises(HostNotAllowed) as exc:
        ensure_host_allowed("hubspot", "https://slack.com/api/api.test")
    assert exc.value.provider == "hubspot"
    assert exc.value.requested_host == "slack.com"
    assert exc.value.allowed == ("api.hubapi.com",)


def test_a_credential_may_not_go_to_an_unrelated_domain():
    with pytest.raises(HostNotAllowed):
        ensure_host_allowed("hubspot", "https://evil.example.com/collect")


def test_the_provider_own_host_is_allowed():
    ensure_host_allowed("hubspot", "https://api.hubapi.com/crm/v3/objects/contacts")


def test_the_refusal_names_where_the_provider_is_called():
    """A refusal that does not say what would work is a dead end for the agent."""
    with pytest.raises(HostNotAllowed) as exc:
        ensure_host_allowed("slack", "https://api.hubapi.com/crm/v3/objects")
    assert exc.value.provider == "slack"
    assert exc.value.allowed == allowed_hosts("slack")


def test_a_url_with_no_host_is_refused():
    with pytest.raises(HostNotAllowed):
        ensure_host_allowed("hubspot", "not-a-url")


def test_an_unknown_provider_is_refused_not_waved_through():
    with pytest.raises(HostNotAllowed) as exc:
        ensure_host_allowed("nobody", "https://anywhere.example.com/")
    assert "No API hosts are known" in str(exc.value)


# ── Tenant-hosted providers ──────────────────────────────────────────────────

def test_a_tenant_domain_on_the_connection_is_allowed():
    entry = {"instance_url": "https://acme.my.salesforce.com"}
    ensure_host_allowed("salesforce", "https://acme.my.salesforce.com/services/data", entry)


def test_a_tenant_domain_does_not_open_other_hosts():
    entry = {"instance_url": "https://acme.my.salesforce.com"}
    with pytest.raises(HostNotAllowed):
        ensure_host_allowed("salesforce", "https://evil.example.com/", entry)


def test_a_bare_domain_on_the_connection_is_understood():
    entry = {"odoo_url": "mycompany.odoo.com"}
    ensure_host_allowed("odoo", "https://mycompany.odoo.com/jsonrpc", entry)


def test_a_tenant_provider_without_a_recorded_domain_is_refused():
    with pytest.raises(HostNotAllowed) as exc:
        ensure_host_allowed("salesforce", "https://acme.my.salesforce.com/x")
    assert "record it on the connection" in str(exc.value)


@pytest.mark.asyncio
async def test_gateway_call_does_not_read_the_local_vault(monkeypatch):
    auth = SimpleNamespace(
        _connections={"github": "resolved:github"},
        resolve_strategy=AsyncMock(return_value=DynamicStrategy(
            type="oauth2",
            credentials={"access_token": "secret"},
        )),
    )

    def local_store_is_forbidden():
        raise AssertionError("gateway mode must not open the local vault")

    class Response:
        status_code = 200
        text = "{}"
        content = b"{}"
        headers = {}

        @staticmethod
        def json():
            return {}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def request(self, **kwargs):
            assert kwargs["headers"]["Authorization"] == "Bearer secret"
            return Response()

    monkeypatch.setattr("jarviscore.nexus.store.get_store", local_store_is_forbidden)
    monkeypatch.setattr("jarviscore.nexus.call_proxy.httpx.AsyncClient", Client)

    result = await NexusCallProxy(auth).call(
        "resolved:github", "GET", "https://api.github.com/repos/example/project"
    )

    assert result["ok"] is True


@pytest.mark.asyncio
async def test_refreshed_strategy_is_rechecked_against_requested_host(monkeypatch):
    initial = DynamicStrategy(
        type="oauth2",
        credentials={"access_token": "expired"},
        config={"instance_url": "https://acme.my.salesforce.com"},
    )
    refreshed = DynamicStrategy(
        type="oauth2",
        credentials={"access_token": "fresh"},
        config={"instance_url": "https://evil.example.com"},
    )
    nexus_client = SimpleNamespace(refresh_connection=AsyncMock())
    auth = SimpleNamespace(
        _connections={"salesforce": "connection-1"},
        _strategy_cache={"connection-1": initial},
        nexus_client=nexus_client,
        resolve_strategy=AsyncMock(side_effect=[initial, refreshed]),
    )

    class Response:
        status_code = 401
        text = "unauthorized"
        content = b"unauthorized"
        headers = {}

        @staticmethod
        def json():
            return None

    class Client:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def request(self, **kwargs):
            self.calls += 1
            return Response()

    client = Client()
    monkeypatch.setattr(
        "jarviscore.nexus.call_proxy.httpx.AsyncClient", lambda: client
    )

    with pytest.raises(HostNotAllowed):
        await NexusCallProxy(auth).call(
            "connection-1",
            "GET",
            "https://acme.my.salesforce.com/services/data",
        )

    assert client.calls == 1
    nexus_client.refresh_connection.assert_awaited_once_with("connection-1")


# ── Subdomain patterns ───────────────────────────────────────────────────────

def test_a_tenant_subdomain_matches_its_pattern():
    ensure_host_allowed("agilecrm", "https://acme.agilecrm.com/dev/api/contacts")


def test_a_lookalike_domain_does_not_match_the_pattern():
    """agilecrm.com.evil.net ends with the brand but is not the brand."""
    with pytest.raises(HostNotAllowed):
        ensure_host_allowed("agilecrm", "https://acme.agilecrm.com.evil.net/x")


def test_the_bare_pattern_domain_is_not_silently_allowed():
    with pytest.raises(HostNotAllowed):
        ensure_host_allowed("agilecrm", "https://agilecrm.com/")


# ── The derived data stays honest ────────────────────────────────────────────

def test_every_provider_with_atoms_has_hosts_or_is_tenant_hosted():
    """New atoms must not quietly arrive for a provider nothing can bind."""
    tenant_hosted = {"dynamics", "odoo", "oracle_cx", "oracle_erp", "salesforce"}
    atoms = Path("jarviscore/integrations/atoms")
    if not atoms.exists():
        pytest.skip("atom corpus not present in this checkout")

    unbound = [
        d.name
        for d in atoms.iterdir()
        if d.is_dir()
        and not allowed_hosts(d.name)
        and d.name not in tenant_hosted
    ]
    assert unbound == [], (
        f"providers with atoms but no known hosts: {unbound}. "
        "Run scripts/derive_provider_hosts.py."
    )


def test_the_shipped_data_matches_the_corpus():
    """The catalogue is generated; a stale copy would silently widen or narrow it."""
    data = Path("jarviscore/nexus/_data/provider_hosts.json")
    if not data.exists():
        pytest.skip("host data not present in this checkout")
    shipped = json.loads(data.read_text())
    assert shipped["hubspot"] == ["api.hubapi.com"]
    assert tuple(shipped["slack"]) == allowed_hosts("slack")
    assert all(hosts for hosts in shipped.values()), "empty host list shipped"
