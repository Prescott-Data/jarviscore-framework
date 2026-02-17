"""
Tests for AuthenticationManager — Dual-mode auth resolution.

Tests dev mode (env vars), production mode (mocked NexusClient),
strategy caching, resolve_auth_context, OAuth flow handlers, and cleanup.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jarviscore.auth.manager import AuthenticationManager
from jarviscore.auth.oauth_flow import (
    CLIFlowHandler,
    LocalCallbackServer,
    _CallbackHandler,
)
from jarviscore.nexus.models import DynamicStrategy


# ── Development Mode ──────────────────────────────────────────────

class TestDevMode:

    @pytest.mark.asyncio
    async def test_dev_mode_returns_connection_id(self):
        manager = AuthenticationManager({"auth_mode": "development"})
        conn_id = await manager.authenticate("shopify", user_id="u1")
        assert conn_id == "dev_shopify_u1"

    @pytest.mark.asyncio
    async def test_dev_mode_reads_env_token(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_TOKEN", "shpat_test123")
        manager = AuthenticationManager({"auth_mode": "development"})

        conn_id = await manager.authenticate("shopify")
        strategy = await manager.resolve_strategy(conn_id)

        assert strategy.type == "api_key"
        assert strategy.credentials["api_key"] == "shpat_test123"

    @pytest.mark.asyncio
    async def test_dev_mode_empty_token_when_not_set(self):
        manager = AuthenticationManager({"auth_mode": "development"})
        conn_id = await manager.authenticate("unknown_provider")
        strategy = await manager.resolve_strategy(conn_id)
        assert strategy.credentials["api_key"] == ""

    @pytest.mark.asyncio
    async def test_dev_mode_caches_connection(self):
        manager = AuthenticationManager({"auth_mode": "development"})
        conn1 = await manager.authenticate("github")
        conn2 = await manager.authenticate("github")
        assert conn1 == conn2  # Same connection returned

    @pytest.mark.asyncio
    async def test_dev_mode_default_user_id(self):
        manager = AuthenticationManager({
            "auth_mode": "development",
            "nexus_default_user_id": "custom-agent",
        })
        conn_id = await manager.authenticate("slack")
        assert "custom-agent" in conn_id


# ── Production Mode ───────────────────────────────────────────────

class TestProdMode:

    def test_prod_mode_requires_gateway_url(self):
        with pytest.raises(ValueError, match="nexus_gateway_url is required"):
            AuthenticationManager({"auth_mode": "production"})

    @pytest.mark.asyncio
    async def test_prod_mode_calls_nexus(self):
        manager = AuthenticationManager({
            "auth_mode": "production",
            "nexus_gateway_url": "https://gateway.test.com",
        })

        # Mock the nexus client
        manager.nexus_client.request_connection = AsyncMock(
            return_value=("conn_prod_1", "https://auth.test.com/oauth")
        )
        manager.lifecycle_monitor.monitor_connection = AsyncMock()

        # Mock the flow handler so it doesn't open a browser or poll
        manager.flow_handler.present_auth_url = AsyncMock()
        manager.flow_handler.wait_for_completion = AsyncMock(return_value="ACTIVE")

        conn_id = await manager.authenticate("shopify", scopes=["read_products"])
        assert conn_id == "conn_prod_1"
        manager.nexus_client.request_connection.assert_called_once()
        manager.lifecycle_monitor.monitor_connection.assert_called_once_with("conn_prod_1")

        # Verify flow handler was invoked
        manager.flow_handler.present_auth_url.assert_called_once_with(
            "https://auth.test.com/oauth", "shopify"
        )
        manager.flow_handler.wait_for_completion.assert_called_once()

        await manager.close()

    @pytest.mark.asyncio
    async def test_prod_mode_raises_on_failed_oauth(self):
        manager = AuthenticationManager({
            "auth_mode": "production",
            "nexus_gateway_url": "https://gateway.test.com",
        })

        manager.nexus_client.request_connection = AsyncMock(
            return_value=("conn_fail_1", "https://auth.test.com/oauth")
        )
        manager.flow_handler.present_auth_url = AsyncMock()
        manager.flow_handler.wait_for_completion = AsyncMock(return_value="FAILED")

        with pytest.raises(RuntimeError, match="OAuth flow for shopify did not complete"):
            await manager.authenticate("shopify")

        await manager.close()

    @pytest.mark.asyncio
    async def test_prod_mode_resolve_strategy(self):
        manager = AuthenticationManager({
            "auth_mode": "production",
            "nexus_gateway_url": "https://gateway.test.com",
        })

        mock_strategy = DynamicStrategy(
            type="oauth2",
            credentials={"access_token": "prod_token_xyz"},
            expires_at="2030-01-01T00:00:00Z",
        )
        manager.nexus_client.resolve_strategy = AsyncMock(return_value=mock_strategy)

        strategy = await manager.resolve_strategy("conn_prod_1")
        assert strategy.type == "oauth2"
        assert strategy.credentials["access_token"] == "prod_token_xyz"

        await manager.close()


# ── Strategy Caching ──────────────────────────────────────────────

class TestStrategyCaching:

    @pytest.mark.asyncio
    async def test_cache_hit(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        manager = AuthenticationManager({
            "auth_mode": "development",
            "auth_strategy_cache_ttl": 300,
        })

        conn_id = await manager.authenticate("github")
        s1 = await manager.resolve_strategy(conn_id)
        s2 = await manager.resolve_strategy(conn_id)

        # Both should return same strategy (from cache)
        assert s1.credentials == s2.credentials

    @pytest.mark.asyncio
    async def test_cache_miss_on_ttl_expiry(self):
        manager = AuthenticationManager({
            "auth_mode": "development",
            "auth_strategy_cache_ttl": 0,  # Immediate expiry
        })

        conn_id = await manager.authenticate("test_provider")

        # First call populates cache
        s1 = await manager.resolve_strategy(conn_id)

        # TTL=0 means next call should re-fetch
        s2 = await manager.resolve_strategy(conn_id)

        # Both should still work (dev mode recreates from env)
        assert s1.type == s2.type


# ── resolve_auth_context ──────────────────────────────────────────

class TestResolveAuthContext:

    @pytest.mark.asyncio
    async def test_returns_none_without_registry(self):
        manager = AuthenticationManager({"auth_mode": "development"})
        result = await manager.resolve_auth_context("shopify", registry=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_no_auth_system(self):
        manager = AuthenticationManager({"auth_mode": "development"})

        mock_registry = MagicMock()
        mock_registry.get_system_auth_requirements.return_value = {}

        result = await manager.resolve_auth_context("utils", registry=mock_registry)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolves_auth_context_for_system(self, monkeypatch):
        monkeypatch.setenv("SHOPIFY_TOKEN", "shpat_live_abc")
        manager = AuthenticationManager({"auth_mode": "development"})

        mock_registry = MagicMock()
        mock_registry.get_system_auth_requirements.return_value = {
            "provider": "shopify",
            "scopes": ["read_products"],
            "auth_type": "oauth2",
        }

        result = await manager.resolve_auth_context("shopify", registry=mock_registry)
        assert result is not None
        assert result["provider"] == "shopify"
        assert result["strategy_type"] == "api_key"  # dev mode uses api_key
        assert result["access_token"] == "shpat_live_abc"


# ── CLIFlowHandler ───────────────────────────────────────────────

class TestCLIFlowHandler:

    @pytest.mark.asyncio
    async def test_present_auth_url_opens_browser(self, capsys):
        handler = CLIFlowHandler(open_browser=False)
        await handler.present_auth_url("https://auth.example.com/oauth", "github")

        captured = capsys.readouterr()
        assert "Authorization required for: github" in captured.out
        assert "https://auth.example.com/oauth" in captured.out

    @pytest.mark.asyncio
    async def test_wait_for_completion_active(self):
        handler = CLIFlowHandler()
        check_fn = AsyncMock(return_value="ACTIVE")

        status = await handler.wait_for_completion(
            connection_id="conn_1",
            check_status_fn=check_fn,
            timeout=5,
            poll_interval=0.01,
        )
        assert status == "ACTIVE"
        check_fn.assert_called_with("conn_1")

    @pytest.mark.asyncio
    async def test_wait_for_completion_failed(self):
        handler = CLIFlowHandler()
        check_fn = AsyncMock(return_value="FAILED")

        status = await handler.wait_for_completion(
            connection_id="conn_1",
            check_status_fn=check_fn,
            timeout=5,
            poll_interval=0.01,
        )
        assert status == "FAILED"

    @pytest.mark.asyncio
    async def test_wait_for_completion_timeout(self):
        handler = CLIFlowHandler()
        check_fn = AsyncMock(return_value="PENDING")

        status = await handler.wait_for_completion(
            connection_id="conn_1",
            check_status_fn=check_fn,
            timeout=0.05,
            poll_interval=0.01,
        )
        assert status == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_wait_handles_status_check_error(self):
        handler = CLIFlowHandler()
        # First call raises, second returns ACTIVE
        check_fn = AsyncMock(side_effect=[Exception("network error"), "ACTIVE"])

        status = await handler.wait_for_completion(
            connection_id="conn_1",
            check_status_fn=check_fn,
            timeout=5,
            poll_interval=0.01,
        )
        assert status == "ACTIVE"

    @pytest.mark.asyncio
    async def test_pluggable_flow_handler(self):
        """AuthenticationManager accepts a custom flow handler."""
        manager = AuthenticationManager({
            "auth_mode": "production",
            "nexus_gateway_url": "https://gateway.test.com",
        })

        custom_handler = MagicMock()
        custom_handler.present_auth_url = AsyncMock()
        custom_handler.wait_for_completion = AsyncMock(return_value="ACTIVE")

        manager.flow_handler = custom_handler

        manager.nexus_client.request_connection = AsyncMock(
            return_value=("conn_custom", "https://auth.test.com/custom")
        )
        manager.lifecycle_monitor.monitor_connection = AsyncMock()

        conn_id = await manager.authenticate("slack")
        assert conn_id == "conn_custom"
        custom_handler.present_auth_url.assert_called_once()
        custom_handler.wait_for_completion.assert_called_once()

        await manager.close()


# ── LocalCallbackServer ──────────────────────────────────────────

class TestLocalCallbackServer:

    def test_callback_url(self):
        server = LocalCallbackServer(port=9999)
        assert server.callback_url == "http://localhost:9999/callback"

    @pytest.mark.asyncio
    async def test_wait_for_code_returns_on_auth_code(self):
        server = LocalCallbackServer(port=9998)
        # Simulate auth code being set directly
        _CallbackHandler.auth_code = "test_code_abc"
        _CallbackHandler.error = None

        code = await server.wait_for_code(timeout=1)
        assert code == "test_code_abc"

        # Reset class state
        _CallbackHandler.auth_code = None

    @pytest.mark.asyncio
    async def test_wait_for_code_returns_none_on_error(self):
        server = LocalCallbackServer(port=9997)
        _CallbackHandler.auth_code = None
        _CallbackHandler.error = "access_denied"

        code = await server.wait_for_code(timeout=1)
        assert code is None

        # Reset class state
        _CallbackHandler.error = None

    @pytest.mark.asyncio
    async def test_wait_for_code_timeout(self):
        server = LocalCallbackServer(port=9996)
        _CallbackHandler.auth_code = None
        _CallbackHandler.error = None

        code = await server.wait_for_code(timeout=0.1)
        assert code is None


# ── Close / Cleanup ──────────────────────────────────────────────

class TestCleanup:

    @pytest.mark.asyncio
    async def test_close_dev_mode(self):
        """Close in dev mode is a no-op (no external clients)."""
        manager = AuthenticationManager({"auth_mode": "development"})
        await manager.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_close_prod_mode(self):
        manager = AuthenticationManager({
            "auth_mode": "production",
            "nexus_gateway_url": "https://gateway.test.com",
        })
        manager.lifecycle_monitor.stop_all = AsyncMock()
        manager.nexus_client.close = AsyncMock()

        await manager.close()

        manager.lifecycle_monitor.stop_all.assert_called_once()
        manager.nexus_client.close.assert_called_once()
