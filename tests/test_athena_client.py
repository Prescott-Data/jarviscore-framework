from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jarviscore.memory.athena_client import AthenaClient
from jarviscore.memory import get_athena_client


def _response(payload):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


@pytest.mark.asyncio
async def test_get_context_preserves_athena_v015_response_fields():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response(
        {
            "stmEvents": [{"role": "user", "content": "recent"}],
            "relevantPages": [{"id": "chain-1", "summary": "prior decision"}],
            "segments": [{"id": "segment-1", "content": "evidence"}],
            "userPersona": {"userId": "owner"},
            "ltpm": {"status": "ready"},
        }
    )
    client._client = http

    context = await client.get_context("session-1", limit=7)

    http.get.assert_awaited_once_with(
        "/api/v1/sessions/session-1/context", params={"limit": 7}
    )
    assert context == {
        "stm_events": [{"role": "user", "content": "recent"}],
        "mtm_chains": [{"id": "chain-1", "summary": "prior decision"}],
        "segments": [{"id": "segment-1", "content": "evidence"}],
        "user_persona": {"userId": "owner"},
        "ltpm": {"status": "ready"},
        "heat_score": 0.0,
    }


@pytest.mark.asyncio
async def test_get_context_retains_legacy_aliases():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response(
        {
            "events": [{"content": "legacy event"}],
            "chains": [{"summary": "legacy chain"}],
            "heatScore": 0.4,
        }
    )
    client._client = http

    context = await client.get_context("session-1")

    assert context["stm_events"] == [{"content": "legacy event"}]
    assert context["mtm_chains"] == [{"summary": "legacy chain"}]
    assert context["heat_score"] == 0.4


@pytest.mark.asyncio
async def test_get_context_failure_returns_complete_empty_shape():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.side_effect = RuntimeError("offline")
    client._client = http

    context = await client.get_context("session-1")

    assert context == {
        "stm_events": [],
        "mtm_chains": [],
        "segments": [],
        "user_persona": None,
        "ltpm": None,
        "heat_score": 0.0,
    }


@pytest.mark.asyncio
async def test_get_context_sends_query_and_segment_options():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response({})
    client._client = http

    await client.get_context(
        "session-1", limit=8, query="prior decisions", include_segments=True
    )

    http.get.assert_awaited_once_with(
        "/api/v1/sessions/session-1/context",
        params={
            "limit": 8,
            "query": "prior decisions",
            "includeSegments": True,
        },
    )


@pytest.mark.asyncio
async def test_store_event_with_id_serializes_payload_and_timestamp():
    client = AthenaClient("http://athena.test", tenant_id="tenant-1")
    http = AsyncMock()
    http.post.return_value = _response(
        {"success": True, "eventId": "68b5f26cc7e80f7a577792a1"}
    )
    client._client = http

    event_id = await client.store_event_with_id(
        "session-1",
        "agent",
        "observation",
        "structured result",
        {"workflow_id": "wf-1"},
        timestamp=datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc),
        payload=b'{"result": 42}',
        mime_type="application/json",
    )

    assert event_id == "68b5f26cc7e80f7a577792a1"
    request = http.post.await_args.kwargs["json"]
    assert request["timestamp"] == "2026-09-01T12:30:00Z"
    assert request["payload"] == "eyJyZXN1bHQiOiA0Mn0="
    assert request["mime_type"] == "application/json"
    assert request["metadata"] == {
        "tenant_id": "tenant-1",
        "origin_service": "jarviscore",
        "workflow_id": "wf-1",
    }


@pytest.mark.asyncio
async def test_store_event_keeps_boolean_compatibility():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.post.return_value = _response({"success": True, "eventId": "event-1"})
    client._client = http

    assert await client.store_event(
        "session-1", "agent", "observation", "result"
    ) is True


@pytest.mark.asyncio
async def test_store_event_requires_mime_type_for_payload():
    client = AthenaClient("http://athena.test")
    with pytest.raises(ValueError, match="mime_type"):
        await client.store_event(
            "session-1", "agent", "observation", "result", payload=b"data"
        )


@pytest.mark.asyncio
async def test_search_memory_sends_metadata_filter():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.post.return_value = _response({"results": [{"sourceId": "chain-1"}]})
    client._client = http

    results = await client.search_memory(
        "session-1",
        "gold decisions",
        limit=3,
        similarity_threshold=0.8,
        metadata_filter={"origin_service": "billy"},
    )

    assert results == [{"sourceId": "chain-1"}]
    assert http.post.await_args.kwargs["json"]["filter"] == {
        "origin_service": "billy"
    }


@pytest.mark.asyncio
async def test_session_interaction_and_analysis_methods():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.side_effect = [
        _response({"session": {"sessionId": "session-1"}}),
        _response({"topics": [{"topic": "markets"}]}),
        _response({"segments": [{"id": "segment-1"}]}),
    ]
    http.post.side_effect = [
        _response({"success": True}),
        _response({"success": True}),
    ]
    http.delete.return_value = _response({"success": True})
    client._client = http

    assert await client.get_session("session-1") == {"sessionId": "session-1"}
    assert await client.store_interaction(
        "session-1", "question", "answer", {"channel": "telegram"}
    ) is True
    assert await client.analyze_topics("session-1") == [{"topic": "markets"}]
    assert await client.get_segments("session-1", limit=4) == [{"id": "segment-1"}]
    assert await client.trigger_graph_analytics() is True
    assert await client.delete_session("session-1") is True
    assert http.get.await_args_list[-1].kwargs["params"] == {"limit": 4}


@pytest.mark.asyncio
async def test_heat_metrics_unwraps_canonical_response():
    client = AthenaClient("http://athena.test")
    http = AsyncMock()
    http.get.return_value = _response(
        {"heatMetrics": {"overallHeat": 0.7, "totalInteractions": 12}}
    )
    client._client = http

    metrics = await client.get_heat_metrics("session-1")

    assert metrics == {"overallHeat": 0.7, "totalInteractions": 12}


def test_from_env_loads_auth_tenant_and_timeout(monkeypatch):
    monkeypatch.setenv("ATHENA_URL", "https://athena.example")
    monkeypatch.setenv("ATHENA_TENANT_ID", "tenant-1")
    monkeypatch.setenv("ATHENA_HTTP_TIMEOUT", "4.5")
    monkeypatch.setenv("ATHENA_API_KEY", "api-secret")
    monkeypatch.setenv("ATHENA_JWT_TOKEN", "jwt-secret")

    client = AthenaClient.from_env()

    assert client is not None
    assert client._tenant_id == "tenant-1"
    assert client._timeout == 4.5
    assert client._api_key == "api-secret"
    assert client._jwt_token == "jwt-secret"


@pytest.mark.asyncio
async def test_http_recreates_only_a_boolean_closed_client():
    client = AthenaClient("http://athena.test", api_key="api-secret")
    closed = MagicMock()
    closed.is_closed = True
    client._client = closed
    replacement = MagicMock()

    with patch("httpx.AsyncClient", return_value=replacement) as constructor:
        assert await client._http() is replacement

    assert constructor.call_args.kwargs["headers"]["X-API-Key"] == "api-secret"


def test_public_factory_uses_environment_auth_fallback(monkeypatch):
    monkeypatch.setenv("ATHENA_API_KEY", "api-secret")
    monkeypatch.setenv("ATHENA_JWT_TOKEN", "jwt-secret")
    settings = SimpleNamespace(
        athena_url="https://athena.example",
        athena_tenant_id="tenant-1",
        athena_http_timeout=3.0,
        athena_api_key=None,
        athena_jwt_token=None,
    )

    client = get_athena_client(settings)

    assert client is not None
    assert client._api_key == "api-secret"
    assert client._jwt_token == "jwt-secret"