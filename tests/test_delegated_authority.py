"""Acting for a person: their credential only, within what they delegated, on record."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from jarviscore.auth.principal import act_for
from jarviscore.control import mandate as mandate_module
from jarviscore.control import policy as policy_module
from jarviscore.control.policy import PolicyDenied
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import Journal, verify
from jarviscore.nexus import call_proxy as proxy_module
from jarviscore.nexus.call_proxy import NexusCallProxy
from jarviscore.nexus.client import NexusClient
from jarviscore.nexus.models import DynamicStrategy

READ_ONLY_ERP = {"systems": ["erp"], "effects": ["read"], "expires_at": "2099-01-01T00:00:00Z"}


# ── The mandate ─────────────────────────────────────────────────────────────


def test_a_mandate_holds_work_to_the_systems_effects_and_time_delegated():
    granted = mandate_module.parse(READ_ONLY_ERP)

    assert granted.refusal("erp", "read") is None
    assert "did not delegate github" in granted.refusal("github", "read")
    assert "did not delegate write" in granted.refusal("erp", "write")
    assert "expired" in mandate_module.parse({"expires_at": 0}).refusal("erp", "read")
    assert mandate_module.parse(None) is None


@pytest.mark.parametrize("raw", [
    "everything", {"systems": "erp"}, {"effects": ["delete"]}, {"scopes": ["x"]}, {"expires_at": "tomorrow"},
    {"expires_at": "2099-01-01T00:00:00"},
])
def test_a_mandate_that_cannot_be_read_refuses_everything(raw):
    unreadable = mandate_module.parse(raw)

    assert unreadable.invalid and "cannot be read" in unreadable.refusal("erp", "read")


# ── At the broker ───────────────────────────────────────────────────────────


class Response:
    status_code = 200
    text = "{}"
    content = b"{}"
    headers = {}

    @staticmethod
    def json():
        return {}


class Client:
    sent = []

    async def request(self, **kwargs):
        Client.sent.append(kwargs)
        return Response()


@pytest.fixture
def broker(monkeypatch, tmp_path):
    def configure(mode="strict"):
        path = tmp_path / "policy.json"
        path.write_text("{}")
        monkeypatch.setenv("JARVISCORE_CONTROL_MODE", mode)
        monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(path))
        monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
        monkeypatch.setattr(policy_module, "_cached", None)
        monkeypatch.setattr(journal_module, "_journal", None)
        client = Client()
        Client.sent = []
        monkeypatch.setattr(proxy_module, "_pooled_client", lambda: client)
        auth = SimpleNamespace(
            _connections={"erp": "conn-erp"}, _strategy_cache={}, nexus_client=None,
            resolve_strategy=AsyncMock(return_value=DynamicStrategy(
                type="api_key", credentials={"api_key": "k"},
                config={"instance_url": "https://erp.example.test", "header_name": "X-Key"})),
        )
        return NexusCallProxy(auth), auth, str(tmp_path / "journal")
    return configure


AUTHORITY = {"workflow_id": "wf", "step_id": "s1", "atom": "erp_pay", "effect": "write",
             "code_origin": "shipped", "action_id": "a1"}


def decisions(root):
    with open(Journal(root).run_path("wf/s1"), encoding="utf-8") as handle:
        return [json.loads(line)["data"] for line in handle if '"policy.decision"' in line]


@pytest.mark.asyncio
async def test_work_for_a_person_does_only_what_they_delegated_and_names_them_on_record(broker):
    proxy, auth, root = broker("strict")

    with act_for("ada@example.com", READ_ONLY_ERP):
        await proxy.call("conn-erp", "GET", "https://erp.example.test/invoices/7",
                         authority={**AUTHORITY, "effect": "read", "atom": "erp_get"})
        with pytest.raises(PolicyDenied, match="did not delegate write") as refused:
            await proxy.call("conn-erp", "POST", "https://erp.example.test/payments", authority=AUTHORITY)

    assert refused.value.decision.rule == "outside-mandate"
    assert [r["method"] for r in Client.sent] == ["GET"]
    assert auth.resolve_strategy.await_count == 1  # the refused call never reached for a credential
    read, pay = decisions(root)
    assert read["acting_for"] == pay["acting_for"] == "ada@example.com"
    assert read["mandate"]["digest"] == pay["mandate"]["digest"]
    assert verify(root).ok


@pytest.mark.asyncio
async def test_no_deployment_rule_widens_a_mandate(broker, tmp_path, monkeypatch):
    proxy, _, _ = broker("strict")
    (tmp_path / "policy.json").write_text(json.dumps({"rules": [
        {"name": "anything", "decision": "allow", "match": {"provider": "erp"}},
    ]}))
    monkeypatch.setattr(policy_module, "_cached", None)

    with act_for("ada@example.com", {"systems": ["gmail"]}):
        with pytest.raises(PolicyDenied, match="did not delegate erp"):
            await proxy.call("conn-erp", "GET", "https://erp.example.test/x", authority={**AUTHORITY, "effect": "read"})


@pytest.mark.asyncio
async def test_without_a_mandate_work_is_as_before(broker):
    proxy, _, root = broker("strict")

    with act_for("ada@example.com"):
        await proxy.call("conn-erp", "GET", "https://erp.example.test/invoices/7",
                         authority={**AUTHORITY, "effect": "read", "atom": "erp_get"})

    assert decisions(root)[0]["outcome"] == "allow" and "mandate" not in decisions(root)[0]


@pytest.mark.asyncio
async def test_a_credential_nexus_refuses_for_this_person_is_not_replaced_by_another(broker):
    proxy, auth, _ = broker("strict")
    refused = httpx.HTTPStatusError(
        "403", request=httpx.Request("GET", "http://gw/v1/token/x"),
        response=httpx.Response(403, json={"error": "subject_mismatch"}),
    )
    auth.resolve_strategy = AsyncMock(side_effect=refused)

    with act_for("bob@example.com"), pytest.raises(PermissionError, match="subject_mismatch"):
        await proxy.call("conn-erp", "GET", "https://erp.example.test/x",
                         authority={**AUTHORITY, "effect": "read", "atom": "erp_get"})
    assert Client.sent == []


# ── What Nexus is told ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nexus_is_told_whom_by_which_agent_and_for_which_operation():
    from jarviscore.auth.principal import operation
    from jarviscore.control.effects import scope

    seen = []
    client = NexusClient("http://gateway.test")
    client.client = httpx.AsyncClient(base_url="http://gateway.test", transport=httpx.MockTransport(
        lambda request: seen.append(request) or httpx.Response(200, json={"strategy": {"type": "oauth2"}, "credentials": {}}),
    ))
    client.default_subject = "jarviscore-agent"
    token = scope.set({"agent": "coder-1"})
    op = operation.set("op-42")
    try:
        with act_for("ada@example.com"):
            await client.get_token("conn-1")
            await client.resolve_active("github", "ada@example.com")
        await client.get_token("conn-2")
    finally:
        scope.reset(token)
        operation.reset(op)

    ada = str(uuid.uuid5(uuid.NAMESPACE_DNS, "ada@example.com"))
    assert [r.headers["X-Nexus-Subject"] for r in seen] == [
        ada, ada, str(uuid.uuid5(uuid.NAMESPACE_DNS, "jarviscore-agent")),
    ]
    assert seen[0].headers["X-Nexus-Agent"] == "coder-1" and seen[0].headers["X-Nexus-Operation"] == "op-42"


@pytest.mark.asyncio
async def test_a_credential_cached_for_one_person_is_never_served_to_another():
    from jarviscore.auth.manager import AuthenticationManager

    manager = AuthenticationManager.__new__(AuthenticationManager)
    manager.user_id = "jarviscore-agent"
    manager.cache_ttl = 300
    manager._strategy_cache = {}
    manager._discovered = {}
    manager.nexus_client = SimpleNamespace(resolve_strategy=AsyncMock(return_value=DynamicStrategy(
        type="oauth2", credentials={"access_token": "t"})))

    with act_for("ada@example.com"):
        await manager.resolve_strategy("conn-1")
        await manager.resolve_strategy("conn-1")
    with act_for("bob@example.com"):
        await manager.resolve_strategy("conn-1")

    assert manager.nexus_client.resolve_strategy.await_count == 2
