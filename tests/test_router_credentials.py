"""The router is told whether a declared system can be authenticated (#152).

A CRM agent with a registered HubSpot token was asked to read its contacts. The
router saw `system: "hubspot"` and a role contract advertising `browser: ...
forms, login flows`, chose browser, and the run ended by asking a human to sign
in to a system it already held a working token for.

The router was choosing rationally from what it was told. It was not told the
thing that mattered, because credentials are resolved after routing and only for
the coder. So resolve first, and put the answer in the payload.
"""

import json

import pytest

from jarviscore.kernel.kernel import (
    CREDENTIALED_ROLES,
    Kernel,
    RoutingDecision,
    TaskRouter,
)


class RecordingRouter:
    def __init__(self, role="browser"):
        self.role = role
        self.contexts = []

    async def route(self, *, task, context=None, agent_default_role=None):
        self.contexts.append(dict(context or {}))
        return RoutingDecision(role=self.role, confidence=0.9, reason="test")


def _kernel(router, *, vault=None):
    kernel = Kernel.__new__(Kernel)
    kernel._task_router = router
    kernel.auth_manager = None
    kernel._role_lease_profiles = {
        "coder": object(), "browser": object(),
        "researcher": object(), "communicator": object(),
    }
    kernel._vault = vault or {}
    return kernel


@pytest.fixture
def local_vault(monkeypatch):
    """Stand in for the Nexus local store.

    Models the distinction the real store draws: holding a provider's app is not
    the same as holding a credential that can sign a call for it.
    """
    from jarviscore.nexus.store import ConnectionState

    class Store:
        def __init__(self):
            self._connected = set()
            self._unconsented = set()

        def add(self, name):
            self._connected.add(name)

        def awaiting_consent(self, name):
            self._unconsented.add(name)

        def list(self):
            return sorted(self._connected | self._unconsented)

        def get(self, name):
            if name in self._connected or name in self._unconsented:
                return {"token": "..."}
            return None

        def connection_state(self, name):
            if name in self._connected:
                return ConnectionState.CONNECTED
            if name in self._unconsented:
                return ConnectionState.REGISTERED
            return ConnectionState.ABSENT

        def needs_consent(self, name):
            return name in self._unconsented

    store = Store()
    monkeypatch.setattr(
        "jarviscore.nexus.store.get_store", lambda: store, raising=False,
    )
    return store


# ──────────────────────────────────────────────────────────────────
# The router is told
# ──────────────────────────────────────────────────────────────────

class TestRouterSeesCredentials:

    @pytest.mark.asyncio
    async def test_a_resolvable_system_is_reported_as_available(self, local_vault):
        local_vault.add("hubspot")
        router = RecordingRouter(role="coder")
        kernel = _kernel(router)

        await kernel._route_task("Read our CRM", {"system": "hubspot"})

        assert router.contexts[0]["system_credentials_available"] is True

    @pytest.mark.asyncio
    async def test_an_unregistered_system_is_reported_as_unavailable(self, local_vault):
        router = RecordingRouter(role="coder")
        kernel = _kernel(router)

        await kernel._route_task("Read our CRM", {"system": "hubspot"})

        assert router.contexts[0]["system_credentials_available"] is False

    @pytest.mark.asyncio
    async def test_a_registered_but_unconsented_system_is_unavailable(self, local_vault):
        """An app nobody has consented to cannot sign a call, so it is not a credential."""
        local_vault.awaiting_consent("slack")
        router = RecordingRouter(role="coder")
        kernel = _kernel(router)

        await kernel._route_task("Post to Slack", {"system": "slack"})

        assert router.contexts[0]["system_credentials_available"] is False


class TestRouterSeesWhatIsReachable:
    """A task rarely names its provider, so the inventory travels with every route.

    "List our Google Drive files" was routed to browser, which navigated to
    drive.google.com, hit the sign-in wall and asked the human to log in by hand
    to an account whose app was already registered and one click from connected.
    """

    @pytest.mark.asyncio
    async def test_the_router_is_told_what_can_be_reached(self, local_vault):
        local_vault.add("hubspot")
        local_vault.awaiting_consent("google_drive")
        router = RecordingRouter(role="coder")

        await _kernel(router)._route_task("List our Google Drive files", {})

        inventory = router.contexts[0]["providers_reachable_by_api"]
        assert inventory["hubspot"] == "connected"
        assert inventory["google_drive"] == "one_consent_away"

    @pytest.mark.asyncio
    async def test_an_empty_vault_says_nothing(self, local_vault):
        """No providers is not the same as providers that cannot be used."""
        router = RecordingRouter(role="coder")

        await _kernel(router)._route_task("Summarise the quarter", {})

        assert "providers_reachable_by_api" not in router.contexts[0]

    @pytest.mark.asyncio
    async def test_the_inventory_reaches_the_summarised_context(self, local_vault):
        """Dropped in summarisation, it would be as if it were never gathered."""
        from jarviscore.kernel.kernel import TaskRouter

        local_vault.add("hubspot")
        summary = TaskRouter._summarize_context(
            {"providers_reachable_by_api": {"hubspot": "connected"}}
        )
        assert "providers_reachable_by_api" in summary

    @pytest.mark.asyncio
    async def test_no_declared_system_says_nothing_either_way(self, local_vault):
        router = RecordingRouter(role="researcher")
        kernel = _kernel(router)

        await kernel._route_task("Find the top three competitors", {})

        assert "system_credentials_available" not in router.contexts[0]

    @pytest.mark.asyncio
    async def test_the_caller_context_is_not_mutated(self, local_vault):
        local_vault.add("hubspot")
        router = RecordingRouter(role="coder")
        context = {"system": "hubspot"}

        await _kernel(router)._route_task("Read our CRM", context)

        assert context == {"system": "hubspot"}


class TestDiscardedCredentialIsVisible:

    @pytest.mark.asyncio
    async def test_routing_away_from_a_held_credential_warns(self, local_vault, caplog):
        local_vault.add("hubspot")
        router = RecordingRouter(role="browser")

        with caplog.at_level("WARNING"):
            await _kernel(router)._route_task("Read our CRM", {"system": "hubspot"})

        assert "has resolvable credentials" in caplog.text
        assert "browser" in caplog.text

    @pytest.mark.asyncio
    async def test_the_router_is_not_overridden(self, local_vault):
        """A task may genuinely need a UI. The decision stays the router's."""
        local_vault.add("hubspot")
        router = RecordingRouter(role="browser")

        decision = await _kernel(router)._route_task("Read our CRM", {"system": "hubspot"})

        assert decision.role == "browser"

    @pytest.mark.asyncio
    async def test_the_credentialed_route_does_not_warn(self, local_vault, caplog):
        local_vault.add("hubspot")
        router = RecordingRouter(role="coder")

        with caplog.at_level("WARNING"):
            await _kernel(router)._route_task("Read our CRM", {"system": "hubspot"})

        assert "resolvable credentials" not in caplog.text

    @pytest.mark.asyncio
    async def test_no_warning_when_there_is_no_credential_to_discard(self, local_vault, caplog):
        router = RecordingRouter(role="browser")

        with caplog.at_level("WARNING"):
            await _kernel(router)._route_task("Read our CRM", {"system": "hubspot"})

        assert "resolvable credentials" not in caplog.text

    def test_coder_is_the_only_credentialed_role(self):
        """The coder sandbox holds the sole call proxy; this encodes that."""
        assert CREDENTIALED_ROLES == frozenset({"coder"})


class TestExplicitRoleStillWins:

    @pytest.mark.asyncio
    async def test_an_explicit_role_skips_the_router_entirely(self, local_vault):
        local_vault.add("hubspot")
        router = RecordingRouter(role="coder")
        kernel = _kernel(router)

        decision = await kernel._route_task(
            "Read our CRM", {"system": "hubspot"},
            agent_default_role="communicator",
            use_default_role_as_fallback=False,
        )

        assert decision.role == "communicator"
        assert router.contexts == []


# ──────────────────────────────────────────────────────────────────
# The payload the router reads
# ──────────────────────────────────────────────────────────────────

class TestContextSummary:

    def test_credential_availability_is_forwarded(self):
        summary = TaskRouter._summarize_context({
            "system": "hubspot", "system_credentials_available": True,
        })
        assert json.loads(summary["system_credentials_available"]) is True

    def test_values_are_never_cut_mid_json(self):
        """A router reading half a JSON value is reading a different value."""
        summary = TaskRouter._summarize_context({
            "previous_step_results": {"rows": ["x" * 4000]},
        })
        json.loads(summary["previous_step_results"])      # parses, so it is whole

    def test_an_oversized_value_is_withheld_whole_and_named(self):
        summary = TaskRouter._summarize_context({
            "workflow_id": "wf-1",
            "system": "hubspot",
            "previous_step_results": {"rows": ["x" * 20000]},
        })

        assert "previous_step_results" not in summary
        assert "previous_step_results" in summary["withheld"]
        assert json.loads(summary["system"]) == "hubspot"

    def test_routing_essentials_survive_a_crowded_context(self):
        summary = TaskRouter._summarize_context({
            "system": "hubspot",
            "system_credentials_available": True,
            "registry_candidate": {"code": "y" * 30000},
        })

        assert json.loads(summary["system"]) == "hubspot"
        assert json.loads(summary["system_credentials_available"]) is True

    def test_unlisted_keys_are_not_forwarded(self):
        summary = TaskRouter._summarize_context({"_nexus_connection_id": "secret-handle"})
        assert summary == {}

    def test_a_small_context_is_complete(self):
        summary = TaskRouter._summarize_context({"workflow_id": "wf-1", "step_id": "s1"})
        assert "withheld" not in summary
