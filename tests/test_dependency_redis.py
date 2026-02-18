"""
Tests for Phase 7C: DependencyManager Redis path.

What these tests prove:
- In-memory path (original): waits for deps to appear in memory dict
- Redis path (Phase 7C): polls are_dependencies_met() against Redis
- Redis path fetches step outputs from Redis after deps are met
- TimeoutError raised if deps never appear (both paths)
- check_dependencies() non-blocking helper works correctly
- register_waiting / resolve_step book-keeping still works
"""

import asyncio
import json
from typing import Any

import pytest

from jarviscore.orchestration.dependency import DependencyManager
from jarviscore.testing import MockRedisContextStore


# ======================================================================
# In-memory path (original behaviour)
# ======================================================================

class TestInMemoryPath:
    @pytest.mark.asyncio
    async def test_empty_deps_return_immediately(self):
        mgr = DependencyManager()
        result = await mgr.wait_for([], {})
        assert result == {}

    @pytest.mark.asyncio
    async def test_already_satisfied(self):
        memory = {"step1": {"output": "data"}}
        mgr = DependencyManager(memory_cache=memory)
        result = await mgr.wait_for(["step1"], memory)
        assert result == {"step1": {"output": "data"}}

    @pytest.mark.asyncio
    async def test_waits_for_dep_to_appear(self):
        """Dep appears in memory after 0.05 s — wait_for should return it."""
        memory: dict = {}
        mgr = DependencyManager(memory_cache=memory)

        async def populate():
            await asyncio.sleep(0.05)
            memory["step1"] = {"result": 42}

        result, _ = await asyncio.gather(
            mgr.wait_for(["step1"], memory, timeout=5.0),
            populate(),
        )
        assert result["step1"] == {"result": 42}

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        """Dep never appears — TimeoutError after short timeout."""
        mgr = DependencyManager()
        with pytest.raises(TimeoutError):
            await mgr.wait_for(["missing"], {}, timeout=0.1)


# ======================================================================
# Redis path (Phase 7C)
# ======================================================================

class TestRedisPath:
    def _store_with_completed_step(self, workflow_id: str, step_id: str, output: Any):
        """Helper: returns a MockRedisContextStore with one completed step."""
        store = MockRedisContextStore()
        store.init_workflow_graph(workflow_id, [{"id": step_id, "depends_on": []}])
        store.update_step_status(workflow_id, step_id, "completed")
        store.save_step_output(workflow_id, step_id, output=output)
        return store

    @pytest.mark.asyncio
    async def test_redis_empty_deps_return_immediately(self):
        store = MockRedisContextStore()
        mgr = DependencyManager(redis_store=store)
        result = await mgr.wait_for([], {}, workflow_id="wf-1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_redis_already_completed(self):
        store = self._store_with_completed_step("wf-1", "step1", {"val": 7})
        mgr = DependencyManager(redis_store=store)
        result = await mgr.wait_for(["step1"], {}, workflow_id="wf-1")
        assert result["step1"]["val"] == 7

    @pytest.mark.asyncio
    async def test_redis_waits_until_completed(self):
        """Dep appears in Redis after 0.05 s — Redis path should detect it."""
        store = MockRedisContextStore()
        store.init_workflow_graph("wf-2", [{"id": "s1", "depends_on": []}])
        mgr = DependencyManager(redis_store=store)

        async def complete_in_redis():
            await asyncio.sleep(0.05)
            store.update_step_status("wf-2", "s1", "completed")
            store.save_step_output("wf-2", "s1", output={"done": True})

        result, _ = await asyncio.gather(
            mgr.wait_for(["s1"], {}, workflow_id="wf-2", timeout=5.0),
            complete_in_redis(),
        )
        assert result["s1"]["done"] is True

    @pytest.mark.asyncio
    async def test_redis_timeout_raises(self):
        """Step never completes in Redis — TimeoutError after short timeout."""
        store = MockRedisContextStore()
        store.init_workflow_graph("wf-3", [{"id": "s1", "depends_on": []}])
        mgr = DependencyManager(redis_store=store)
        with pytest.raises(TimeoutError):
            await mgr.wait_for(["s1"], {}, workflow_id="wf-3", timeout=0.1)

    @pytest.mark.asyncio
    async def test_redis_path_preferred_over_memory(self):
        """When redis_store + workflow_id are given, Redis path is used."""
        store = MockRedisContextStore()
        store.init_workflow_graph("wf-4", [{"id": "s1", "depends_on": []}])
        store.update_step_status("wf-4", "s1", "completed")
        store.save_step_output("wf-4", "s1", output="redis_value")

        # memory dict has stale data — Redis should win
        memory = {"s1": "memory_value"}
        mgr = DependencyManager(memory_cache=memory, redis_store=store)
        result = await mgr.wait_for(["s1"], memory, workflow_id="wf-4")

        # Output is fetched from Redis
        assert result["s1"] == "redis_value"

    @pytest.mark.asyncio
    async def test_falls_back_to_memory_without_workflow_id(self):
        """No workflow_id → fall back to memory path even with redis_store."""
        store = MockRedisContextStore()
        memory = {"s1": "mem_val"}
        mgr = DependencyManager(memory_cache=memory, redis_store=store)
        result = await mgr.wait_for(["s1"], memory)  # no workflow_id
        assert result["s1"] == "mem_val"


# ======================================================================
# check_dependencies (non-blocking)
# ======================================================================

class TestCheckDependencies:
    def test_empty(self):
        mgr = DependencyManager()
        ok, missing = mgr.check_dependencies([], {})
        assert ok is True
        assert missing == []

    def test_all_present(self):
        mgr = DependencyManager()
        ok, missing = mgr.check_dependencies(["a", "b"], {"a": 1, "b": 2})
        assert ok is True

    def test_some_missing(self):
        mgr = DependencyManager()
        ok, missing = mgr.check_dependencies(["a", "b", "c"], {"a": 1})
        assert ok is False
        assert set(missing) == {"b", "c"}


# ======================================================================
# register_waiting / resolve_step
# ======================================================================

class TestWaitingRegistry:
    def test_register_and_get(self):
        mgr = DependencyManager()
        mgr.register_waiting("step2", ["step1"])
        assert mgr.get_waiting_steps() == {"step2": ["step1"]}

    def test_resolve_removes_entry(self):
        mgr = DependencyManager()
        mgr.register_waiting("step2", ["step1"])
        mgr.resolve_step("step2")
        assert "step2" not in mgr.get_waiting_steps()

    def test_resolve_nonexistent_no_error(self):
        mgr = DependencyManager()
        mgr.resolve_step("ghost")  # should not raise
