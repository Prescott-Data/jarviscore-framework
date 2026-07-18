"""
Tests for issue #52: mesh.fanout() — dynamic fan-out with explicit aggregation.

What these tests prove:
- N runtime items execute against one agent with results in ITEM ORDER
- Every result is stamped with item + step_id (namespaced identity — the
  #53 contamination class is impossible by construction)
- Concurrency is genuinely bounded
- Budget caps attempted items and reports the remainder honestly
- Partial failure is first-class: .failed carries per-item errors, the
  rest complete; fail_fast cancels pending items
- Per-item timeout produces an honest per-item error
- aggregate() reduces successes deterministically; summarize() builds an
  honest evidence window (markers on clipped items, failures listed)
- mesh.fanout() refuses to run before mesh.start()
"""

import asyncio
from typing import Any, Dict

import pytest

from jarviscore import Mesh, MeshMode
from jarviscore.core.agent import Agent
from jarviscore.orchestration.fanout import FanoutResult, run_fanout


# ── Agents ────────────────────────────────────────────────────────────────────

class AnalystAgent(Agent):
    role = "analyst"
    capabilities = ["analysis"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        ctx = task.get("context", {})
        return {"status": "success", "payload": {"read": ctx.get("fanout_item")}}


class FlakyAgent(Agent):
    role = "flaky"
    capabilities = ["flaky"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        item = task.get("context", {}).get("fanout_item")
        if item == "bad":
            raise RuntimeError("boom on bad item")
        return {"status": "success", "payload": item}


class ConcurrencyProbe(Agent):
    role = "probe"
    capabilities = ["probe"]
    in_flight = 0
    max_seen = 0

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        cls = type(self)
        cls.in_flight += 1
        cls.max_seen = max(cls.max_seen, cls.in_flight)
        await asyncio.sleep(0.05)
        cls.in_flight -= 1
        return {"status": "success", "payload": "ok"}


class SlowAgent(Agent):
    role = "slow"
    capabilities = ["slow"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(5)
        return {"status": "success"}


async def _with_mesh(agent_cls, coro_fn):
    mesh = Mesh(mode=MeshMode.AUTONOMOUS)
    mesh.add(agent_cls)
    await mesh.start()
    try:
        return await coro_fn(mesh)
    finally:
        await mesh.stop()


# ── Core behavior ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestFanoutCore:

    async def test_results_in_item_order_with_identity(self):
        symbols = ["EURUSD", "XAUUSD", "JP225"]

        async def run(mesh):
            return await mesh.fanout(
                "scan-1", agent="analyst", items=symbols,
                task=lambda s: f"Read {s}", context=lambda s: {"symbol": s},
            )

        result = await _with_mesh(AnalystAgent, run)

        assert [r["item"] for r in result.results] == symbols
        assert [r["payload"]["read"] for r in result.results] == symbols
        assert all(r["status"] == "success" for r in result.results)
        # Namespaced identity: unique step ids under the fanout id
        step_ids = [r["step_id"] for r in result.results]
        assert len(set(step_ids)) == 3
        assert all(sid.startswith("scan-1:") for sid in step_ids)

    async def test_static_task_and_context(self):
        async def run(mesh):
            return await mesh.fanout(
                "scan-2", agent="analyst", items=["a", "b"],
                task="Read the item in context", context={"static": True},
            )

        result = await _with_mesh(AnalystAgent, run)
        assert len(result.succeeded) == 2

    async def test_fanout_before_start_is_a_loud_error(self):
        mesh = Mesh(mode=MeshMode.AUTONOMOUS)
        mesh.add(AnalystAgent)
        with pytest.raises(RuntimeError, match="mesh.start"):
            await mesh.fanout("x", agent="analyst", items=["a"], task="t")


@pytest.mark.asyncio
class TestBoundsAndBudget:

    async def test_concurrency_is_bounded(self):
        ConcurrencyProbe.in_flight = 0
        ConcurrencyProbe.max_seen = 0

        async def run(mesh):
            return await mesh.fanout(
                "probe-1", agent="probe", items=list(range(12)),
                task="go", concurrency=3,
            )

        result = await _with_mesh(ConcurrencyProbe, run)
        assert len(result.succeeded) == 12
        assert ConcurrencyProbe.max_seen <= 3

    async def test_budget_skips_honestly(self):
        async def run(mesh):
            return await mesh.fanout(
                "scan-3", agent="analyst", items=["a", "b", "c", "d", "e"],
                task="read", budget=2,
            )

        result = await _with_mesh(AnalystAgent, run)
        assert len(result.results) == 2
        assert result.skipped == ["c", "d", "e"]

    async def test_per_item_timeout_is_an_honest_error(self):
        async def run(mesh):
            return await mesh.fanout(
                "slow-1", agent="slow", items=["x"], task="go", timeout=0.05,
            )

        result = await _with_mesh(SlowAgent, run)
        assert len(result.failed) == 1
        assert "timed out" in result.failed[0]["error"]


@pytest.mark.asyncio
class TestPartialFailure:

    async def test_collect_mode_keeps_the_rest(self):
        async def run(mesh):
            return await mesh.fanout(
                "flaky-1", agent="flaky", items=["good1", "bad", "good2"],
                task="go",
            )

        result = await _with_mesh(FlakyAgent, run)
        assert [r["item"] for r in result.succeeded] == ["good1", "good2"]
        assert len(result.failed) == 1
        assert result.failed[0]["item"] == "bad"
        assert "boom on bad item" in result.failed[0]["error"]

    async def test_fail_fast_cancels_pending(self):
        items = ["bad"] + [f"g{i}" for i in range(10)]

        async def run(mesh):
            return await mesh.fanout(
                "flaky-2", agent="flaky", items=items,
                task="go", concurrency=1, on_error="fail_fast",
            )

        result = await _with_mesh(FlakyAgent, run)
        cancelled = [r for r in result.failed if "cancelled" in r.get("error", "")]
        assert len(cancelled) >= 1  # pending items were not run

    async def test_unknown_agent_is_a_per_item_error(self):
        async def run(mesh):
            return await mesh.fanout(
                "ghost-1", agent="nonexistent", items=["a"], task="go",
            )

        result = await _with_mesh(AnalystAgent, run)
        assert "No agent found" in result.failed[0]["error"]


# ── Aggregation ───────────────────────────────────────────────────────────────

class TestAggregation:

    def _made(self):
        return FanoutResult(
            fanout_id="f",
            results=[
                {"item": "a", "step_id": "f:0000-a", "status": "success", "payload": 1},
                {"item": "b", "step_id": "f:0001-b", "status": "failure", "error": "x"},
                {"item": "c", "step_id": "f:0002-c", "status": "success", "payload": 2},
            ],
            skipped=["d"],
        )

    def test_aggregate_reduces_successes(self):
        total = self._made().aggregate(lambda rs: sum(r["payload"] for r in rs))
        assert total == 3

    @pytest.mark.asyncio
    async def test_summarize_builds_an_honest_evidence_window(self):
        captured = {}

        class _LLM:
            async def generate(self, messages):
                captured["prompt"] = messages[0]["content"]
                return {"content": "the summary"}

        result = FanoutResult(
            fanout_id="f",
            results=[
                {"item": "a", "step_id": "f:0", "status": "success", "payload": "Z" * 2000},
                {"item": "b", "step_id": "f:1", "status": "failure", "error": "broke"},
            ],
            skipped=["c"],
        )
        out = await result.summarize(_LLM(), "Synthesize the board read.")
        assert out == "the summary"
        prompt = captured["prompt"]
        assert "…[truncated: showing 800 of 2000 chars]" in prompt  # honest clip
        assert "b: FAILED — broke" in prompt                        # failures visible
        assert "skipped by budget" in prompt                        # skips visible

    def test_run_fanout_validates_inputs(self):
        with pytest.raises(ValueError, match="concurrency"):
            asyncio.get_event_loop().run_until_complete(
                run_fanout(
                    fanout_id="f", find_agent=lambda s: None, agent="a",
                    items=[], task="t", concurrency=0,
                )
            )
