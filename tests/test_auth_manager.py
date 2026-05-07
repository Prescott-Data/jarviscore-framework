"""
Tests for AuthenticationManager — Nexus-gated credential manager.

Tests authenticate (mocked NexusClient), strategy caching,
OAuth flow handlers, and cleanup.
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


def _make_manager_with_mock_nexus(**extra_config):
    """Create an AuthenticationManager with a mocked NexusClient."""
    manager = AuthenticationManager({
        "nexus_gateway_url": "https://gateway.test.com",
        **extra_config,
    })
    manager.nexus_client.request_connection = AsyncMock(
        return_value=("conn_abc", "https://provider.com/auth")
    )
    manager.nexus_client.check_connection_status = AsyncMock(return_value="ACTIVE")
    manager.lifecycle_monitor.monitor_connection = AsyncMock()
    manager.flow_handler.present_auth_url = AsyncMock()
    manager.flow_handler.wait_for_completion = AsyncMock(return_value="ACTIVE")
    return manager


# ── Authentication (no Nexus configured) ──────────────────────────

class TestNoNexusConfigured:

    def test_manager_created_without_nexus_client(self):
        """AuthenticationManager can be created without gateway_url (no Nexus client)."""
        manager = AuthenticationManager({})
        assert manager.nexus_client is None

    @pytest.mark.asyncio
    async def test_authenticate_raises_when_no_nexus(self):
        """authenticate() raises RuntimeError when NEXUS_GATEWAY_URL is not set."""
        manager = AuthenticationManager({})
        with pytest.raises(RuntimeError, match="NEXUS_GATEWAY_URL is not configured"):
            await manager.authenticate("shopify")

    @pytest.mark.asyncio
    async def test_authenticate_returns_connection_id(self):
        """authenticate() returns connection_id from NexusClient."""
        manager = _make_manager_with_mock_nexus()
        conn_id = await manager.authenticate("shopify", user_id="u1")
        assert conn_id == "conn_abc"
        await manager.close()

    @pytest.mark.asyncio
    async def test_authenticate_caches_connection(self):
        """authenticate() returns cached connection_id on repeat calls."""
        manager = _make_manager_with_mock_nexus()
        conn1 = await manager.authenticate("github")
        conn2 = await manager.authenticate("github")
        assert conn1 == conn2
        # Only one request_connection call — second was cached
        manager.nexus_client.request_connection.assert_called_once()
        await manager.close()

    @pytest.mark.asyncio
    async def test_default_user_id_used(self):
        """nexus_default_user_id is passed to request_connection."""
        manager = _make_manager_with_mock_nexus(nexus_default_user_id="custom-agent")
        await manager.authenticate("slack")
        call_kwargs = manager.nexus_client.request_connection.call_args
        assert call_kwargs.kwargs.get("user_id") or call_kwargs.args[1] == "custom-agent"
        await manager.close()


# ── Production Mode ───────────────────────────────────────────────

class TestProdMode:

    def test_no_nexus_client_when_gateway_url_absent(self):
        """Without gateway_url, nexus_client is None — no hard error at construction."""
        manager = AuthenticationManager({"auth_mode": "production"})
        assert manager.nexus_client is None

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

        with pytest.raises(RuntimeError, match="Nexus auth flow for 'shopify' did not complete"):
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
    async def test_cache_hit(self):
        manager = _make_manager_with_mock_nexus(auth_strategy_cache_ttl=300)
        mock_strategy = DynamicStrategy(
            type="oauth2",
            credentials={"access_token": "tok_cached"},
            expires_at="2030-01-01T00:00:00Z",
        )
        manager.nexus_client.resolve_strategy = AsyncMock(return_value=mock_strategy)

        conn_id = await manager.authenticate("github")
        s1 = await manager.resolve_strategy(conn_id)
        s2 = await manager.resolve_strategy(conn_id)

        # Both should return same strategy (from cache)
        assert s1.credentials == s2.credentials
        # resolve_strategy on nexus_client called only once (second hit is cached)
        manager.nexus_client.resolve_strategy.assert_called_once()
        await manager.close()

    @pytest.mark.asyncio
    async def test_cache_miss_on_ttl_expiry(self):
        manager = _make_manager_with_mock_nexus(auth_strategy_cache_ttl=0)
        mock_strategy = DynamicStrategy(
            type="api_key",
            credentials={"api_key": "k1"},
        )
        manager.nexus_client.resolve_strategy = AsyncMock(return_value=mock_strategy)

        conn_id = await manager.authenticate("test_provider")

        s1 = await manager.resolve_strategy(conn_id)
        s2 = await manager.resolve_strategy(conn_id)

        # TTL=0 → both calls hit nexus
        assert manager.nexus_client.resolve_strategy.call_count == 2
        assert s1.type == s2.type
        await manager.close()


# ── resolve_auth_context ──────────────────────────────────────────

class TestResolveStrategy:

    @pytest.mark.asyncio
    async def test_resolve_strategy_calls_nexus(self):
        manager = _make_manager_with_mock_nexus()
        mock_strategy = DynamicStrategy(
            type="oauth2",
            credentials={"access_token": "live_token"},
            expires_at="2030-01-01T00:00:00Z",
        )
        manager.nexus_client.resolve_strategy = AsyncMock(return_value=mock_strategy)

        strategy = await manager.resolve_strategy("conn_xyz")
        assert strategy.type == "oauth2"
        assert strategy.credentials["access_token"] == "live_token"
        await manager.close()

    @pytest.mark.asyncio
    async def test_resolve_strategy_raises_when_no_nexus(self):
        """resolve_strategy raises AttributeError when nexus_client is None."""
        manager = AuthenticationManager({})
        with pytest.raises(AttributeError):
            await manager.resolve_strategy("conn_xyz")

    @pytest.mark.asyncio
    async def test_resolve_strategy_populates_cache(self):
        manager = _make_manager_with_mock_nexus()
        mock_strategy = DynamicStrategy(
            type="api_key",
            credentials={"api_key": "key123"},
        )
        manager.nexus_client.resolve_strategy = AsyncMock(return_value=mock_strategy)

        await manager.resolve_strategy("conn_abc")
        assert "conn_abc" in manager._strategy_cache
        await manager.close()


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
            failed_grace_period=0,  # No grace period — FAILED is immediately terminal
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
    async def test_close_without_nexus(self):
        """close() is a no-op when no NexusClient is configured."""
        manager = AuthenticationManager({})
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
