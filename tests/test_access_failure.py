"""What the credential boundary refused must outlive the code that caught it.

Generated code wraps calls in `except Exception` and returns `str(e)`. The type
is gone by the time anyone looks, which is why the verdict used to be recovered
by matching substrings of the message, and why "Created 401 contacts
successfully" was read as an authentication failure.
"""

import pytest

from jarviscore.execution.coder_sandbox import create_coder_sandbox
from jarviscore.nexus.hosts import HostNotAllowed
from jarviscore.nexus.strategy import StrategyError


SWALLOWS_EVERYTHING = """
async def main():
    try:
        r = await nexus_call('GET', 'https://example.invalid/thing')
        return {'ok': True, 'data': r}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
"""


class FakeProxy:
    """Stands in for NexusCallProxy; raises or returns what the test needs."""

    def __init__(self, outcome):
        self.outcome = outcome

    async def call(self, connection_id, method, url, **kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _sandbox(outcome):
    return create_coder_sandbox(timeout=10, nexus_call_proxy=FakeProxy(outcome))


async def _run(sandbox, provider="slack"):
    return await sandbox.execute(
        SWALLOWS_EVERYTHING,
        context={"_nexus_connection_id": provider, "_nexus_provider": provider},
    )


async def test_a_missing_credential_is_recorded_despite_being_caught():
    out = await _run(_sandbox(StrategyError("this connection has no access token")))
    assert out["access_failure"]["kind"] == "no_usable_credential"
    assert out["access_failure"]["provider"] == "slack"


async def test_a_refused_destination_is_recorded_despite_being_caught():
    out = await _run(_sandbox(HostNotAllowed("not your host")), provider="hubspot")
    assert out["access_failure"]["kind"] == "destination_not_owned_by_provider"
    assert out["access_failure"]["provider"] == "hubspot"


async def test_a_provider_rejection_is_recorded_as_evidence():
    out = await _run(_sandbox({"ok": False, "status_code": 401, "body": "nope"}))
    failure = out["access_failure"]
    assert failure["kind"] == "provider_rejected_credential"
    assert failure["status_code"] == 401


async def test_a_working_call_records_nothing():
    out = await _run(_sandbox({"ok": True, "status_code": 200, "body": "{}"}))
    assert out["access_failure"] is None


async def test_an_ordinary_failure_records_nothing():
    """A bug in the code is not an access problem, whatever the message says."""
    sandbox = _sandbox({"ok": True, "status_code": 200, "body": "{}"})
    out = await sandbox.execute(
        "async def main():\n    raise ValueError('Created 401 contacts, then broke')",
        context={"_nexus_connection_id": "slack", "_nexus_provider": "slack"},
    )
    assert out["status"] == "failure"
    assert out["access_failure"] is None


async def test_a_later_clean_run_does_not_inherit_an_earlier_refusal():
    sandbox = _sandbox(StrategyError("no token"))
    first = await _run(sandbox)
    assert first["access_failure"] is not None

    sandbox._nexus_call_proxy = FakeProxy({"ok": True, "status_code": 200, "body": "{}"})
    second = await _run(sandbox)
    assert second["access_failure"] is None
