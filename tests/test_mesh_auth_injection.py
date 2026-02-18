"""
Tests for Phase 7D: Mesh auth wiring.

What these tests prove:
- _auth_manager is None by default (no auth_mode in config)
- _auth_manager is created when auth_mode is set in config
- Agents with requires_auth=True receive _auth_manager via injection
- Agents without requires_auth are NOT given _auth_manager
- auth_manager.close() is called on mesh.stop()
- _redis_store is None when no redis_store_url is in config
- WorkflowEngine receives redis_store from Mesh

These tests mock AuthenticationManager and RedisContextStore so they
don't require live network or Redis.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict

import pytest

from jarviscore import Mesh
from jarviscore.core.agent import Agent


# ======================================================================
# Test agents
# ======================================================================

class PlainAgent(Agent):
    role = "plain"
    capabilities = ["plain"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": "plain"}


class AuthAgent(Agent):
    role = "auth_worker"
    capabilities = ["auth_worker"]
    requires_auth = True

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": "authed"}


# ======================================================================
# Default: no auth config
# ======================================================================

class TestNoAuthConfig:
    @pytest.mark.asyncio
    async def test_no_auth_manager_by_default(self):
        mesh = Mesh(mode="autonomous")
        mesh.add(PlainAgent)
        await mesh.start()
        try:
            assert mesh._auth_manager is None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_no_redis_store_by_default(self):
        mesh = Mesh(mode="autonomous")
        mesh.add(PlainAgent)
        await mesh.start()
        try:
            assert mesh._redis_store is None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_plain_agent_has_no_auth_manager(self):
        mesh = Mesh(mode="autonomous")
        agent = mesh.add(PlainAgent)
        await mesh.start()
        try:
            assert not hasattr(agent, "_auth_manager") or agent._auth_manager is None
        finally:
            await mesh.stop()


# ======================================================================
# Auth injection when auth_mode is set
# ======================================================================

class TestAuthInjection:
    @pytest.mark.asyncio
    async def test_auth_manager_created_with_auth_mode(self):
        mock_auth = MagicMock()
        mock_auth.close = AsyncMock()

        with patch(
            "jarviscore.auth.manager.AuthenticationManager",
            return_value=mock_auth
        ):
            mesh = Mesh(mode="autonomous", config={"auth_mode": "development"})
            mesh.add(PlainAgent)
            await mesh.start()
            try:
                assert mesh._auth_manager is mock_auth
            finally:
                await mesh.stop()

    @pytest.mark.asyncio
    async def test_requires_auth_agent_receives_auth_manager(self):
        mock_auth = MagicMock()
        mock_auth.close = AsyncMock()

        with patch(
            "jarviscore.auth.manager.AuthenticationManager",
            return_value=mock_auth
        ):
            mesh = Mesh(mode="autonomous", config={"auth_mode": "development"})
            agent = mesh.add(AuthAgent)
            await mesh.start()
            try:
                assert agent._auth_manager is mock_auth
            finally:
                await mesh.stop()

    @pytest.mark.asyncio
    async def test_plain_agent_not_injected(self):
        mock_auth = MagicMock()
        mock_auth.close = AsyncMock()

        with patch(
            "jarviscore.auth.manager.AuthenticationManager",
            return_value=mock_auth
        ):
            mesh = Mesh(mode="autonomous", config={"auth_mode": "development"})
            plain = mesh.add(PlainAgent)
            await mesh.start()
            try:
                # PlainAgent has requires_auth=False (not set), so no injection
                assert getattr(plain, "_auth_manager", None) is None
            finally:
                await mesh.stop()


# ======================================================================
# stop() calls auth_manager.close()
# ======================================================================

class TestAuthManagerCleanup:
    @pytest.mark.asyncio
    async def test_close_called_on_stop(self):
        mock_auth = MagicMock()
        mock_auth.close = AsyncMock()

        with patch(
            "jarviscore.auth.manager.AuthenticationManager",
            return_value=mock_auth
        ):
            mesh = Mesh(mode="autonomous", config={"auth_mode": "development"})
            mesh.add(PlainAgent)
            await mesh.start()
            await mesh.stop()

        mock_auth.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auth_manager_none_after_stop(self):
        mock_auth = MagicMock()
        mock_auth.close = AsyncMock()

        with patch(
            "jarviscore.auth.manager.AuthenticationManager",
            return_value=mock_auth
        ):
            mesh = Mesh(mode="autonomous", config={"auth_mode": "development"})
            mesh.add(PlainAgent)
            await mesh.start()
            await mesh.stop()
            assert mesh._auth_manager is None


# ======================================================================
# Redis store injection
# ======================================================================

class TestRedisStoreInjection:
    @pytest.mark.asyncio
    async def test_redis_store_created_with_url(self):
        mock_store = MagicMock()

        with patch(
            "jarviscore.storage.redis_store.RedisContextStore",
            return_value=mock_store
        ):
            mesh = Mesh(
                mode="autonomous",
                config={"redis_store_url": "redis://localhost:6379/0"}
            )
            mesh.add(PlainAgent)
            await mesh.start()
            try:
                assert mesh._redis_store is mock_store
            finally:
                await mesh.stop()

    @pytest.mark.asyncio
    async def test_workflow_engine_receives_redis_store(self):
        mock_store = MagicMock()

        with patch(
            "jarviscore.storage.redis_store.RedisContextStore",
            return_value=mock_store
        ):
            mesh = Mesh(
                mode="autonomous",
                config={"redis_store_url": "redis://localhost:6379/0"}
            )
            mesh.add(PlainAgent)
            await mesh.start()
            try:
                assert mesh._workflow_engine.redis_store is mock_store
            finally:
                await mesh.stop()
