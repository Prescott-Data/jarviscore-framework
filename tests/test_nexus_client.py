"""
Tests for NexusClient — Dromos Gateway HTTP client.

Uses unittest.mock to mock httpx.AsyncClient responses.
"""

import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jarviscore.nexus.client import NexusClient
from jarviscore.nexus.models import DynamicStrategy


@pytest.fixture
def client():
    return NexusClient(gateway_url="https://gateway.example.com")


@pytest.fixture
async def cleanup_client(client):
    yield client
    await client.close()


# ── Control Plane ─────────────────────────────────────────────────

class TestNexusClientControlPlane:

    @pytest.mark.asyncio
    async def test_request_connection(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "connection_id": "conn_123",
            "auth_url": "https://provider.com/auth?state=abc",
        }

        client.client.post = AsyncMock(return_value=mock_response)

        conn_id, auth_url = await client.request_connection(
            provider="shopify",
            user_id="user1",
            scopes=["read_products", "write_products"],
        )

        assert conn_id == "conn_123"
        assert "provider.com/auth" in auth_url
        client.client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_connection_status(self, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"status": "ACTIVE"}

        client.client.get = AsyncMock(return_value=mock_response)

        status = await client.check_connection_status("conn_123")
        assert status == "ACTIVE"


# ── Data Plane ────────────────────────────────────────────────────

class TestNexusClientDataPlane:

    @pytest.mark.asyncio
    async def test_get_token(self, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "type": "oauth2",
            "credentials": {"access_token": "tok_abc123"},
            "expires_at": "2030-01-01T00:00:00Z",
        }

        client.client.get = AsyncMock(return_value=mock_response)

        token = await client.get_token("conn_123")
        assert token["credentials"]["access_token"] == "tok_abc123"

    @pytest.mark.asyncio
    async def test_resolve_strategy(self, client):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "type": "oauth2",
            "credentials": {"access_token": "tok_xyz"},
            "expires_at": "2030-12-31T00:00:00Z",
        }

        client.client.get = AsyncMock(return_value=mock_response)

        strategy = await client.resolve_strategy("conn_123")
        assert isinstance(strategy, DynamicStrategy)
        assert strategy.type == "oauth2"
        assert strategy.credentials["access_token"] == "tok_xyz"
        assert not strategy.is_expired()


# ── Strategy Application ──────────────────────────────────────────

class TestStrategyApplication:

    def test_apply_oauth2_strategy(self):
        strategy = DynamicStrategy(
            type="oauth2",
            credentials={"access_token": "bearer_token_123"},
        )
        result = NexusClient.apply_strategy_to_request(
            strategy, "GET", "https://api.example.com/data"
        )
        assert result["headers"]["Authorization"] == "Bearer bearer_token_123"
        assert result["method"] == "GET"
        assert result["url"] == "https://api.example.com/data"

    def test_apply_api_key_strategy(self):
        strategy = DynamicStrategy(
            type="api_key",
            credentials={"api_key": "key_abc"},
        )
        result = NexusClient.apply_strategy_to_request(
            strategy, "POST", "https://api.example.com/data"
        )
        assert result["headers"]["X-Api-Key"] == "key_abc"

    def test_apply_basic_auth_strategy(self):
        strategy = DynamicStrategy(
            type="basic_auth",
            credentials={"username": "user", "password": "pass"},
        )
        result = NexusClient.apply_strategy_to_request(
            strategy, "GET", "https://api.example.com/data"
        )
        expected = base64.b64encode(b"user:pass").decode()
        assert result["headers"]["Authorization"] == f"Basic {expected}"

    def test_preserves_existing_headers(self):
        strategy = DynamicStrategy(
            type="api_key",
            credentials={"api_key": "k"},
        )
        result = NexusClient.apply_strategy_to_request(
            strategy, "GET", "https://x.com",
            headers={"Content-Type": "application/json"},
        )
        assert result["headers"]["Content-Type"] == "application/json"
        assert result["headers"]["X-Api-Key"] == "k"

    def test_passes_extra_kwargs(self):
        strategy = DynamicStrategy(type="api_key", credentials={"api_key": "k"})
        result = NexusClient.apply_strategy_to_request(
            strategy, "POST", "https://x.com",
            json={"data": 1},
        )
        assert result["json"] == {"data": 1}


# ── Close ─────────────────────────────────────────────────────────

class TestNexusClientClose:

    @pytest.mark.asyncio
    async def test_close(self, client):
        client.client.aclose = AsyncMock()
        await client.close()
        client.client.aclose.assert_called_once()
