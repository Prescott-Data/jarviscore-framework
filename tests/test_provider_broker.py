"""The provider broker: decided before any I/O, refused in strict mode, recorded either way."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarviscore.control import policy as policy_module
from jarviscore.control.operations import read_operations
from jarviscore.control.policy import PolicyDenied
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import verify
from jarviscore.nexus import call_proxy as proxy_module
from jarviscore.nexus.call_proxy import NexusCallProxy
from jarviscore.nexus.models import DynamicStrategy

ISSUES = '''
async def github_create_issue(owner: str, repo: str, title: str) -> dict:
    return await nexus_call("POST", f"https://api.github.com/repos/{owner}/{repo}/issues", json={"title": title})
'''


class Response:
    status_code = 201
    text = "{}"
    content = b"{}"
    headers = {}

    @staticmethod
    def json():
        return {}


class Client:
    made = 0

    def __init__(self):
        Client.made += 1
        self.requests = []

    async def request(self, **kwargs):
        self.requests.append(kwargs)
        return Response()


@pytest.fixture
def broker(monkeypatch, tmp_path):
    def configure(mode):
        monkeypatch.setenv("JARVISCORE_CONTROL_MODE", mode)
        monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
        monkeypatch.delenv("JARVISCORE_CONTROL_POLICY", raising=False)
        monkeypatch.setattr(policy_module, "_cached", None)
        monkeypatch.setattr(journal_module, "_journal", None)
        Client.made = 0
        monkeypatch.setattr("jarviscore.nexus.call_proxy.httpx.AsyncClient", Client)
        monkeypatch.setattr(proxy_module, "_clients", proxy_module.weakref.WeakKeyDictionary())
        auth = SimpleNamespace(
            _connections={"github": "connection-1"},
            _strategy_cache={},
            nexus_client=None,
            resolve_strategy=AsyncMock(return_value=DynamicStrategy(
                type="oauth2", credentials={"access_token": "secret"},
            )),
        )
        return NexusCallProxy(auth), auth, str(tmp_path / "journal")
    return configure


def kinds(root, run):
    from jarviscore.evidence.journal import Journal
    import json

    with open(Journal(root).run_path(run), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


@pytest.mark.asyncio
async def test_strict_mode_refuses_before_any_io(broker):
    proxy, auth, root = broker("strict")

    with pytest.raises(PolicyDenied) as refused:
        await proxy.call("connection-1", "DELETE", "https://api.github.com/repos/a/b",
                         authority={"workflow_id": "wf", "step_id": "s0"})

    assert refused.value.decision.rule == "mutation-without-atom"
    auth.resolve_strategy.assert_not_awaited()
    assert Client.made == 0
    events = kinds(root, "wf/s0")
    assert [e["kind"] for e in events] == ["policy.decision"]
    assert events[0]["data"]["outcome"] == "deny" and events[0]["data"]["enforced"] is True
    assert verify(root).ok


@pytest.mark.asyncio
async def test_report_mode_records_the_refusal_and_lets_the_call_through(broker):
    proxy, _, root = broker("report")

    result = await proxy.call("connection-1", "DELETE", "https://api.github.com/repos/a/b",
                              authority={"workflow_id": "wf", "step_id": "s0"})

    assert result["ok"]
    events = kinds(root, "wf/s0")
    assert [e["kind"] for e in events] == ["policy.decision", "effect.attempt", "effect.outcome"]
    assert events[0]["data"]["outcome"] == "deny" and events[0]["data"]["enforced"] is False
    report = verify(root)
    assert report.ok and report.effects == 1


@pytest.mark.asyncio
async def test_an_allowed_atom_call_is_recorded_without_query_or_body(broker):
    proxy, _, root = broker("strict")
    contract = read_operations(ISSUES, "github_create_issue")

    await proxy.call(
        "connection-1", "POST", "https://api.github.com/repos/acme/app/issues?secret=1",
        json={"title": "private title"},
        authority={"workflow_id": "wf", "step_id": "s1", "atom": "github_create_issue",
                   "effect": "write", "code_origin": "model", "contract": contract, "action_id": "a1"},
    )

    events = kinds(root, "wf/s1")
    decision = events[0]["data"]
    assert decision["outcome"] == "allow" and decision["verified"] is True
    assert decision["path"] == "/repos/acme/app/issues"
    flat = str(events)
    assert "secret" not in flat and "private title" not in flat
    assert events[2]["data"]["status"] == 201


@pytest.mark.asyncio
async def test_model_written_code_outside_its_contract_is_refused(broker):
    proxy, _, _ = broker("strict")
    contract = read_operations(ISSUES, "github_create_issue")

    with pytest.raises(PolicyDenied) as refused:
        await proxy.call(
            "connection-1", "POST", "https://api.github.com/repos/acme/app/collaborators",
            authority={"atom": "github_create_issue", "effect": "write", "code_origin": "model",
                       "contract": contract, "action_id": "a2"},
        )

    assert refused.value.decision.rule == "outside-contract"
    assert Client.made == 0


@pytest.mark.asyncio
async def test_calls_on_one_loop_share_one_connection_pool(broker):
    proxy, _, _ = broker("report")

    for _ in range(3):
        await proxy.call("connection-1", "GET", "https://api.github.com/repos/a/b")

    assert Client.made == 1


@pytest.mark.asyncio
async def test_strict_mode_refuses_a_call_it_cannot_record(broker, monkeypatch):
    proxy, auth, _ = broker("strict")

    def unwritable(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(journal_module.Journal, "append", unwritable)

    with pytest.raises(RuntimeError, match="could not be recorded"):
        await proxy.call("connection-1", "GET", "https://api.github.com/repos/a/b")
    auth.resolve_strategy.assert_not_awaited()


@pytest.mark.asyncio
async def test_off_mode_neither_decides_nor_records(broker):
    proxy, _, root = broker("off")

    await proxy.call("connection-1", "DELETE", "https://api.github.com/repos/a/b",
                     authority={"workflow_id": "wf", "step_id": "s9"})

    import os
    assert not os.path.exists(root)


@pytest.mark.asyncio
async def test_a_mutation_to_a_provider_that_deduplicates_carries_the_operation_id(broker):
    proxy, auth, _ = broker("report")
    auth._connections = {"stripe": "connection-1"}
    seen = {}

    async def request(**kwargs):
        seen.update(kwargs)
        return Response()

    Client.request = staticmethod(request)
    try:
        await proxy.call("connection-1", "POST", "https://api.stripe.com/v1/refunds",
                         authority={"atom": "stripe_create_refund", "effect": "write",
                                    "code_origin": "shipped", "action_id": "op-123"})
    finally:
        del Client.request

    assert seen["headers"]["Idempotency-Key"] == "op-123"


def test_a_square_payment_retried_carries_the_same_idempotency_key():
    import asyncio
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "jarviscore/integrations/atoms/square"
    for kind in ("payment", "customer", "order"):
        bodies = []

        async def nexus_call(method, url, **kwargs):
            bodies.append(kwargs.get("json"))
            return {"ok": True, "status_code": 200, "json": {}, "body": "{}", "content": b"{}"}

        namespace = {"nexus_call": nexus_call}
        exec(compile((root / f"square_create_{kind}.py").read_text(), kind, "exec"), namespace)
        create = namespace[f"square_create_{kind}"]
        asyncio.run(create({"amount": 5, "note": "a"}))
        asyncio.run(create({"amount": 5, "note": "a"}))
        asyncio.run(create({"amount": 6, "note": "a"}))

        keys = [body["idempotency_key"] for body in bodies]
        assert keys[0] == keys[1] != keys[2], kind
