import httpx
import pytest

from jarviscore.auth.manager import AuthenticationManager
from jarviscore.nexus.client import NexusClient


@pytest.mark.asyncio
async def test_missing_provider_is_seeded_before_connection_request():
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"oauth2": {}})
        return httpx.Response(201, json={"created": True})

    client = NexusClient("https://gateway.test")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://gateway.test", transport=httpx.MockTransport(handler)
    )
    try:
        await client.ensure_provider({"name": "slack", "auth_type": "oauth2"})
    finally:
        await client.close()

    assert calls == [("GET", "/v1/providers"), ("POST", "/v1/providers")]


@pytest.mark.asyncio
async def test_existing_provider_is_not_rewritten():
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"oauth2": {"slack": {"name": "slack"}}})

    client = NexusClient("https://gateway.test")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://gateway.test", transport=httpx.MockTransport(handler)
    )
    try:
        await client.ensure_provider({"name": "slack", "auth_type": "oauth2"})
    finally:
        await client.close()

    assert calls == [("GET", "/v1/providers")]


@pytest.mark.asyncio
async def test_begin_authentication_seeds_before_request(monkeypatch):
    manager = AuthenticationManager({"nexus_gateway_url": "https://gateway.test"})
    order = []

    async def ensure(profile):
        order.append(("seed", profile["name"]))

    async def request_connection(**kwargs):
        order.append(("connect", kwargs["provider"]))
        return "conn-1", "https://slack.com/oauth"

    manager.nexus_client.ensure_provider = ensure
    manager.nexus_client.request_connection = request_connection
    try:
        assert await manager.begin_authentication("slack") == (
            "conn-1", "https://slack.com/oauth"
        )
    finally:
        await manager.close()

    assert order == [("seed", "slack"), ("connect", "slack")]


@pytest.mark.asyncio
async def test_non_oauth_capture_schema_is_resolved_from_signed_state():
    requested = []
    schema = {
        "schema": {
            "type": "object",
            "properties": {"api_key": {"type": "string", "format": "password"}},
            "required": ["api_key"],
        }
    }

    async def handler(request):
        requested.append(dict(request.url.params))
        return httpx.Response(200, json=schema)

    client = NexusClient("https://gateway.test")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url="https://gateway.test", transport=httpx.MockTransport(handler)
    )
    try:
        assert await client.capture_schema("signed-state") == schema
    finally:
        await client.close()

    assert requested == [{"state": "signed-state"}]
    assert "credentials" not in str(schema)
