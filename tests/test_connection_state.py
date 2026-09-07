"""Registering an app and connecting an account are different events.

Collapsing them is how a missing consent step surfaced as an opaque 401 deep
inside an agent run: the vault held a client_id and secret, every caller read
that as "connected", and the failure appeared at the far end of the call instead
of as a consent request before it.
"""

import pytest

from jarviscore.nexus.models import DynamicStrategy
from jarviscore.nexus.store import ConnectionState, NexusLocalStore
from jarviscore.nexus.strategy import unmet_requirement


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVISCORE_MASTER_KEY", "test-key-for-vault-state")
    return NexusLocalStore(path=tmp_path / "nexus.enc")


# ── unmet_requirement: the single source of truth ────────────────────────────

def test_oauth2_without_token_is_unmet():
    strategy = DynamicStrategy(
        type="oauth2", credentials={"client_id": "abc", "client_secret": "shh"}
    )
    reason = unmet_requirement(strategy)
    assert reason is not None
    assert "access token" in reason


def test_oauth2_with_token_is_met():
    strategy = DynamicStrategy(type="oauth2", credentials={"access_token": "tok"})
    assert unmet_requirement(strategy) is None


def test_api_key_without_placement_is_unmet():
    """A key with nowhere to go cannot sign a call, however present it is."""
    strategy = DynamicStrategy(type="api_key", credentials={"api_key": "k"})
    reason = unmet_requirement(strategy)
    assert reason is not None
    assert "placement" in reason


def test_api_key_with_placement_is_met():
    strategy = DynamicStrategy(
        type="api_key",
        credentials={"api_key": "k"},
        config={"header_name": "Authorization", "value_prefix": "Bearer "},
    )
    assert unmet_requirement(strategy) is None


def test_absent_strategy_is_unmet():
    assert unmet_requirement(None) is not None


# ── connection_state ─────────────────────────────────────────────────────────

def test_unregistered_provider_is_absent(store):
    assert store.connection_state("hubspot") is ConnectionState.ABSENT


def test_oauth_app_without_consent_is_registered_not_connected(store):
    store.register(
        "slack",
        {"auth_type": "oauth2", "client_id": "abc", "client_secret": "shh"},
    )
    assert store.connection_state("slack") is ConnectionState.REGISTERED
    assert store.needs_consent("slack") is True


def test_oauth_app_with_token_is_connected(store):
    store.register(
        "slack", {"auth_type": "oauth2", "access_token": "xoxb-real"}
    )
    assert store.connection_state("slack") is ConnectionState.CONNECTED
    assert store.needs_consent("slack") is False


def test_api_key_with_placement_is_connected(store):
    store.register(
        "hubspot",
        {
            "auth_type": "api_key",
            "api_key": "pat-na1-xxx",
            "auth_config": {
                "header_name": "Authorization",
                "value_prefix": "Bearer ",
            },
        },
    )
    assert store.connection_state("hubspot") is ConnectionState.CONNECTED


def test_api_key_without_placement_is_not_connected(store):
    """Present but unplaceable is not usable, and must not read as connected."""
    store.register("mystery", {"auth_type": "api_key", "api_key": "k"})
    assert store.connection_state("mystery") is ConnectionState.REGISTERED


def test_non_oauth_gap_does_not_ask_for_consent(store):
    """Consent is an OAuth remedy; an unplaceable key needs a different fix."""
    store.register("mystery", {"auth_type": "api_key", "api_key": "k"})
    assert store.needs_consent("mystery") is False


def test_unsupported_auth_type_is_registered_not_connected(store):
    store.register("weird", {"auth_type": "carrier_pigeon", "api_key": "k"})
    assert store.connection_state("weird") is ConnectionState.REGISTERED
