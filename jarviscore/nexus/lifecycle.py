"""
LifecycleMonitor — Background connection health monitoring for Nexus.

Responsibilities:
- Proactive token refresh before expiry (via Gateway POST /v1/refresh/{id})
- ATTENTION state detection (re-auth needed — notify the human)
- Terminal state cleanup (REVOKED, EXPIRED, FAILED — stop monitoring)

The monitor runs as async tasks — one per connection — polling the Gateway
for status and triggering refresh when tokens approach expiry.
"""

import asyncio
import logging
from typing import Callable, Dict, Optional

from .client import NexusClient

logger = logging.getLogger(__name__)

_TERMINAL_STATES = frozenset({"REVOKED", "EXPIRED", "FAILED"})


class LifecycleMonitor:
    """
    Background async monitor for Nexus connection health.

    Periodically checks connection status via the Nexus Gateway and:
    - Proactively refreshes tokens before they expire
    - Logs warnings on ATTENTION state (user must re-consent)
    - Stops monitoring on terminal states

    Usage:
        monitor = LifecycleMonitor(nexus_client)
        await monitor.monitor_connection("conn_abc123")
        # ... runs in background ...
        await monitor.stop_all()
    """

    def __init__(
        self,
        nexus_client: NexusClient,
        check_interval: int = 60,
        on_attention: Optional[Callable[[str], None]] = None,
    ):
        self.nexus_client = nexus_client
        self.check_interval = check_interval
        self.on_attention = on_attention  # Optional callback when re-auth needed
        self._tasks: Dict[str, asyncio.Task] = {}
        self._health: Dict[str, Dict] = {}

    async def monitor_connection(self, connection_id: str) -> None:
        """
        Start monitoring a connection. Runs as a background asyncio task.

        The task polls connection status at check_interval and:
        - Refreshes tokens proactively when nearing expiry
        - Triggers on_attention callback when user action is needed
        - Auto-stops on terminal states
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

                    if status == "ACTIVE":
                        # Proactively refresh to keep tokens warm
                        try:
                            await self.nexus_client.refresh_connection(connection_id)
                        except Exception as refresh_err:
                            # Refresh failures are non-fatal — token may still be valid
                            logger.debug(
                                f"Proactive refresh for {connection_id} skipped: {refresh_err}"
                            )

                    if status == "ATTENTION":
                        logger.warning(
                            f"Connection {connection_id} needs re-authentication. "
                            f"The user must complete a new OAuth handshake."
                        )
                        if self.on_attention:
                            try:
                                self.on_attention(connection_id)
                            except Exception:
                                pass

                    if status in _TERMINAL_STATES:
                        logger.info(
                            f"Connection {connection_id} reached terminal state: {status}. "
                            f"Stopping monitor."
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
