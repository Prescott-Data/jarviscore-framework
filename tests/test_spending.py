"""Each person's work is charged to them, and a tenant can cap it."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import fakeredis
import pytest

from jarviscore.auth.principal import act_for
from jarviscore.auth.spending import Spending, SpendCapReached, spending_scope
from jarviscore.execution.llm import UnifiedLLMClient
from jarviscore.storage.redis_store import RedisContextStore

ALICE, BOB = "acme/alice", "acme/bob"


@pytest.fixture
def store():
    return RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))


def llm(tokens=100, cost=0.01):
    client = UnifiedLLMClient.__new__(UnifiedLLMClient)
    client.config = {"llm_default_max_tokens": 50}
    client._semaphore = None
    client._generate_inner = AsyncMock(return_value={"content": "ok", "tokens": {"total": tokens},
                                                     "cost_usd": cost})
    return client


class TestTheLedger:

    def test_caps_are_the_tenants_unless_a_person_has_their_own(self, store):
        spending = Spending(store)
        spending.set_caps("acme", tokens_per_day=1000, usd_per_month=20)
        spending.set_caps("acme", person="alice", usd_per_month=50)
        alice, bob = spending.caps_for(ALICE), spending.caps_for(BOB)
        assert (alice.tokens_per_day, alice.usd_per_month) == (1000, 50)
        assert (bob.tokens_per_day, bob.usd_per_month) == (1000, 20)
        assert not spending.caps_for("globex/alice").any()
        spending.set_caps("acme", person="alice", usd_per_month=None)
        assert spending.caps_for(ALICE).usd_per_month == 20

    def test_unknown_caps_are_refused(self, store):
        with pytest.raises(ValueError):
            Spending(store).set_caps("acme", tokens_per_week=5)

    def test_a_call_that_would_go_over_is_refused_before_it_is_made(self, store):
        spending = Spending(store)
        spending.set_caps("acme", tokens_per_day=1000)
        held = spending.reserve(ALICE, 600)
        with pytest.raises(SpendCapReached, match="day"):
            spending.reserve(ALICE, 600)
        spending.settle(ALICE, held, 300, 0.02)
        spending.reserve(ALICE, 600)
        assert spending.usage(ALICE)["day"]["tokens"] == 300
        assert spending.usage(ALICE)["month"]["usd"] == pytest.approx(0.02)

    def test_reservations_from_a_stopped_process_lapse(self, store):
        spending = Spending(store)
        spending.reservation_seconds = 0.05
        spending.set_caps("acme", tokens_per_day=1000)
        spending.reserve(ALICE, 900)       # never settled: its process stopped
        import time
        time.sleep(0.1)
        spending.reserve(ALICE, 900)

    def test_a_dollar_cap(self, store):
        spending = Spending(store)
        spending.set_caps("acme", usd_per_day=1.0)
        spending.settle(ALICE, spending.reserve(ALICE, 10), 10, 1.5)
        with pytest.raises(SpendCapReached, match=r"\$1.50 of \$1.00"):
            spending.check(ALICE)
        with pytest.raises(SpendCapReached):
            spending.reserve(ALICE, 10)
        spending.check(BOB)

    async def test_many_calls_at_once_never_overshoot(self, store):
        spending = Spending(store)
        spending.set_caps("acme", tokens_per_day=1000)

        async def call():
            try:
                rid = spending.reserve(ALICE, 100)
            except SpendCapReached:
                return False
            await asyncio.sleep(0.01)
            spending.settle(ALICE, rid, 100, 0.0)
            return True

        made = await asyncio.gather(*(call() for _ in range(40)))
        assert sum(made) == 10
        assert spending.usage(ALICE)["day"]["tokens"] == 1000


class TestModelCalls:

    async def test_a_call_made_for_someone_is_charged_to_them(self, store):
        with act_for(ALICE), spending_scope(store):
            await llm(tokens=120, cost=0.03).generate("hello")
        used = Spending(store).usage(ALICE)["day"]
        assert (used["tokens"], used["calls"], used["usd"]) == (120, 1, pytest.approx(0.03))
        assert Spending(store).usage(BOB)["day"]["tokens"] == 0

    async def test_outside_a_scope_or_for_nobody_nothing_is_charged(self, store):
        await llm().generate("hello")
        with spending_scope(store):
            await llm().generate("hello")
        with act_for(ALICE):
            await llm().generate("hello")
        assert Spending(store).usage(ALICE)["day"]["calls"] == 0

    async def test_over_the_cap_the_call_is_not_made(self, store):
        Spending(store).set_caps("acme", tokens_per_day=10)
        client = llm()
        with act_for(ALICE), spending_scope(store):
            with pytest.raises(SpendCapReached):
                await client.generate("hello")
        client._generate_inner.assert_not_awaited()

    async def test_a_failed_call_charges_nothing_and_holds_nothing(self, store):
        Spending(store).set_caps("acme", tokens_per_day=10_000)
        client = llm()
        client._generate_inner = AsyncMock(side_effect=RuntimeError("provider down"))
        with act_for(ALICE), spending_scope(store), pytest.raises(RuntimeError):
            await client.generate("hello")
        assert Spending(store).usage(ALICE)["day"]["tokens"] == 0
        assert store._redis.hlen(store._spend_key(ALICE, "reservations")) == 0


class TestInARoom:

    async def test_asking_over_the_cap_is_refused_with_when_it_renews(self, tmp_path, store):
        from jarviscore.room import Person, Room
        from jarviscore.storage.local import LocalBlobStorage

        alice = Person("acme", "alice", "Alice")
        room = Room("launch", tenant="acme", blob_storage=LocalBlobStorage(str(tmp_path)), redis_store=store)
        await room.ensure({"plan.md": "# Plan\n"}, by=alice)
        Spending(store).set_caps("acme", tokens_per_day=100)
        Spending(store).settle(ALICE, Spending(store).reserve(ALICE, 100), 100, 0.0)
        room.mesh = object()
        with pytest.raises(SpendCapReached, match="midnight UTC"):
            await room.ask("anything", asked_by=alice)
        assert [e["type"] for e in room.events()] == ["room.created"], "nothing started"


async def test_work_that_reaches_the_cap_stops_and_says_why(tmp_path, monkeypatch):
    """A real mesh: a step whose model calls go over the asker's cap fails with the reason."""
    from jarviscore import Mesh
    from jarviscore.profiles import CustomAgent
    from jarviscore.room import Person, Room
    from jarviscore.storage.local import LocalBlobStorage

    redis = RedisContextStore(client=fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: redis)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: LocalBlobStorage(str(tmp_path)))
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    monkeypatch.delenv("NEXUS_GATEWAY_URL", raising=False)

    class Talker(CustomAgent):
        role = "talker"
        capabilities = ["talking"]
        calls = 0

        async def execute_task(self, task):
            client = llm(tokens=400)
            for _ in range(5):
                await client.generate("think")
                Talker.calls += 1
            (Path(task["context"]["workspace_binding"]["path"]) / "plan.md").write_text("talked\n")
            return {"status": "success", "output": "done"}

    mesh = Mesh(config={"p2p_enabled": False, "distributed_poll_interval": 0.02})
    mesh.add(Talker)
    await mesh.start()
    try:
        alice = Person("acme", "alice", "Alice")
        room = Room.for_mesh(mesh, "launch", tenant="acme")
        await room.ensure({"plan.md": "# Plan\n"}, by=alice)
        Spending(redis).set_caps("acme", tokens_per_day=1000)
        plan = {"obligations": [{"id": "o1", "description": "talk", "source_quote": "talk"}],
                "steps": [{"id": "t", "capability": "talking", "effect": "propose", "systems": [],
                           "task": "talk", "success_criterion": "done", "expected_findings": ["done"],
                           "depends_on": [], "covers": ["o1"]}]}
        asked = await room.ask("talk a lot", asked_by=alice, timeout=20, plan_template=plan)
        assert asked.status == "failed" and asked.proposal is None
        # Each call reserves what it may use; the fourth no longer fits under the cap.
        assert Talker.calls == 3, "stopped at the first call that would have gone over"
        assert Spending(redis).usage(ALICE)["day"]["tokens"] == 1200
    finally:
        await mesh.stop()


async def test_someone_over_their_cap_is_told_so_in_the_conversation(tmp_path, store):
    from jarviscore.room import Person, Room, RoomAgent

    alice = Person("acme", "alice", "Alice")
    room = Room("launch", tenant="acme", blob_storage=__import__("jarviscore.storage.local", fromlist=["x"])
                .LocalBlobStorage(str(tmp_path)), redis_store=store)
    await room.ensure({"plan.md": "# Plan\n"}, by=alice)
    Spending(store).set_caps("acme", usd_per_day=1.0)
    Spending(store).settle(ALICE, Spending(store).reserve(ALICE, 10), 10, 2.0)

    class NoModel(RoomAgent):
        async def execute_task(self, task):
            raise AssertionError("no model call over the cap")

    turn = await NoModel().converse(room, alice, "draft the plan")
    assert turn.private and "allowance for work done for Alice is used up" in turn.replies[0]
    assert "midnight UTC" in turn.replies[0]
