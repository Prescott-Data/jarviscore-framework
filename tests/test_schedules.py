"""Durable schedules and event triggers start and wake goals."""

import asyncio
import json
import time

import pytest

from jarviscore import Mesh
from jarviscore.orchestration.schedules import DUE, ScheduleBook
from jarviscore.testing import MockLLMClient, MockRedisContextStore

from test_mesh_goal import AnalysisPeer, WaitingResearchPeer, goal_responses


class _Clock:
    def __init__(self, now=1_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def redis_client():
    return MockRedisContextStore()._redis


def _goal(text="Check my inbox", **context):
    return {"kind": "goal", "goal": text, "context": context}


def test_a_one_time_goal_fires_once_at_its_moment(redis_client):
    clock = _Clock()
    book = ScheduleBook(redis_client, clock)
    schedule_id = book.add(_goal(owner_id="ada"), at=1_100.0)

    assert book.claim_due() == []
    clock.now = 1_100.0
    [firing] = book.claim_due()

    assert firing.schedule_id == schedule_id
    assert firing.context == {"owner_id": "ada"}
    assert firing.workflow_id == f"{schedule_id}-1100"
    assert book.claim_due() == [] and book.get(schedule_id) is None


def test_an_interval_keeps_its_rhythm(redis_client):
    clock = _Clock()
    book = ScheduleBook(redis_client, clock)
    schedule_id = book.add(_goal(), every_seconds=60)

    clock.now = 1_061.0
    [first] = book.claim_due()
    assert first.occurrence == "1060"
    assert redis_client.zscore(DUE, schedule_id) == 1_120.0


def test_missed_moments_coalesce_into_one_run(redis_client):
    clock = _Clock()
    book = ScheduleBook(redis_client, clock)
    schedule_id = book.add(_goal(), every_seconds=60)

    clock.now = 1_000.0 + 60 * 10 + 5
    assert len(book.claim_due()) == 1
    assert redis_client.zscore(DUE, schedule_id) == clock.now + 60
    assert book.get(schedule_id)["fired"] == 1


def test_two_nodes_never_fire_the_same_occurrence(redis_client):
    clock = _Clock()
    first, second = ScheduleBook(redis_client, clock), ScheduleBook(redis_client, clock)
    first.add(_goal(), at=1_000.0)

    assert len(first.claim_due()) + len(second.claim_due()) == 1


def test_an_event_carries_its_payload_and_identity(redis_client):
    book = ScheduleBook(redis_client, _Clock())
    schedule_id = book.add(_goal(owner_id="ada"), event="email.received")

    [firing] = book.for_event("email.received", "msg-7", {"from": "bank"})

    assert firing.workflow_id == f"{schedule_id}-event-msg-7"
    assert firing.context["owner_id"] == "ada"
    assert firing.context["event"] == {"name": "email.received", "id": "msg-7", "payload": {"from": "bank"}}
    assert book.for_event("calendar.changed", "x") == []


def test_cancelled_schedules_never_fire(redis_client):
    clock = _Clock()
    book = ScheduleBook(redis_client, clock)
    timed = book.add(_goal(), at=1_000.0)
    evented = book.add(_goal(), event="email.received")

    assert book.cancel(timed) and book.cancel(evented)
    assert book.claim_due() == [] and book.for_event("email.received", "1") == []
    assert not book.cancel(timed)


@pytest.mark.parametrize("action,kwargs", [
    (_goal(""), {"at": 1.0}),
    ({"kind": "wake", "workflow_id": "wf"}, {"at": 1.0}),
    ({"kind": "email"}, {"at": 1.0}),
    (_goal(), {}),
    (_goal(), {"at": 1.0, "event": "e"}),
    (_goal(), {"every_seconds": 0}),
    ({"kind": "wake", "workflow_id": "wf", "step_id": "s"}, {"every_seconds": 60}),
])
def test_malformed_schedules_are_refused(redis_client, action, kwargs):
    with pytest.raises(ValueError):
        ScheduleBook(redis_client, _Clock()).add(action, **kwargs)


def _mesh(monkeypatch, store, *agents):
    monkeypatch.setattr(Mesh, "_init_redis", lambda self, settings: store)
    monkeypatch.setattr(Mesh, "_init_blob_storage", lambda self, settings: None)
    monkeypatch.setattr(Mesh, "_init_nexus", lambda self: None)
    monkeypatch.setattr(Mesh, "_init_athena", lambda self, settings: None)
    mesh = Mesh(config={
        "p2p_enabled": False,
        "distributed_poll_interval": 0.01,
        "schedule_poll_seconds": 0.01,
    })
    for agent in agents:
        mesh.add(agent)
    return mesh


async def _until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.mark.asyncio
async def test_a_waiting_step_wakes_at_its_moment(monkeypatch):
    store = MockRedisContextStore()
    waiting = WaitingResearchPeer(MockLLMClient(responses=goal_responses()), agent_id="researcher-1")
    mesh = _mesh(monkeypatch, store, waiting, AnalysisPeer(agent_id="analyst-1"))

    await mesh.start()
    try:
        first = await mesh.execute_goal("Find evidence and analyse it", workflow_id="wf-follow-up", timeout=1)
        mesh.schedule_wake("wf-follow-up", "research", at=time.time(), context={"follow_up": "three days later"})
        woke = await _until(lambda: len(waiting.received) == 2)
    finally:
        await mesh.stop()

    assert first["status"] == "waiting"
    assert woke
    resumed = waiting.received[1]["context"]
    assert resumed["_resume"] is True
    assert resumed["follow_up"] == "three days later"
    assert resumed["schedule"]["occurrence"]


@pytest.mark.asyncio
async def test_an_event_starts_its_goal_once(monkeypatch):
    store = MockRedisContextStore()
    mesh = _mesh(monkeypatch, store, AnalysisPeer(agent_id="analyst-1"))

    await mesh.start()
    try:
        mesh.schedule_goal("Triage the new email", event="email.received", context={"owner_id": "ada"})
        first = await mesh.emit_event("email.received", {"subject": "Invoice"}, event_id="msg-1")
        again = await mesh.emit_event("email.received", {"subject": "Invoice"}, event_id="msg-1")
    finally:
        await mesh.stop()

    assert first == again and len(first) == 1
    registered = json.loads(store._redis.get(f"workflow_goal:{first[0]}"))
    assert registered["goal"] == "Triage the new email"
    assert registered["context"]["owner_id"] == "ada"
    assert registered["context"]["event"]["payload"] == {"subject": "Invoice"}
    assert store._redis.scard("jarviscore:pending_goal_plans") == 1
