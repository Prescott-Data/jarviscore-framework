"""An unconsented provider should produce a request, not a dead end.

The agent can see that a capability exists and cannot run it. Reporting that to
a human who only had to click once is a dead end, so the ask belongs in the loop.
"""

import pytest

from jarviscore.kernel.defaults.coder import CoderSubAgent


ATOM_SOURCE = '''\
async def slack_send_message(channel: str, text: str) -> dict:
    """Post a message to a Slack channel."""
    response = await nexus_call(
        "POST", "https://slack.com/api/chat.postMessage",
        json={"channel": channel, "text": text},
    )
    return {"status": "success", "data": response["json"]}
'''


class FakeRegistry:
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


class FakeAuthManager:
    """Stands in for the gateway handshake; records that consent was asked for."""

    def __init__(self, outcome="conn-123"):
        self.outcome = outcome
        self.asked = []
        self.presented = []
        self.return_url = "http://127.0.0.1:8765/"
        manager = self

        class Flow:
            async def present_auth_url(self, url, provider, **kwargs):
                manager.presented.append((url, provider, kwargs))

        self.flow_handler = Flow()

    async def begin_authentication(self, provider, **kwargs):
        self.asked.append(provider)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome, "https://provider.test/consent"


@pytest.fixture
def coder(monkeypatch):
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._tools = {}
    agent._atom_tools = []
    agent._access_tools = []
    agent._atoms = {}
    agent._run_context = {}
    agent.auth_manager = FakeAuthManager()
    agent.code_registry = FakeRegistry(
        {"slack_send_message": {"system": "slack", "code": ATOM_SOURCE}}
    )

    def register_tool(name, fn, description, phase=None):
        agent._tools[name] = (fn, description, phase)

    agent.register_tool = register_tool

    class _Log:
        def info(self, *a, **k):
            pass

        def debug(self, *a, **k):
            pass

        def error(self, *a, **k):
            pass

    agent._log = _Log()
    return agent


def _set_consent(monkeypatch, needs, providers=("slack",)):
    class _Store:
        def list(self):
            return list(providers)

        def needs_consent(self, provider):
            return needs

    monkeypatch.setattr("jarviscore.nexus.store.get_store", lambda: _Store())


def test_unconsented_provider_offers_the_ask(coder, monkeypatch):
    _set_consent(monkeypatch, needs=True)
    coder._offer_access_request()
    assert "request_access" in coder._tools
    description = coder._tools["request_access"][1]
    assert "slack (1 capabilities)" in description


def test_connected_provider_offers_no_ask(coder, monkeypatch):
    _set_consent(monkeypatch, needs=False)
    coder._offer_access_request()
    assert "request_access" not in coder._tools


def test_consent_is_offered_without_the_system_being_named_first(coder, monkeypatch):
    """The agent often works out the provider itself; the ask must not wait."""
    _set_consent(monkeypatch, needs=True)
    coder._offer_access_request(None)
    assert "request_access" in coder._tools


async def test_consent_yields_without_waiting_or_offering_dead_capabilities(
    coder, monkeypatch
):
    """Consent is a durable pause; the callback resumes the same run."""
    _set_consent(monkeypatch, needs=True)
    coder._offer_access_request()
    assert "slack_send_message" not in coder._tools

    result = await coder._tools["request_access"][0](system="slack")

    assert result["status"] == "waiting"
    assert result["typed_outcome"] == "WAITING_FOR_CONSENT"
    assert coder.auth_manager.asked == ["slack"]
    assert "slack_send_message" not in coder._tools
    assert coder.auth_manager.presented[0][1] == "slack"


async def test_wait_result_carries_the_handle_needed_to_resume(coder, monkeypatch):
    _set_consent(monkeypatch, needs=True)
    coder._offer_access_request()
    result = await coder._tools["request_access"][0](system="slack")
    assert result["connection_id"] == "conn-123"
    assert result["system"] == "slack"


async def test_a_handshake_that_cannot_start_is_reported(coder, monkeypatch):
    _set_consent(monkeypatch, needs=True)
    coder.auth_manager = FakeAuthManager(outcome=RuntimeError("timed out"))
    coder._offer_access_request()

    result = await coder._tools["request_access"][0](system="slack")

    assert result["status"] == "error"
    assert result["semantic_error"] == "CONSENT_NOT_STARTED"
    assert "slack_send_message" not in coder._tools


async def test_no_gateway_says_so_instead_of_pretending(coder, monkeypatch):
    _set_consent(monkeypatch, needs=True)
    coder.auth_manager = None
    coder._offer_access_request()

    result = await coder._tools["request_access"][0](system="slack")

    assert result["semantic_error"] == "NO_CONSENT_CHANNEL"


# ── Capabilities are held back until they can actually fire ──────────────────

def _set_state(monkeypatch, state, *, needs_consent):
    class _Store:
        def list(self):
            return ["slack"]

        def connection_state(self, provider):
            return state

        def needs_consent(self, provider):
            return needs_consent

    monkeypatch.setattr("jarviscore.nexus.store.get_store", lambda: _Store())


def test_an_unconnected_provider_offers_consent_not_capabilities(coder, monkeypatch):
    """A confident call that cannot be signed reads as a broken capability."""
    from jarviscore.nexus.store import ConnectionState

    _set_state(monkeypatch, ConnectionState.REGISTERED, needs_consent=True)
    coder._prepare_access("slack")

    assert "slack_send_message" not in coder._tools
    assert "request_access" in coder._tools


def test_a_connected_provider_offers_capabilities(coder, monkeypatch):
    from jarviscore.nexus.store import ConnectionState

    _set_state(monkeypatch, ConnectionState.CONNECTED, needs_consent=False)
    coder._prepare_access("slack")

    assert "slack_send_message" in coder._tools
    assert "request_access" not in coder._tools


def test_a_connected_provider_binds_the_connection_to_itself(coder, monkeypatch):
    """The credential and the capability must point at the same provider."""
    from jarviscore.nexus.store import ConnectionState

    _set_state(monkeypatch, ConnectionState.CONNECTED, needs_consent=False)
    coder._run_context = {"_nexus_connection_id": "hubspot", "_nexus_provider": "hubspot"}
    coder._prepare_access("slack")

    assert coder._run_context["_nexus_connection_id"] == "slack"
    assert coder._run_context["_nexus_provider"] == "slack"


def test_declaring_a_system_mid_run_reports_what_changed(coder, monkeypatch):
    from jarviscore.nexus.store import ConnectionState

    _set_state(monkeypatch, ConnectionState.REGISTERED, needs_consent=True)
    note = coder._refresh_offerings_for("slack")

    assert note is not None
    assert "request_access" in note
    assert "held back" in note


def test_declaring_the_same_system_twice_changes_nothing(coder, monkeypatch):
    from jarviscore.nexus.store import ConnectionState

    _set_state(monkeypatch, ConnectionState.CONNECTED, needs_consent=False)
    coder._refresh_offerings_for("slack")
    assert coder._refresh_offerings_for("slack") is None


async def test_connection_sync_exposes_provider_names_not_handles(coder, monkeypatch):
    from jarviscore.nexus.store import ConnectionState

    class Manager:
        async def discover_all(self, providers):
            self.discovered = list(providers)

        def is_connected(self, provider):
            return provider in {"gmail", "google_calendar"}

    class Store:
        def list(self):
            return ["gmail", "google_calendar", "hubspot", "slack"]

        def connection_state(self, provider):
            return ConnectionState.CONNECTED if provider == "hubspot" else ConnectionState.REGISTERED

    manager = Manager()
    coder.auth_manager = manager
    coder._run_context = {}
    monkeypatch.setattr("jarviscore.nexus.store.get_store", lambda: Store())

    await coder._sync_connections()

    assert coder._run_context["connected_providers"] == [
        "gmail", "google_calendar", "hubspot",
    ]
    assert "connection" not in str(coder._run_context).lower()
