"""A node that leaves the mesh must leave every other node's roster too.

Remote agents used to be added on announcement and never removed: a clean
stop sent no deannouncement, and nothing checked the roster against SWIM
membership. Peers kept listing departed agents and their requests timed out.
"""
import asyncio

import pytest

from jarviscore.config import get_config_from_dict
from jarviscore.p2p.coordinator import P2PCoordinator
from jarviscore.profiles import CustomAgent

BASE_PORT = 7781


def _agent(index: int) -> CustomAgent:
    cls = type(
        f"Leaver{index}",
        (CustomAgent,),
        {"role": f"leaver_{index}", "capabilities": [f"leaving_{index}"]},
    )
    return cls(f"leaver-{index}")


# Reconciliation against SWIM member states, no network


def _coordinator_knowing(*node_ids: str) -> P2PCoordinator:
    """An unstarted coordinator whose roster holds one agent per node."""
    coordinator = P2PCoordinator([], {})
    for index, node_id in enumerate(node_ids):
        agent_id = f"agent-{index}"
        coordinator._remote_agent_registry[agent_id] = {
            "role": f"role_{index}", "capabilities": [f"cap_{index}"], "node_id": node_id,
        }
        coordinator._capability_map[f"cap_{index}"] = [agent_id]
    coordinator.requested = []
    coordinator._schedule_capability_request = coordinator.requested.append
    return coordinator


def test_dead_node_is_dropped_from_the_roster():
    coordinator = _coordinator_knowing("10.0.0.1:7946", "10.0.0.2:7946")

    coordinator._reconcile_roster({"10.0.0.1:7946": "DEAD", "10.0.0.2:7946": "ALIVE"})

    assert list(coordinator._remote_agent_registry) == ["agent-1"]
    assert "cap_0" not in coordinator._capability_map
    assert coordinator._capability_map["cap_1"] == ["agent-1"]


def test_suspect_node_is_kept():
    coordinator = _coordinator_knowing("10.0.0.1:7946")

    coordinator._reconcile_roster({"10.0.0.1:7946": "SUSPECT"})

    assert "agent-0" in coordinator._remote_agent_registry


def test_node_unknown_to_swim_is_kept():
    # An announcement can arrive before gossip tells SWIM about its sender.
    coordinator = _coordinator_knowing("10.0.0.1:7946")

    coordinator._reconcile_roster({})

    assert "agent-0" in coordinator._remote_agent_registry


def test_returning_node_is_asked_to_announce_again_once():
    coordinator = _coordinator_knowing("10.0.0.1:7946")
    coordinator._reconcile_roster({"10.0.0.1:7946": "DEAD"})

    coordinator._reconcile_roster({"10.0.0.1:7946": "ALIVE"})
    coordinator._reconcile_roster({"10.0.0.1:7946": "ALIVE"})

    assert coordinator.requested == ["10.0.0.1:7946"]


def test_alive_node_that_never_died_is_not_asked():
    coordinator = _coordinator_knowing("10.0.0.1:7946")

    coordinator._reconcile_roster({"10.0.0.1:7946": "ALIVE"})

    assert coordinator.requested == []


# Real three-node meshes


async def _start_mesh(base_port: int, size: int = 3):
    coordinators = []
    for index in range(size):
        config = {
            "bind_host": "127.0.0.1",
            "bind_port": base_port + index,
            "node_name": f"leaver-{index}",
        }
        if index:
            config["seed_nodes"] = f"127.0.0.1:{base_port}"
        coordinator = P2PCoordinator([_agent(index)], get_config_from_dict(config))
        await coordinator.start()
        coordinators.append(coordinator)
    return coordinators


def _roles(coordinator) -> set:
    return {info["role"] for info in coordinator.list_remote_agents()}


async def _wait_for(condition, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.5)
    return True


async def _converged(coordinators) -> None:
    size = len(coordinators)

    def everyone_sees_everyone():
        return all(
            _roles(c) >= {f"leaver_{o}" for o in range(size) if o != i}
            for i, c in enumerate(coordinators)
        )

    assert await _wait_for(everyone_sees_everyone, 60), "mesh never converged"


@pytest.mark.integration
@pytest.mark.slow
async def test_clean_stop_removes_the_node_from_other_rosters():
    coordinators = await _start_mesh(BASE_PORT)
    leaver, survivors = coordinators[1], [coordinators[0], coordinators[2]]
    try:
        await _converged(coordinators)

        await leaver.stop()

        gone = await _wait_for(lambda: all("leaver_1" not in _roles(c) for c in survivors), 10)
        assert gone, f"survivors still list leaver_1: {[_roles(c) for c in survivors]}"
        assert all("leaving_1" not in c._capability_map for c in survivors)
    finally:
        for coordinator in reversed(coordinators):
            await coordinator.stop()


@pytest.mark.integration
@pytest.mark.slow
async def test_crashed_node_is_removed_from_every_roster():
    coordinators = await _start_mesh(BASE_PORT + 10)
    crashed, survivors = coordinators[1], [coordinators[0], coordinators[2]]
    try:
        await _converged(coordinators)

        # A crash sends no goodbye: stop the node's SWIM without deannouncing.
        crashed._started = False
        crashed.swim_manager.shutdown()

        # Suspect timeout (15s) plus failed probes and one membership check.
        gone = await _wait_for(lambda: all("leaver_1" not in _roles(c) for c in survivors), 45)
        assert gone, f"survivors still list leaver_1: {[_roles(c) for c in survivors]}"
        assert all("leaving_1" not in c._capability_map for c in survivors)
    finally:
        for coordinator in reversed(coordinators):
            await coordinator.stop()
