"""
Tests for Phase 9: Mesh Integration + Final Wiring.

What these tests prove:
- blob_storage is always initialized after start() — local backend needs no connection
- All agents receive _blob_storage injection (same instance as mesh._blob_storage)
- All agents receive _redis_store injection (None when not configured)
- All agents receive _redis_store when redis_store_url is configured
- Multiple agents share the same store instances
- mailbox (MailboxManager) is None when redis not configured
- MailboxManager is injected into each agent when redis is available
- agent.mailbox.redis points to the same store as mesh._redis_store
- Infrastructure is available inside agent setup() (before setup runs)
- Prometheus server is NOT started by default
- Prometheus server IS started when prometheus_enabled=True in settings
"""

import pytest
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

from jarviscore import Mesh
from jarviscore.core.agent import Agent


# ======================================================================
# Shared test agents
# ======================================================================

class WorkerAgent(Agent):
    role = "worker"
    capabilities = ["work"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": "done"}


class Worker2Agent(Agent):
    role = "worker2"
    capabilities = ["work2"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": "done"}


# ======================================================================
# Blob storage initialization
# ======================================================================

class TestBlobStorageInit:
    @pytest.mark.asyncio
    async def test_blob_storage_always_initialized(self):
        """Blob storage is available even without any config (local backend)."""
        mesh = Mesh(mode="autonomous")
        mesh.add(WorkerAgent)
        await mesh.start()
        try:
            assert mesh._blob_storage is not None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_blob_storage_is_local_by_default(self):
        """Default backend is LocalBlobStorage (no Redis or Azure needed)."""
        from jarviscore.storage.local import LocalBlobStorage
        mesh = Mesh(mode="autonomous")
        mesh.add(WorkerAgent)
        await mesh.start()
        try:
            assert isinstance(mesh._blob_storage, LocalBlobStorage)
        finally:
            await mesh.stop()


# ======================================================================
# Infrastructure injection into agents
# ======================================================================

class TestInfrastructureInjection:
    @pytest.mark.asyncio
    async def test_agent_receives_blob_storage(self):
        """Every agent gets the same _blob_storage as the mesh."""
        mesh = Mesh(mode="autonomous")
        agent = mesh.add(WorkerAgent)
        await mesh.start()
        try:
            assert agent._blob_storage is mesh._blob_storage
            assert agent._blob_storage is not None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_redis_store_is_none_by_default(self):
        """Without redis_store_url, _redis_store is None on agents."""
        mesh = Mesh(mode="autonomous")
        agent = mesh.add(WorkerAgent)
        await mesh.start()
        try:
            assert agent._redis_store is None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_agent_receives_redis_store_when_configured(self):
        """When redis_store_url is set, all agents get the store instance."""
        mock_store = MagicMock()

        with patch(
            "jarviscore.storage.redis_store.RedisContextStore",
            return_value=mock_store,
        ):
            mesh = Mesh(
                mode="autonomous",
                config={"redis_store_url": "redis://localhost:6379/0"},
            )
            agent = mesh.add(WorkerAgent)
            await mesh.start()
            try:
                assert agent._redis_store is mock_store
            finally:
                await mesh.stop()

    @pytest.mark.asyncio
    async def test_multiple_agents_share_same_stores(self):
        """All agents share a single store instance (no per-agent copies)."""
        mock_store = MagicMock()

        with patch(
            "jarviscore.storage.redis_store.RedisContextStore",
            return_value=mock_store,
        ):
            mesh = Mesh(
                mode="autonomous",
                config={"redis_store_url": "redis://localhost:6379/0"},
            )
            a1 = mesh.add(WorkerAgent)
            a2 = mesh.add(Worker2Agent)
            await mesh.start()
            try:
                assert a1._redis_store is mock_store
                assert a2._redis_store is mock_store
                assert a1._blob_storage is mesh._blob_storage
                assert a2._blob_storage is mesh._blob_storage
            finally:
                await mesh.stop()


# ======================================================================
# Mailbox injection
# ======================================================================

class TestMailboxInjection:
    @pytest.mark.asyncio
    async def test_no_mailbox_without_redis(self):
        """mailbox stays None when no redis is configured."""
        mesh = Mesh(mode="autonomous")
        agent = mesh.add(WorkerAgent)
        await mesh.start()
        try:
            assert agent.mailbox is None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_mailbox_injected_when_redis_available(self):
        """A MailboxManager is created for each agent when redis is available."""
        from jarviscore.mailbox import MailboxManager

        mock_store = MagicMock()

        with patch(
            "jarviscore.storage.redis_store.RedisContextStore",
            return_value=mock_store,
        ):
            mesh = Mesh(
                mode="autonomous",
                config={"redis_store_url": "redis://localhost:6379/0"},
            )
            agent = mesh.add(WorkerAgent)
            await mesh.start()
            try:
                assert isinstance(agent.mailbox, MailboxManager)
                assert agent.mailbox.agent_id == agent.agent_id
            finally:
                await mesh.stop()

    @pytest.mark.asyncio
    async def test_mailbox_uses_correct_redis_store(self):
        """agent.mailbox.redis is the same object as mesh._redis_store."""
        mock_store = MagicMock()

        with patch(
            "jarviscore.storage.redis_store.RedisContextStore",
            return_value=mock_store,
        ):
            mesh = Mesh(
                mode="autonomous",
                config={"redis_store_url": "redis://localhost:6379/0"},
            )
            agent = mesh.add(WorkerAgent)
            await mesh.start()
            try:
                assert agent.mailbox.redis is mock_store
            finally:
                await mesh.stop()


# ======================================================================
# Infrastructure available during agent setup()
# ======================================================================

class TestInfrastructureAvailableInSetup:
    @pytest.mark.asyncio
    async def test_blob_storage_available_in_setup(self):
        """_blob_storage is already injected when agent.setup() is called."""
        seen = {}

        class SetupCheckAgent(Agent):
            role = "setup_checker"
            capabilities = ["check"]

            async def setup(self):
                seen["blob"] = self._blob_storage

            async def execute_task(self, task):
                return {"status": "success", "output": "done"}

        mesh = Mesh(mode="autonomous")
        mesh.add(SetupCheckAgent)
        await mesh.start()
        try:
            assert seen.get("blob") is not None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_redis_store_available_in_setup(self):
        """_redis_store is already injected when agent.setup() is called."""
        seen = {}
        mock_store = MagicMock()

        class SetupCheckAgent2(Agent):
            role = "setup_checker2"
            capabilities = ["check2"]

            async def setup(self):
                seen["redis"] = self._redis_store

            async def execute_task(self, task):
                return {"status": "success", "output": "done"}

        with patch(
            "jarviscore.storage.redis_store.RedisContextStore",
            return_value=mock_store,
        ):
            mesh = Mesh(
                mode="autonomous",
                config={"redis_store_url": "redis://localhost:6379/0"},
            )
            mesh.add(SetupCheckAgent2)
            await mesh.start()
            try:
                assert seen.get("redis") is mock_store
            finally:
                await mesh.stop()


# ======================================================================
# Prometheus server startup
# ======================================================================

class TestPrometheus:
    @pytest.mark.asyncio
    async def test_prometheus_not_started_by_default(self):
        """start_prometheus_server is never called unless explicitly enabled."""
        with patch(
            "jarviscore.telemetry.metrics.start_prometheus_server"
        ) as mock_start:
            mesh = Mesh(mode="autonomous")
            mesh.add(WorkerAgent)
            await mesh.start()
            try:
                mock_start.assert_not_called()
            finally:
                await mesh.stop()

    @pytest.mark.asyncio
    async def test_prometheus_started_when_enabled(self):
        """start_prometheus_server is called with the configured port."""
        mock_settings = MagicMock()
        mock_settings.prometheus_enabled = True
        mock_settings.prometheus_port = 9090
        mock_settings.redis_url = None
        mock_settings.redis_context_ttl_days = 7
        mock_settings.storage_backend = "local"
        mock_settings.storage_base_path = "./blob_storage"

        with patch(
            "jarviscore.config.settings.Settings", return_value=mock_settings
        ), patch(
            "jarviscore.telemetry.metrics.start_prometheus_server"
        ) as mock_start:
            mesh = Mesh(mode="autonomous")
            mesh.add(WorkerAgent)
            await mesh.start()
            try:
                mock_start.assert_called_once_with(9090)
            finally:
                await mesh.stop()
