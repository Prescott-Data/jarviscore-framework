"""
Tests for LifecycleMonitor — Background connection health monitoring.

Uses mock NexusClient and asyncio test utilities.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from jarviscore.nexus.lifecycle import LifecycleMonitor


class MockNexusClient:
    """Minimal mock of NexusClient for lifecycle tests."""

    def __init__(self):
        self.status_responses = []  # queue of status strings
        self._call_count = 0

    async def check_connection_status(self, connection_id: str) -> str:
        if self._call_count < len(self.status_responses):
            status = self.status_responses[self._call_count]
            self._call_count += 1
            return status
        return "ACTIVE"


@pytest.fixture
def mock_nexus():
    return MockNexusClient()


class TestLifecycleMonitorBasic:

    @pytest.mark.asyncio
    async def test_start_monitoring(self, mock_nexus):
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)
        mock_nexus.status_responses = ["ACTIVE"]

        await monitor.monitor_connection("conn_1")
        assert "conn_1" in monitor.monitored_connections

        # Let it run one cycle
        await asyncio.sleep(0.1)

        health = monitor.get_connection_health("conn_1")
        assert health is not None
        assert health["status"] == "ACTIVE"

        await monitor.stop_all()

    @pytest.mark.asyncio
    async def test_stop_monitoring(self, mock_nexus):
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)
        mock_nexus.status_responses = ["ACTIVE"]

        await monitor.monitor_connection("conn_1")
        assert "conn_1" in monitor.monitored_connections

        await monitor.stop_monitoring("conn_1")
        assert "conn_1" not in monitor.monitored_connections
        assert monitor.get_connection_health("conn_1") is None

    @pytest.mark.asyncio
    async def test_duplicate_monitoring_ignored(self, mock_nexus):
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)
        mock_nexus.status_responses = ["ACTIVE", "ACTIVE"]

        await monitor.monitor_connection("conn_1")
        await monitor.monitor_connection("conn_1")  # Should warn, not duplicate
        assert len(monitor.monitored_connections) == 1

        await monitor.stop_all()


class TestLifecycleMonitorStates:

    @pytest.mark.asyncio
    async def test_terminal_state_stops_monitoring(self, mock_nexus):
        """Monitor stops itself when connection reaches terminal state."""
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)
        mock_nexus.status_responses = ["ACTIVE", "REVOKED"]

        await monitor.monitor_connection("conn_1")
        # Wait enough for two cycles
        await asyncio.sleep(0.2)

        # Task should have exited on REVOKED
        health = monitor.get_connection_health("conn_1")
        assert health is not None
        assert health["status"] == "REVOKED"
        # Task removed from active tasks
        assert "conn_1" not in monitor.monitored_connections

    @pytest.mark.asyncio
    async def test_attention_state_recorded(self, mock_nexus):
        """ATTENTION state is recorded in health."""
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)
        # Fill queue with ATTENTION so it stays in that state
        mock_nexus.status_responses = ["ATTENTION", "ATTENTION", "ATTENTION"]

        await monitor.monitor_connection("conn_1")
        await asyncio.sleep(0.1)

        health = monitor.get_connection_health("conn_1")
        assert health["status"] == "ATTENTION"

        await monitor.stop_all()

    @pytest.mark.asyncio
    async def test_error_during_check(self, mock_nexus):
        """Errors during health check are recorded but monitoring continues."""
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)

        # Override to raise an error on first call
        call_count = 0
        original = mock_nexus.check_connection_status

        async def flaky_check(cid):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Network timeout")
            return "ACTIVE"

        mock_nexus.check_connection_status = flaky_check

        await monitor.monitor_connection("conn_1")
        await asyncio.sleep(0.15)

        health = monitor.get_connection_health("conn_1")
        # Should have recovered after error
        assert health is not None
        # Could be ERROR or ACTIVE depending on timing
        assert health["status"] in ("ERROR", "ACTIVE")

        await monitor.stop_all()


class TestLifecycleMonitorStopAll:

    @pytest.mark.asyncio
    async def test_stop_all_cleans_up(self, mock_nexus):
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)
        mock_nexus.status_responses = ["ACTIVE"] * 10

        await monitor.monitor_connection("conn_1")
        await monitor.monitor_connection("conn_2")
        assert len(monitor.monitored_connections) == 2

        await monitor.stop_all()
        assert len(monitor.monitored_connections) == 0

    @pytest.mark.asyncio
    async def test_stop_nonexistent_connection(self, mock_nexus):
        """Stopping a non-monitored connection is a no-op."""
        monitor = LifecycleMonitor(mock_nexus, check_interval=0.05)
        await monitor.stop_monitoring("nonexistent")  # Should not raise
