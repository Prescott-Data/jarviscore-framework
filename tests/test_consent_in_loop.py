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

    async def authenticate(self, provider):
        self.asked.append(provider)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


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


async def test_consent_makes_capabilities_callable_in_the_same_run(
    coder, monkeypatch
):
    """The point of the whole mechanism: the run continues, it does not restart."""
    _set_consent(monkeypatch, needs=True)
    coder._offer_access_request()
    assert "slack_send_message" not in coder._tools

    result = await coder._tools["request_access"][0](system="slack")

    assert result["status"] == "success"
    assert coder.auth_manager.asked == ["slack"]
    assert "slack_send_message" in coder._tools
    assert result["capabilities"] == ["slack_send_message"]


async def test_consent_routes_later_calls_through_the_gateway(coder, monkeypatch):
    """The token lands at the gateway, not in the local vault that holds the app."""
    _set_consent(monkeypatch, needs=True)
    coder._offer_access_request()
    await coder._tools["request_access"][0](system="slack")
    assert coder._run_context["_nexus_connection_id"] == "conn-123"
    assert coder._run_context["_nexus_provider"] == "slack"


async def test_abandoned_consent_is_reported_not_raised(coder, monkeypatch):
    _set_consent(monkeypatch, needs=True)
    coder.auth_manager = FakeAuthManager(outcome=RuntimeError("timed out"))
    coder._offer_access_request()

    result = await coder._tools["request_access"][0](system="slack")

    assert result["status"] == "error"
    assert result["semantic_error"] == "CONSENT_NOT_COMPLETED"
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
