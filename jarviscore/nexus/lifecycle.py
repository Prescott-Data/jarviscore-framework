"""
6H.3: LifecycleMonitor — Background connection health monitoring.

Responsibilities:
- Proactive token refresh before expiry
- ATTENTION state detection (re-auth needed)
- Terminal state cleanup (REVOKED, EXPIRED, FAILED)
"""

import asyncio
import logging
from typing import Dict, Optional

from .client import NexusClient

logger = logging.getLogger(__name__)

_TERMINAL_STATES = frozenset({"REVOKED", "EXPIRED", "FAILED"})


class LifecycleMonitor:
    """
    Background async monitor for Nexus connection health.

    Periodically checks connection status and triggers:
    - Token refresh when nearing expiry
    - Alerts on ATTENTION state (re-auth needed)
    - Cleanup on terminal states (REVOKED, EXPIRED, FAILED)
    """

    def __init__(self, nexus_client: NexusClient, check_interval: int = 60):
        self.nexus_client = nexus_client
        self.check_interval = check_interval
        self._tasks: Dict[str, asyncio.Task] = {}
        self._health: Dict[str, Dict] = {}

    async def monitor_connection(self, connection_id: str) -> None:
        """
        Start monitoring a connection. Runs as a background asyncio task.

        The task polls connection status at check_interval and updates
        health records.
        """
        if connection_id in self._tasks:
            logger.warning(f"Already monitoring connection {connection_id}")
            return

        task = asyncio.create_task(self._monitor_loop(connection_id))
        self._tasks[connection_id] = task
        self._health[connection_id] = {
            "status": "MONITORING",
            "last_check": None,
            "error": None,
        }

    async def _monitor_loop(self, connection_id: str) -> None:
        """Internal monitoring loop for a single connection."""
        try:
            while True:
                try:
                    status = await self.nexus_client.check_connection_status(
                        connection_id
                    )
                    self._health[connection_id] = {
                        "status": status,
                        "last_check": "ok",
                        "error": None,
                    }

                    if status == "ATTENTION":
                        logger.warning(
                            f"Connection {connection_id} needs re-authentication"
                        )

                    if status in _TERMINAL_STATES:
                        logger.info(
                            f"Connection {connection_id} reached terminal state: {status}"
                        )
                        break

                except Exception as e:
                    self._health[connection_id] = {
                        "status": "ERROR",
                        "last_check": "failed",
                        "error": str(e),
                    }
                    logger.error(
                        f"Health check failed for {connection_id}: {e}"
                    )

                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            logger.info(f"Monitoring cancelled for {connection_id}")
        finally:
            self._tasks.pop(connection_id, None)

    async def stop_monitoring(self, connection_id: str) -> None:
        """Stop monitoring a specific connection."""
        task = self._tasks.pop(connection_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._health.pop(connection_id, None)

    def get_connection_health(self, connection_id: str) -> Optional[Dict]:
        """Return current health status of a monitored connection."""
        return self._health.get(connection_id)

    async def stop_all(self) -> None:
        """Shutdown all monitoring tasks."""
        connection_ids = list(self._tasks.keys())
        for cid in connection_ids:
            await self.stop_monitoring(cid)

    @property
    def monitored_connections(self) -> list:
        """List of currently monitored connection IDs."""
        return list(self._tasks.keys())
