from unittest.mock import AsyncMock, MagicMock

import pytest

from jarviscore.memory.athena_client import AthenaClient


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