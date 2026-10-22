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
        await self._work()
        return {"status": "success", "output": {"verified": task.get("id") or task.get("task")}}

    async def execute_capability_request(self, capability, question, context):
        await self._work()
        return {"status": "success", "output": {"answered": question}}

    async def _handle_peer_request(self, message):
        await self._work()
        return {"status": "success", "by": id(self)}

    async def _work(self):
        cls = type(self)
        cls.instances.add(id(self))
        cls.agent_ids.add(self.agent_id)
        cls.running += 1
        cls.peak = max(cls.peak, cls.running)
        try:
            await asyncio.sleep(cls.seconds)
        finally:
            cls.running -= 1


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
async def test_work_that_loses_its_claim_stops_and_the_pool_carries_on(monkeypatch):
    PooledVerifier.reset()
    PooledVerifier.seconds = 30.0
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store, distributed_claim_lease_seconds=1)
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(max=2))
    _publish(store, 1, prefix="held")

    await mesh.start()
    try:
        deadline = time.monotonic() + 5
        while PooledVerifier.running == 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert PooledVerifier.running == 1
        # Another node takes the step over, as after a pause longer than the lease.
        store._redis.set("step_lock:held-0:verification_assessment", "elsewhere:claim")

        deadline = time.monotonic() + 5
        while PooledVerifier.running and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert PooledVerifier.running == 0

        PooledVerifier.seconds = 0.05
        _publish(store, 1, prefix="next")
        await _wait_completed(store, 1, prefix="next")
    finally:
        PooledVerifier.seconds = 0.05
        await mesh.stop()


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


@pytest.mark.asyncio
async def test_a_state_change_wakes_waiting_loops_before_the_poll_interval():
    mesh = Mesh(config={"p2p_enabled": False})
    mark = mesh._activity_generation
    waiting = asyncio.create_task(mesh._idle(30, mark))
    await asyncio.sleep(0)

    started = time.monotonic()
    mesh._wake_workers()
    await asyncio.wait_for(waiting, timeout=1)

    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_a_change_made_during_a_scan_is_not_slept_through():
    mesh = Mesh(config={"p2p_enabled": False})
    mark = mesh._activity_generation
    mesh._wake_workers()

    await asyncio.wait_for(mesh._idle(30, mark), timeout=0.5)


@pytest.mark.asyncio
async def test_a_goal_waiter_wakes_for_its_own_workflow_only():
    mesh = Mesh(config={"p2p_enabled": False})
    mark = mesh._workflow_mark("wf-a")
    waiting = asyncio.create_task(mesh._idle_for(30, mark))

    mesh._wake_workers("wf-b")
    await asyncio.sleep(0.05)
    assert not waiting.done()

    mesh._wake_workers("wf-a")
    await asyncio.wait_for(waiting, timeout=1)


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


# ── Every way work reaches an agent goes through its pool ─────────────────────

@pytest.mark.asyncio
async def test_fanout_items_each_hold_their_own_member(monkeypatch):
    PooledVerifier.reset()
    mesh = _mesh(monkeypatch, MockRedisContextStore())
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(max=4))

    await mesh.start()
    try:
        result = await mesh.fanout(
            "claims", agent="verifier", items=list(range(8)), task="verify", concurrency=8,
        )
    finally:
        await mesh.stop()

    assert len(result.succeeded) == 8
    assert PooledVerifier.peak == 4
    assert len(PooledVerifier.instances) == 4


@pytest.mark.asyncio
async def test_fanout_on_an_agent_without_a_pool_runs_one_item_at_a_time(monkeypatch):
    PooledVerifier.reset()
    mesh = _mesh(monkeypatch, MockRedisContextStore())
    mesh.add(PooledVerifier, agent_id="verifier")

    await mesh.start()
    try:
        result = await mesh.fanout(
            "claims", agent="verifier", items=list(range(4)), task="verify", concurrency=4,
        )
    finally:
        await mesh.stop()

    assert len(result.succeeded) == 4
    assert PooledVerifier.peak == 1


@pytest.mark.asyncio
async def test_capability_needs_are_answered_on_as_many_members_as_allowed(monkeypatch):
    PooledVerifier.reset()
    PooledVerifier.seconds = 0.2
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store)
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(max=4))
    store.publish_workflow(
        "asks", goal="Check four claims", obligations=[],
        steps=[{"id": "plan", "capability": "planning", "effect": "read",
                "task": "Plan", "depends_on": []}],
    )
    need_ids = [
        store.publish_capability_need(
            "asks", requester_agent_id="planner", requester_step_id="plan",
            capability="verify", question=f"Claim {i}?", context={},
        )
        for i in range(4)
    ]

    await mesh.start()
    started = time.monotonic()
    try:
        deadline = started + 5
        while time.monotonic() < deadline:
            needs = [store.get_capability_need("asks", need_id) for need_id in need_ids]
            if all(need["status"] == "fulfilled" for need in needs):
                break
            await asyncio.sleep(0.01)
        elapsed = time.monotonic() - started
    finally:
        PooledVerifier.seconds = 0.05
        await mesh.stop()

    assert [need["result"]["output"]["answered"] for need in needs] == [
        f"Claim {i}?" for i in range(4)
    ]
    assert PooledVerifier.peak == 4
    # One at a time would take four times as long.
    assert elapsed < 0.2 * 4 * 0.75


@pytest.mark.asyncio
async def test_peer_requests_are_answered_on_separate_members(monkeypatch):
    PooledVerifier.reset()
    mesh = _mesh(monkeypatch, MockRedisContextStore())
    agent = mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(max=3))

    await mesh.start()
    try:
        answers = await asyncio.gather(*(agent.peers._request_handler(object()) for _ in range(3)))
    finally:
        await mesh.stop()

    assert PooledVerifier.peak == 3
    assert len({answer["by"] for answer in answers}) == 3


@pytest.mark.asyncio
async def test_delegated_tasks_hold_an_instance_each(monkeypatch):
    PooledVerifier.reset()
    mesh = _mesh(monkeypatch, MockRedisContextStore())
    mesh.add(PooledVerifier, agent_id="verifier")

    await mesh.start()
    try:
        results = await asyncio.gather(*(mesh.delegate(to="verifier", task="go") for _ in range(3)))
    finally:
        await mesh.stop()

    assert all(result["status"] == "success" for result in results)
    assert PooledVerifier.peak == 1


class SelfDelegating(Agent):
    role = "looper"
    capabilities: ClassVar[list[str]] = ["looping"]

    async def execute_task(self, task):
        return await self._mesh.delegate(to="looper", task="again")


@pytest.mark.asyncio
async def test_an_agent_waiting_on_its_only_instance_is_told_instead_of_hanging(monkeypatch):
    mesh = _mesh(monkeypatch, MockRedisContextStore())
    mesh.add(SelfDelegating, agent_id="looper")

    await mesh.start()
    try:
        with pytest.raises(RuntimeError, match="waiting on itself"):
            await asyncio.wait_for(mesh.delegate(to="looper", task="start"), timeout=2)
    finally:
        await mesh.stop()


@pytest.mark.asyncio
async def test_a_released_member_goes_to_the_longest_waiter_first():
    base = object()
    state = PoolState(spec=Pool(min=1, max=1), factory=None, base=base, declared=False)
    held = await state.acquire()
    first = asyncio.create_task(state.acquire())
    second = asyncio.create_task(state.acquire())
    await asyncio.sleep(0)

    state.release(held)
    assert await asyncio.wait_for(first, timeout=1) is base
    assert not second.done()

    state.release(base)
    assert await asyncio.wait_for(second, timeout=1) is base


@pytest.mark.asyncio
async def test_a_cancelled_waiter_does_not_lose_the_member():
    base = object()
    state = PoolState(spec=Pool(min=1, max=1), factory=None, base=base, declared=False)
    held = await state.acquire()
    waiter = asyncio.create_task(state.acquire())
    await asyncio.sleep(0)
    waiter.cancel()
    await asyncio.gather(waiter, return_exceptions=True)

    state.release(held)

    assert state.idle == [base]


@pytest.mark.asyncio
async def test_a_pool_grows_to_max_and_no_further_under_concurrent_demand():
    grown = []

    async def grow():
        await asyncio.sleep(0.01)
        member = object()
        state.members.append(member)
        grown.append(member)
        return member

    state = PoolState(spec=Pool(min=1, max=3), factory=object, base=object())
    state.grow = grow
    taken = await asyncio.gather(*(state.try_acquire() for _ in range(5)))

    assert len(grown) == 2
    assert sum(member is not None for member in taken) == 3


def test_only_declared_pools_are_reported(monkeypatch):
    mesh = _mesh(monkeypatch, MockRedisContextStore())
    mesh.add(PooledVerifier, agent_id="verifier", pool=Pool(max=2))
    mesh.add(SelfDelegating, agent_id="looper")

    assert set(mesh.get_diagnostics()["pools"]) == {"verifier"}


class OutOfEpochs(Agent):
    role = "reader"
    capabilities: ClassVar[list[str]] = ["read_history"]
    progress = {
        "verified": False,
        "working_notes": ["2299131 run 1272015726 rejected 1 row"],
    }

    async def execute_task(self, task):
        return {"status": "epoch_exhausted", "output": None, "payload": None,
                "error": "lease exhausted", "progress": type(self).progress}


@pytest.mark.asyncio
async def test_a_step_out_of_epochs_keeps_what_it_established(monkeypatch):
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store)
    mesh.add(OutOfEpochs, agent_id="reader")
    store.publish_workflow(
        "history", goal="Check the day's runs", obligations=[],
        steps=[{"id": "read", "capability": "read_history", "effect": "read",
                "task": "Read every run", "depends_on": []}],
        budget={"max_epochs_per_step": 1},
    )

    await mesh.start()
    try:
        deadline = time.monotonic() + 5
        while store.get_step_status("history", "read") != "failed" and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        saved = store.get_step_output("history", "read")
    finally:
        await mesh.stop()

    record = saved.get("output", saved)
    assert record["typed_outcome"] == "EXECUTION_EPOCH_LIMIT_REACHED"
    assert record["progress"] == OutOfEpochs.progress
