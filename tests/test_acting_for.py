"""A shared agent uses the accounts of the person it is working for."""

import pytest

from jarviscore.auth.manager import AuthenticationManager
from jarviscore.auth.principal import act_for, acting_for
from jarviscore.core.mesh import Mesh


class FakeGateway:
    """Each person's workspace holds their own connections."""

    def __init__(self, accounts):
        self.accounts = accounts  # {(person, provider): token}
        self.asked = []

    async def resolve_active(self, provider, user_id):
        self.asked.append((provider, user_id))
        token = self.accounts.get((user_id, provider))
        return {"access_token": token, "strategy": {"type": "oauth2"}} if token else None


@pytest.fixture
def manager(monkeypatch):
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)
    m = AuthenticationManager({"nexus_default_user_id": "service"})
    m.nexus_client = FakeGateway({
        ("alice", "github"): "alice-token",
        ("bob", "github"): "bob-token",
        ("service", "slack"): "service-token",
    })
    return m


async def test_a_step_for_alice_uses_alices_account(manager):
    with act_for("alice"):
        handle = await manager.discover("github")
        strategy = await manager.resolve_strategy(handle)
    assert handle == "resolved:alice:github"
    assert strategy.credentials["access_token"] == "alice-token"
    assert manager.nexus_client.asked == [("github", "alice"), ("github", "alice")]


async def test_people_never_see_each_others_connections(manager):
    with act_for("alice"):
        alice = await manager.discover("github")
    with act_for("bob"):
        assert not manager.is_connected("github"), "alice's connection is not bob's"
        bob = await manager.discover("github")
        assert manager.connection_handle("github") == bob
    with act_for("carol"):
        assert await manager.discover("github") is None
    assert alice != bob
    assert (await manager.resolve_strategy(bob)).credentials["access_token"] == "bob-token"


async def test_a_handle_keeps_its_owner_outside_the_step(manager):
    with act_for("alice"):
        handle = await manager.discover("github")
    strategy = await manager.resolve_strategy(handle)
    assert strategy.credentials["access_token"] == "alice-token"


async def test_with_nobody_set_the_deployment_identity_is_used(manager):
    handle = await manager.discover("slack")
    assert handle == "resolved:slack"
    assert acting_for.get() is None


async def test_a_dead_connection_is_withdrawn_whoever_it_belonged_to(manager):
    with act_for("alice"):
        handle = await manager.discover("github")
    manager._connection_needs_attention(handle)
    with act_for("alice"):
        assert not manager.is_connected("github")
        assert manager.providers_needing_attention() == ["github"]
    assert manager.providers_needing_attention() == []


def test_only_the_registered_workflow_names_who_it_is_for():
    assert Mesh._acting_for({"context": {"acting_for": "alice"}}) == "alice"
    assert Mesh._acting_for({"context": {}}) is None
    assert Mesh._acting_for({}) is None


def test_act_for_nobody_changes_nothing():
    with act_for("alice"):
        with act_for(""):
            assert acting_for.get() == "alice"
    assert acting_for.get() is None
