"""Elastic worker pools: one logical agent, as many members as its queued work needs."""

import asyncio
import time
from typing import ClassVar

import pytest

from jarviscore import Pool
from jarviscore.core.agent import Agent
from jarviscore.core.mesh import Mesh
from jarviscore.core.pool import PoolState
from jarviscore.testing import MockRedisContextStore


class PooledVerifier(Agent):
    role = "verifier"
    capabilities: ClassVar[list[str]] = ["verify"]
    running = 0
    peak = 0
    instances: ClassVar[set] = set()
    agent_ids: ClassVar[set] = set()
    torn_down = 0
    seconds = 0.05

    @classmethod
    def reset(cls):
        cls.running = cls.peak = cls.torn_down = 0
        cls.instances, cls.agent_ids = set(), set()

    async def teardown(self):
        type(self).torn_down += 1
        await super().teardown()

    async def execute_task(self, task):
        cls = type(self)
        cls.instances.add(id(self))
        cls.agent_ids.add(self.agent_id)
        cls.running += 1
        cls.peak = max(cls.peak, cls.running)
        try:
            await asyncio.sleep(cls.seconds)
        finally:
            cls.running -= 1
        return {"status": "success", "output": {"verified": task["id"]}}


def _mesh(monkeypatch, store, **config):
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    return Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.01, **config})


def _publish(store, count, prefix="claim"):
    for index in range(count):
        store.publish_workflow(
            f"{prefix}-{index}",
            goal=f"Verify claim {index}",
            obligations=[],
            steps=[{"id": "verification_assessment", "capability": "verify",
                    "effect": "read", "task": f"Verify claim {index}", "depends_on": []}],
        )


async def _wait_completed(store, count, prefix="claim", timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        statuses = [store.get_step_status(f"{prefix}-{i}", "verification_assessment")
                    for i in range(count)]
        if all(status == "completed" for status in statuses):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"steps did not complete: {statuses}")


@pytest.mark.asyncio
async def test_a_pool_runs_queued_steps_on_as_many_members_as_allowed(monkeypatch):
    PooledVerifier.reset()
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store)
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(min=1, max=6))
    _publish(store, 18)

    await mesh.start()
    started = time.perf_counter()
    try:
        await _wait_completed(store, 18)
        elapsed = time.perf_counter() - started
        diagnostics = mesh.get_diagnostics()["pools"]["verifier"]
    finally:
        await mesh.stop()

    assert PooledVerifier.peak == 6
    assert len(PooledVerifier.instances) == 6
    # One logical agent: every member carries the registered id, so any can resume.
    assert PooledVerifier.agent_ids == {"verifier"}
    assert elapsed < 18 * PooledVerifier.seconds / 2
    assert diagnostics["members"] == 6 and diagnostics["steps_started"] == 18
    assert len(mesh.agents) == 1
    # Members other than the registered agent are torn down with the mesh.
    assert PooledVerifier.torn_down == 6


@pytest.mark.asyncio
async def test_each_step_is_claimed_and_run_exactly_once(monkeypatch):
    PooledVerifier.reset()
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store)
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(max=8))
    _publish(store, 24)

    await mesh.start()
    try:
        await _wait_completed(store, 24)
    finally:
        await mesh.stop()

    claimed = [
        event for i in range(24)
        for event in store.get_ledger_full(f"claim-{i}") if event["event"] == "step_claimed"
    ]
    assert len(claimed) == 24


@pytest.mark.asyncio
async def test_idle_members_beyond_min_are_retired(monkeypatch):
    PooledVerifier.reset()
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store)
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(min=2, max=5, idle_seconds=0.05))
    _publish(store, 10)

    await mesh.start()
    try:
        await _wait_completed(store, 10)
        deadline = time.monotonic() + 2
        while mesh._pools["verifier"].snapshot()["members"] > 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        members = mesh._pools["verifier"].snapshot()["members"]
    finally:
        await mesh.stop()

    assert PooledVerifier.peak == 5
    assert members == 2


@pytest.mark.asyncio
async def test_a_step_pinned_for_resume_goes_to_any_member_of_its_pool(monkeypatch):
    PooledVerifier.reset()
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store)
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(max=3))
    _publish(store, 1, prefix="resumed")
    graph = store._store._redis
    import json

    raw = json.loads(graph.hget("workflow_graph:resumed-0", "verification_assessment"))
    raw["resume_agent_id"] = "verifier"
    graph.hset("workflow_graph:resumed-0", "verification_assessment", json.dumps(raw))

    await mesh.start()
    try:
        await _wait_completed(store, 1, prefix="resumed")
    finally:
        await mesh.stop()


@pytest.mark.asyncio
async def test_unpooled_agents_keep_one_step_at_a_time(monkeypatch):
    PooledVerifier.reset()
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store)
    mesh.add(PooledVerifier, agent_id="verifier")
    _publish(store, 4)

    await mesh.start()
    try:
        await _wait_completed(store, 4)
    finally:
        await mesh.stop()

    assert PooledVerifier.peak == 1
    assert len(PooledVerifier.instances) == 1


def test_a_pool_needs_the_agent_class():
    mesh = Mesh(config={"p2p_enabled": False})
    with pytest.raises(TypeError, match="pass the class"):
        mesh.add(PooledVerifier(agent_id="verifier"), pool=Pool())


@pytest.mark.parametrize("arguments", [
    {"min": 0}, {"min": 3, "max": 2}, {"idle_seconds": -1}, {"lane": "fast"},
])
def test_pool_limits_are_validated(arguments):
    with pytest.raises(ValueError):
        Pool(**arguments)


def test_only_idle_members_beyond_min_retire_and_never_the_registered_agent():
    base, first, second = object(), object(), object()
    state = PoolState(spec=Pool(min=2, max=4, idle_seconds=0), factory=object, base=base)
    state.members += [first, second]
    state.idle = [base, first, second]

    retiring = state.retirable()

    assert base not in retiring
    assert len(retiring) == 1
