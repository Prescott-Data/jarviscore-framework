"""The system acts on what it already knows.

Two places noticed something and told nobody. The registry counted successes
and never failures, so an atom that broke stayed golden. The lifecycle monitor
detected revoked tokens and fired a callback that was never attached, so the
next run failed at the provider one full run after the system knew.
"""

import pytest

from jarviscore.auth.manager import AuthenticationManager
from jarviscore.execution.code_registry import FunctionRegistry, FunctionStatus


# ── Registry: stage follows the evidence both ways ───────────────────────────

@pytest.fixture
def registry(tmp_path):
    r = FunctionRegistry(storage_path=str(tmp_path))
    r.function_metadata = {
        "slack_send_message": {
            "function_name": "slack_send_message",
            "system": "slack",
            "registry_stage": "candidate",
        }
    }
    r._save_function_metadata = lambda name: None
    r.sync_registry_index = lambda: None
    return r


def _stage(registry):
    return registry.function_metadata["slack_send_message"]["registry_stage"]


def _run(registry, success, n=1, error_type=None):
    for _ in range(n):
        registry.update_execution_stats(
            "slack_send_message", success=success, execution_time=0.1, error_type=error_type
        )


def test_one_success_verifies(registry):
    _run(registry, True)
    assert _stage(registry) == FunctionStatus.VERIFIED.value


def test_five_consecutive_successes_are_golden(registry):
    _run(registry, True, n=5)
    assert _stage(registry) == FunctionStatus.GOLDEN.value


def test_a_golden_atom_that_breaks_is_no_longer_golden(registry):
    """'Verified' used to mean 'worked five times once', not 'works'."""
    _run(registry, True, n=5)
    _run(registry, False, error_type="KeyError")
    assert _stage(registry) == FunctionStatus.VERIFIED.value
    meta = registry.function_metadata["slack_send_message"]
    assert meta["failure_count"] == 1
    assert meta["last_failure"]["error_type"] == "KeyError"


def test_a_verified_atom_that_breaks_is_a_candidate_again(registry):
    _run(registry, True)
    _run(registry, False)
    assert _stage(registry) == FunctionStatus.CANDIDATE.value


def test_a_failure_resets_the_run_not_the_history(registry):
    """Lifetime counts are kept; the stage answers 'does it work now'."""
    _run(registry, True, n=5)
    _run(registry, False)
    meta = registry.function_metadata["slack_send_message"]
    assert meta["success_count"] == 5
    assert meta["consecutive_successes"] == 0


def test_golden_must_be_earned_again_after_a_failure(registry):
    _run(registry, True, n=5)
    _run(registry, False)
    _run(registry, True)
    assert _stage(registry) == FunctionStatus.VERIFIED.value
    _run(registry, True, n=4)
    assert _stage(registry) == FunctionStatus.GOLDEN.value


# ── Lifecycle: a revoked token withdraws the handle ──────────────────────────

@pytest.fixture
def manager(monkeypatch):
    monkeypatch.setenv("NEXUS_GATEWAY_URL", "http://gateway.test")
    m = AuthenticationManager({})
    m._connections["slack"] = "conn-slack"
    m._connections["hubspot"] = "conn-hubspot"
    m._strategy_cache["conn-slack"] = (object(), 0.0)
    return m


def test_the_monitor_is_built_with_a_listener(manager):
    """It accepted on_attention and was constructed without one."""
    assert manager.lifecycle_monitor.on_attention is not None


def test_attention_withdraws_the_handle(manager):
    manager._connection_needs_attention("conn-slack")
    assert manager.is_connected("slack") is False
    assert manager.is_connected("hubspot") is True


def test_attention_names_the_provider_that_needs_a_person(manager):
    manager._connection_needs_attention("conn-slack")
    assert manager.providers_needing_attention() == ["slack"]


def test_attention_drops_the_cached_strategy(manager):
    """A cached strategy for a revoked connection is a stale credential."""
    manager._connection_needs_attention("conn-slack")
    assert "conn-slack" not in manager._strategy_cache


def test_attention_for_an_unknown_connection_changes_nothing(manager):
    manager._connection_needs_attention("conn-nobody")
    assert manager.is_connected("slack") is True
    assert manager.providers_needing_attention() == []


# ── The loop sees it: re-consent is offered before the next failed run ───────

def test_a_revoked_provider_is_offered_for_reconsent(manager, monkeypatch):
    """The point of wiring the callback: the agent can ask before it fails."""
    from jarviscore.kernel.defaults.coder import CoderSubAgent

    class _Store:
        def list(self):
            return []

        def needs_consent(self, provider):
            return False

    monkeypatch.setattr("jarviscore.nexus.store.get_store", lambda: _Store())

    coder = CoderSubAgent.__new__(CoderSubAgent)
    coder._tools = {}
    coder._access_tools = []
    coder._atoms = {}
    coder._run_context = {}
    coder.code_registry = None
    coder.auth_manager = manager
    coder.register_tool = lambda n, f, d, phase=None: coder._tools.__setitem__(n, (f, d, phase))

    class _Log:
        def debug(self, *a, **k):
            pass

    coder._log = _Log()

    coder._offer_access_request()
    assert "request_access" not in coder._tools

    manager._connection_needs_attention("conn-slack")
    coder._offer_access_request()
    assert "request_access" in coder._tools
    assert "slack" in coder._tools["request_access"][1]
