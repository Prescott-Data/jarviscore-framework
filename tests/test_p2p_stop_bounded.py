"""Stopping a node must not wait on peers that are shutting down too."""
import asyncio
import time

from jarviscore.p2p import coordinator as coordinator_module
from jarviscore.p2p.coordinator import P2PCoordinator


async def test_stop_is_bounded_when_deannouncement_hangs(monkeypatch):
    monkeypatch.setattr(coordinator_module, "DEANNOUNCE_TIMEOUT", 0.2)
    coordinator = P2PCoordinator([], {})
    coordinator._started = True

    async def never_returns(timeout=None):
        await asyncio.sleep(3600)

    coordinator.deannounce_capabilities = never_returns

    started = time.monotonic()
    await coordinator.stop()

    assert time.monotonic() - started < 2
    assert coordinator._started is False
