"""Capability visibility across a mesh whose members join one after another.

Capabilities used to be exchanged once, at each node's startup, with whichever
members that node could already see. A node that joined later stayed invisible
to peers that had already announced, and could not see members that joined
after it, so a twelve-node mesh never converged.
"""
import asyncio

import pytest

from jarviscore.config import get_config_from_dict
from jarviscore.p2p.coordinator import P2PCoordinator
from jarviscore.profiles import CustomAgent

BASE_PORT = 7741
NODE_COUNT = 12


def _agent(index: int) -> CustomAgent:
    cls = type(
        f"Peer{index}",
        (CustomAgent,),
        {"role": f"peer_{index}", "capabilities": [f"capability_{index}"]},
    )
    return cls(f"peer-{index}")


@pytest.mark.integration
@pytest.mark.slow
async def test_membership_alone_converges_twelve_sequential_joiners():
    # No node runs the startup announce/request exchange, so every capability a
    # node learns must arrive because SWIM reported the member.
    coordinators = []
    try:
        for index in range(NODE_COUNT):
            config = {
                "bind_host": "127.0.0.1",
                "bind_port": BASE_PORT + index,
                "node_name": f"peer-{index}",
            }
            if index:
                config["seed_nodes"] = f"127.0.0.1:{BASE_PORT}"
            coordinator = P2PCoordinator([_agent(index)], get_config_from_dict(config))
            await coordinator.start()
            coordinators.append(coordinator)

        def missing():
            gaps = {}
            for index, coordinator in enumerate(coordinators):
                seen = {info["role"] for info in coordinator.list_remote_agents()}
                expected = {f"peer_{other}" for other in range(NODE_COUNT) if other != index}
                if expected - seen:
                    gaps[index] = sorted(expected - seen)
            return gaps

        deadline = asyncio.get_running_loop().time() + 90
        while missing() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.5)

        assert not missing(), f"nodes missing peers: {missing()}"
    finally:
        for coordinator in reversed(coordinators):
            await coordinator.stop()
