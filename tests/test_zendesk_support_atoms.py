from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarviscore.auth.manager import AuthenticationManager
from jarviscore.execution.atom_contract import read_contract
from jarviscore.integrations.seed_registry import PROVIDER_META, seed_registry
from jarviscore.kernel.defaults.coder import CoderSubAgent
from jarviscore.nexus._data import provider_urls_for
from jarviscore.nexus.providers import get_scopes
from jarviscore.nexus.store import NexusLocalStore

ATOM_DIR = Path(__file__).resolve().parents[1] / "jarviscore/integrations/atoms/zendesk_support"
EXPECTED_EFFECTS = {
    "zendesk_support_create_ticket": "write",
    "zendesk_support_route_ticket": "write",
    "zendesk_support_get_ticket": "read",
    "zendesk_support_get_ticket_comments": "read",
    "zendesk_support_get_requester": "read",
    "zendesk_support_get_organization": "read",
    "zendesk_support_search_tickets": "read",
    "zendesk_support_post_public_reply": "notify",
    "zendesk_support_post_internal_note": "write",
}


class MemoryRegistry:
    def __init__(self):
        self.functions = {}

    def has_function(self, name):
        return name in self.functions

    def get_function_metadata(self, name):
        return self.functions[name]["metadata"]

    def get_function_code(self, name):
        return self.functions[name]["source"]

    def register_function(self, function_name, function, metadata):
        self.functions[function_name] = {"source": function, "metadata": metadata}
        return True

    def update_function_metadata(self, function_name, metadata):
        self.functions[function_name]["metadata"].update(metadata)


@pytest.mark.asyncio
async def test_chat_ticket_preserves_full_transcript_and_routes_privately():
    call = AsyncMock(return_value={"status_code": 201, "json": {"ticket": {"id": 42}}})
    _, create = load_atom("zendesk_support_create_ticket", call)
    body = "conversation evidence " * 20000 + "tail: customer requested specialist"
    result = await create("Shipping", body, "Customer", "customer@example.com", "session-1", 123)
    assert result["ok"]
    payload = call.await_args.kwargs["json"]["ticket"]
    assert payload["comment"] == {"body": body, "public": False}
    assert payload["external_id"] == "session-1"
    assert payload["group_id"] == 123
    assert payload["requester"]["email"] == "customer@example.com"


@pytest.mark.asyncio
async def test_routing_does_not_post_a_customer_comment():
    call = AsyncMock(return_value={"status_code": 200, "json": {"ticket": {"id": 42}}})
    _, route = load_atom("zendesk_support_route_ticket", call)
    assert (await route(42, 123, "high"))["ok"]
    assert call.await_args.kwargs["json"] == {"ticket": {"group_id": 123, "priority": "high"}}
    assert not (await route(42, True))["ok"]
    assert call.await_count == 1


class ExecutionStore:
    def __init__(self):
        self.results = {}

    def get_atom_execution(self, action_id):
        return self.results.get(action_id)

    def save_atom_execution(self, action_id, result):
        self.results[action_id] = result


def load_atom(name, nexus_call):
    source_path = ATOM_DIR / f"{name}.py"
    source = source_path.read_text(encoding="utf-8")
    namespace = {"nexus_call": nexus_call}
    exec(compile(source, str(source_path), "exec"), namespace)
    return source, namespace[name]


def test_zendesk_support_bundle_is_seeded_for_runtime_discovery():
    registry = MemoryRegistry()
    report = seed_registry(registry, systems=["zendesk_support"])

    assert report["failed"] == []
    assert report["total_atoms"] == len(EXPECTED_EFFECTS)
    assert {item["function"] for item in report["registered"]} == set(EXPECTED_EFFECTS)
    assert PROVIDER_META["zendesk_support"]["status"] == "candidate"
    assert all(
        registry.functions[name]["metadata"]["system"] == "zendesk_support"
        for name in EXPECTED_EFFECTS
    )


def test_every_zendesk_support_atom_has_a_valid_effect_contract():
    for name, effect in EXPECTED_EFFECTS.items():
        source = (ATOM_DIR / f"{name}.py").read_text(encoding="utf-8")
        contract = read_contract(source, system="zendesk_support", expected_name=name)
        assert contract.ok, f"{name}: {contract.report()}"
        assert contract.atom is not None
        assert contract.atom.policy.effect == effect
        if effect in {"write", "notify"}:
            assert contract.atom.policy.requires_approval
            assert contract.atom.policy.consequence


def test_zendesk_support_oauth_profile_is_tenant_specific_and_scoped():
    assert provider_urls_for("zendesk_support", "Acme") == {
        "auth_url": "https://acme.zendesk.com/oauth/authorizations/new",
        "token_url": "https://acme.zendesk.com/oauth/tokens",
        "api_base_url": "https://acme.zendesk.com/api/v2",
    }
    assert get_scopes("zendesk_support") == [
        "tickets:read",
        "tickets:write",
        "users:read",
        "organizations:read",
    ]


@pytest.mark.parametrize(
    "subdomain",
    [None, "acme.zendesk.com", "acme.evil", "https://acme", "-acme", "acme-"],
)
def test_zendesk_support_oauth_profile_rejects_invalid_tenant_labels(subdomain):
    with pytest.raises(ValueError, match="one DNS label"):
        provider_urls_for("zendesk_support", subdomain)


@pytest.mark.asyncio
async def test_existing_gateway_provider_profile_needs_no_local_subdomain(monkeypatch):
    manager = AuthenticationManager({"nexus_gateway_url": "https://gateway.test"})
    exists = AsyncMock(return_value=True)
    ensure = AsyncMock()
    manager.nexus_client.provider_exists = exists
    manager.nexus_client.ensure_provider = ensure
    monkeypatch.setattr(
        "jarviscore.nexus.store.get_store",
        lambda: SimpleNamespace(
            get=lambda provider: None,
            get_provider_metadata=lambda provider: {},
        ),
    )
    try:
        await manager._ensure_provider("zendesk_support")
    finally:
        await manager.close()

    exists.assert_awaited_once_with("zendesk-support")
    ensure.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_provider_profile_uses_saved_tenant_metadata(monkeypatch):
    manager = AuthenticationManager({"nexus_gateway_url": "https://gateway.test"})
    ensure = AsyncMock()
    manager.nexus_client.ensure_provider = ensure
    monkeypatch.setattr(
        "jarviscore.nexus.store.get_store",
        lambda: SimpleNamespace(
            get=lambda provider: {
                "auth_type": "oauth2",
                "client_id": "client-id",
                "client_secret": "client-secret",
            },
            get_provider_metadata=lambda provider: {
                "subdomain": "acme",
                "api_base_url": "https://acme.zendesk.com/api/v2",
            },
        ),
    )
    try:
        await manager._ensure_provider("zendesk_support")
    finally:
        await manager.close()

    profile = ensure.await_args.args[0]
    assert profile["name"] == "zendesk-support"
    assert profile["auth_url"] == "https://acme.zendesk.com/oauth/authorizations/new"
    assert profile["token_url"] == "https://acme.zendesk.com/oauth/tokens"
    assert profile["api_base_url"] == "https://acme.zendesk.com/api/v2"
    assert profile["client_secret"] == "client-secret"


def test_zendesk_provider_metadata_is_non_secret_and_separate_from_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVISCORE_MASTER_KEY", "test-key-for-zendesk-metadata")
    monkeypatch.setattr("jarviscore.nexus.store._SALT_FILE", tmp_path / ".salt")
    store = NexusLocalStore(path=tmp_path / "nexus.enc")
    store.set_provider_metadata(
        "zendesk_support",
        {
            "subdomain": "acme",
            "api_base_url": "https://acme.zendesk.com/api/v2",
        },
    )

    assert store.get_provider_metadata("zendesk_support") == {
        "subdomain": "acme",
        "api_base_url": "https://acme.zendesk.com/api/v2",
    }
    assert store.list() == []
    assert store.get("zendesk_support") is None
    with pytest.raises(ValueError, match="non-empty Zendesk tenant fields"):
        store.set_provider_metadata(
            "zendesk_support", {"client_secret": "must-never-be-copied-to-local-store"}
        )


@pytest.mark.asyncio
async def test_ticket_comments_preserve_every_cursor_page():
    first_page = [{"id": item_id} for item_id in range(1, 101)]
    second_page = [{"id": item_id} for item_id in range(101, 201)]
    third_page = [{"id": item_id} for item_id in range(201, 206)]
    responses = [
        {
            "status_code": 200,
            "json": {
                "comments": first_page,
                "meta": {"has_more": True, "after_cursor": "cursor-1"},
            },
        },
        {
            "status_code": 200,
            "json": {
                "comments": second_page,
                "meta": {"has_more": True, "after_cursor": "cursor-2"},
            },
        },
        {"status_code": 200, "json": {"comments": third_page, "meta": {"has_more": False}}},
    ]
    calls = []

    async def nexus_call(method, url, **kwargs):
        calls.append(
            {
                "method": method,
                "url": url,
                **kwargs,
                "params": dict(kwargs.get("params", {})),
            }
        )
        return responses.pop(0)

    _, atom = load_atom("zendesk_support_get_ticket_comments", nexus_call)
    result = await atom(ticket_id=27)

    expected_comments = first_page + second_page + third_page
    assert result["data"]["comments"] == expected_comments
    assert result["data"]["count"] == 205
    assert result["data"]["complete"] is True
    assert calls[0]["params"] == {"page[size]": 100}
    assert calls[1]["params"] == {"page[size]": 100, "page[after]": "cursor-1"}
    assert calls[2]["params"] == {"page[size]": 100, "page[after]": "cursor-2"}
    assert calls[2]["url"] == "/api/v2/tickets/27/comments.json"


@pytest.mark.asyncio
async def test_search_surfaces_api_cap_and_preserves_the_last_returned_ticket():
    expected_records = []
    calls = []

    async def nexus_call(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        page = kwargs["params"]["page"]
        records = [{"id": (page - 1) * 100 + offset} for offset in range(1, 101)]
        expected_records.extend(records)
        return {
            "status_code": 200,
            "json": {"results": records, "count": 1001, "next_page": f"page-{page + 1}"},
        }

    _, atom = load_atom("zendesk_support_search_tickets", nexus_call)
    result = await atom(query="subject:shipping")

    assert result["data"]["results"] == expected_records
    assert result["data"]["results"][-1] == {"id": 1000}
    assert result["data"]["count"] == 1001
    assert result["data"]["complete"] is False
    assert "caps queries at 1000 results" in result["message"]
    assert len(calls) == 10
    assert calls[0]["params"]["query"] == "type:ticket subject:shipping"
    assert calls[0]["params"]["page"] == 1
    assert calls[-1]["params"]["page"] == 10


@pytest.mark.asyncio
async def test_public_reply_and_internal_note_use_distinct_visibility_values():
    calls = []

    async def nexus_call(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return {"status_code": 200, "json": {"ticket": {"id": 27}}}

    _, public_reply = load_atom("zendesk_support_post_public_reply", nexus_call)
    _, internal_note = load_atom("zendesk_support_post_internal_note", nexus_call)
    public_result = await public_reply(ticket_id=27, body="Reply text")
    note_result = await internal_note(ticket_id=27, body="Reviewer note")

    assert public_result["ok"] is True
    assert note_result["ok"] is True
    assert calls[0]["method"] == "PUT"
    assert calls[0]["url"] == "/api/v2/tickets/27.json"
    assert calls[0]["json"] == {"ticket": {"comment": {"body": "Reply text", "public": True}}}
    assert calls[1]["json"] == {"ticket": {"comment": {"body": "Reviewer note", "public": False}}}
    assert all(call["provider"] == "zendesk_support" for call in calls)


@pytest.mark.asyncio
async def test_public_reply_waits_for_human_approval_before_execution():
    source, _ = load_atom("zendesk_support_post_public_reply", nexus_call=AsyncMock())
    contract = read_contract(
        source,
        system="zendesk_support",
        expected_name="zendesk_support_post_public_reply",
    )
    assert contract.ok
    atom = contract.atom
    assert atom is not None

    class Registry:
        def get_function_code(self, name):
            return source

        def update_execution_stats(self, *args, **kwargs):
            pass

    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "support", "step_id": "public-reply"}
    agent.code_registry = Registry()
    agent.redis_store = ExecutionStore()
    agent._tool_execute_code = AsyncMock(
        return_value={"status": "success", "data": {"ticket": {"id": 27}}}
    )
    call = agent._atom_tool(atom.name)

    waiting = await call(ticket_id=27, body="Your replacement is on the way.")
    assert waiting["typed_outcome"] == "WAITING_FOR_APPROVAL"
    assert waiting["consequence"] == "Sends a public reply to the Zendesk ticket requester."
    agent._tool_execute_code.assert_not_awaited()

    agent._run_context["_approved_actions"] = [waiting["action_id"]]
    approved = await call(ticket_id=27, body="Your replacement is on the way.")
    assert approved["status"] == "success"
    agent._tool_execute_code.assert_awaited_once()
