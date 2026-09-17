"""A consent completed elsewhere must be visible here.

Every process started knowing only the connections it had made itself. A
person approved Google Drive in the desk, the token landed at the broker, and
the next run had no idea: it asked them to approve access they had just given.
"""

import pytest

from jarviscore.auth.manager import AuthenticationManager


class FakeGateway:
    """Answers /v1/resolve the way the gateway does, keyed by provider."""

    def __init__(self, active):
        self.active = active
        self.asked = []

    async def resolve_active(self, provider, user_id):
        self.asked.append(provider)
        return self.active.get(provider)


PAYLOAD = {
    "access_token": "ya29.real",
    "token_type": "Bearer",
    "strategy": {"type": "oauth2"},
    "credentials": {
        "access_token": "ya29.real",
        "expired": False,
        "expires_in": 3599,
        "expires_at": "2099-01-01T00:00:00Z",
        "scope": "drive.readonly",
        "token_type": "Bearer",
    },
    "health_status": "degraded",
}


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setenv("NEXUS_GATEWAY_URL", "http://gateway.test")
    m = AuthenticationManager({})
    m.nexus_client = FakeGateway({"google_drive": PAYLOAD})
    return m


async def test_a_fresh_process_finds_the_token_it_did_not_make(manager):
    assert manager.is_connected("google_drive") is False
    handle = await manager.discover("google_drive")
    assert handle is not None
    assert manager.is_connected("google_drive") is True


async def test_nothing_active_means_nothing_discovered(manager):
    assert await manager.discover("slack") is None
    assert manager.is_connected("slack") is False


async def test_discovery_asks_once_per_provider(manager):
    await manager.discover("google_drive")
    await manager.discover("google_drive")
    assert manager.nexus_client.asked == ["google_drive"]


async def test_a_discovered_handle_resolves_to_a_usable_strategy(manager):
    handle = await manager.discover("google_drive")
    strategy = await manager.resolve_strategy(handle)
    assert strategy.type == "oauth2"
    assert strategy.credentials["access_token"] == "ya29.real"


def test_gateway_bookkeeping_is_not_mistaken_for_credentials():
    """expired=False and expires_in=3599 ride alongside the token; they are not it."""
    strategy = AuthenticationManager._strategy_from_resolve(PAYLOAD)
    assert set(strategy.credentials) == {"access_token", "scope", "token_type"}
    assert strategy.expires_at == "2099-01-01T00:00:00Z"


async def test_discovery_clears_a_stale_attention_flag(manager):
    """Re-consent that completed elsewhere is re-consent."""
    manager._needs_attention.add("google_drive")
    await manager.discover("google_drive")
    assert manager.providers_needing_attention() == []


async def test_a_discovered_connection_that_vanishes_needs_attention(manager):
    handle = await manager.discover("google_drive")
    manager.nexus_client.active.clear()
    with pytest.raises(RuntimeError):
        await manager.resolve_strategy(handle)
    assert manager.is_connected("google_drive") is False
    assert manager.providers_needing_attention() == ["google_drive"]


def test_the_cli_and_the_runtime_share_one_identity(monkeypatch):
    """Seeded apps landed in a workspace the agents never looked in."""
    import uuid
    from jarviscore.config import Settings

    monkeypatch.delenv("NEXUS_USER_ID", raising=False)
    monkeypatch.setenv("NEXUS_GATEWAY_URL", "http://gateway.test")
    runtime = AuthenticationManager({}).user_id
    cli = Settings().nexus_default_user_id
    assert runtime == cli
    assert uuid.uuid5(uuid.NAMESPACE_DNS, runtime) == uuid.uuid5(uuid.NAMESPACE_DNS, cli)
