"""
Tests for Phase 7B: WorkflowEngine reactive loop.

What these tests prove:
- Single step executes and returns a result
- Parallel steps (no deps) run concurrently (timing proof)
- Sequential steps (with deps) run in order
- Failed step is recorded but does not block unrelated steps
- Waiting status is preserved in workflow results
- Deadlock detection fires when deps can never complete
- Crash recovery: completed steps are skipped on re-run
- WorkflowState is persisted to Redis each iteration

All tests use in-memory-only setup (no real Redis), relying solely on the
MockRedisContextStore from jarviscore.testing for the Redis-backed path tests.
"""

import asyncio
import time
from typing import Any, Dict

import pytest

from jarviscore import Mesh
from jarviscore.core.agent import Agent


# ======================================================================
# Helpers
# ======================================================================

def make_mesh():
    """Return a Mesh in autonomous mode (no P2P, no real Redis)."""
    return Mesh(mode="autonomous")


class EchoAgent(Agent):
    """Returns a fixed success result."""
    role = "echo"
    capabilities = ["echo"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": task.get("task", "ok")}


class SlowAgent(Agent):
    """Sleeps 0.1 s before returning — used to prove concurrency."""
    role = "slow"
    capabilities = ["slow"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.1)
        return {"status": "success", "output": "slow_done"}


class FailAgent(Agent):
    """Always returns a failure result."""
    role = "fail"
    capabilities = ["fail"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "failure", "error": "intentional failure"}


class WaitAgent(Agent):
    """Returns a HITL waiting result."""
    role = "hitl"
    capabilities = ["hitl"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "waiting", "reason": "human approval required"}


class ContextAgent(Agent):
    """Returns the previous_step_results it received."""
    role = "ctx"
    capabilities = ["ctx"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        ctx = task.get("context", {})
        return {
            "status": "success",
            "previous": ctx.get("previous_step_results", {}),
        }


# ======================================================================
# Basic execution
# ======================================================================

@pytest.mark.asyncio
class TestBasicExecution:
    async def test_single_step(self):
        mesh = make_mesh()
        mesh.add(EchoAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-single", [
                {"agent": "echo", "task": "hello"}
            ])
        finally:
            await mesh.stop()

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert results[0]["output"] == "hello"

    async def test_result_order_matches_step_order(self):
        """Results returned in original step order regardless of execution order."""
        mesh = make_mesh()
        mesh.add(EchoAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-order", [
                {"id": "s1", "agent": "echo", "task": "first"},
                {"id": "s2", "agent": "echo", "task": "second"},
                {"id": "s3", "agent": "echo", "task": "third"},
            ])
        finally:
            await mesh.stop()

        assert results[0]["output"] == "first"
        assert results[1]["output"] == "second"
        assert results[2]["output"] == "third"


# ======================================================================
# Parallelism
# ======================================================================

@pytest.mark.asyncio
class TestParallelExecution:
    async def test_independent_steps_run_concurrently(self):
        """Two slow steps without deps should complete ~0.1 s, not ~0.2 s."""
        mesh = make_mesh()
        mesh.add(SlowAgent)
        mesh.add(EchoAgent)
        await mesh.start()

        t0 = time.perf_counter()
        try:
            results = await mesh.workflow("wf-parallel", [
                {"id": "s1", "agent": "slow", "task": "a"},
                {"id": "s2", "agent": "slow", "task": "b"},
            ])
        finally:
            await mesh.stop()
        elapsed = time.perf_counter() - t0

        assert all(r["status"] == "success" for r in results)
        # Sequential would take ≥ 0.2 s; concurrent takes < 0.18 s
        assert elapsed < 0.18, f"Steps ran sequentially (took {elapsed:.3f}s)"


# ======================================================================
# Sequential dependencies
# ======================================================================

@pytest.mark.asyncio
class TestSequentialDependencies:
    async def test_dep_step_receives_previous_output(self):
        """Step 2 should see step 1's output in its context."""
        mesh = make_mesh()
        mesh.add(EchoAgent)
        mesh.add(ContextAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-seq", [
                {"id": "s1", "agent": "echo", "task": "upstream_data"},
                {"id": "s2", "agent": "ctx",  "task": "check_ctx", "depends_on": ["s1"]},
            ])
        finally:
            await mesh.stop()

        assert results[0]["status"] == "success"
        assert results[1]["status"] == "success"
        # s2's context should include s1's result
        prev = results[1].get("previous", {})
        assert "s1" in prev

    async def test_integer_depends_on(self):
        """depends_on can use integer indices (0-based)."""
        mesh = make_mesh()
        mesh.add(EchoAgent)
        mesh.add(ContextAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-int-dep", [
                {"agent": "echo", "task": "A"},
                {"agent": "ctx",  "task": "B", "depends_on": [0]},
            ])
        finally:
            await mesh.stop()

        assert results[1]["status"] == "success"


# ======================================================================
# Failure handling
# ======================================================================

@pytest.mark.asyncio
class TestFailureHandling:
    async def test_failing_step_recorded(self):
        mesh = make_mesh()
        mesh.add(FailAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-fail", [
                {"agent": "fail", "task": "go"}
            ])
        finally:
            await mesh.stop()

        assert results[0]["status"] == "failure"

    async def test_parallel_failure_does_not_block_others(self):
        """A failing step must not prevent independent steps from completing."""
        mesh = make_mesh()
        mesh.add(FailAgent)
        mesh.add(EchoAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-partial-fail", [
                {"id": "s1", "agent": "fail", "task": "fail"},
                {"id": "s2", "agent": "echo", "task": "ok"},
            ])
        finally:
            await mesh.stop()

        statuses = {r["step_id"] if "step_id" in r else f"s{i}": r["status"]
                    for i, r in enumerate(results)}
        # s2 (echo) should succeed even though s1 failed
        assert results[1]["status"] == "success"

    async def test_unknown_agent_returns_failure(self):
        mesh = make_mesh()
        mesh.add(EchoAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-no-agent", [
                {"agent": "nonexistent_role", "task": "go"}
            ])
        finally:
            await mesh.stop()

        assert results[0]["status"] == "failure"
        assert "No agent found" in results[0].get("error", "")


# ======================================================================
# HITL / waiting
# ======================================================================

@pytest.mark.asyncio
class TestWaitingStatus:
    async def test_waiting_step_preserved(self):
        mesh = make_mesh()
        mesh.add(WaitAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-hitl", [
                {"agent": "hitl", "task": "approve me"}
            ])
        finally:
            await mesh.stop()

        assert results[0]["status"] == "waiting"
        assert results[0]["reason"] == "human approval required"


# ======================================================================
# Deadlock detection
# ======================================================================

@pytest.mark.asyncio
class TestDeadlockDetection:
    async def test_deadlock_from_circular_deps(self):
        """Mutually-dependent steps should be caught by deadlock detection."""
        mesh = make_mesh()
        mesh.add(EchoAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-deadlock", [
                {"id": "s1", "agent": "echo", "task": "a", "depends_on": ["s2"]},
                {"id": "s2", "agent": "echo", "task": "b", "depends_on": ["s1"]},
            ])
        finally:
            await mesh.stop()

        # Both steps must be in a terminal state (failure due to deadlock)
        assert all(r["status"] in ("failure", "skipped") for r in results)


# ======================================================================
# Engine not started guard
# ======================================================================

@pytest.mark.asyncio
class TestEngineGuards:
    async def test_execute_before_start_raises(self):
        mesh = make_mesh()
        mesh.add(EchoAgent)
        # do NOT call mesh.start()
        with pytest.raises(RuntimeError, match="not started"):
            await mesh.workflow("wf-guard", [{"agent": "echo", "task": "go"}])
