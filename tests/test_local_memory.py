"""Tests for LocalMemory: the zero-infrastructure tier-4 backend."""

import asyncio

import pytest

from jarviscore.memory.local_memory import LocalMemory


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "memory.db")


def test_session_survives_restart(db):
    async def scenario():
        first = await LocalMemory.create("researcher", db_path=db)
        await first.record_thought("btc looked bearish on H4")
        # simulate a process restart: brand-new instance, same file
        second = await LocalMemory.create("researcher", db_path=db)
        assert second.session_id == first.session_id
        ctx = await second.get_memory_context()
        return ctx

    ctx = _run(scenario())
    assert len(ctx["stm_events"]) == 1
    assert "bearish" in ctx["stm_events"][0]["content"]
    assert ctx["mtm_chains"] == []          # consolidation is Athena's job


def test_agents_get_isolated_sessions(db):
    async def scenario():
        a = await LocalMemory.create("scout", db_path=db)
        b = await LocalMemory.create("analyst", db_path=db)
        await a.record_action("scouted example.com")
        return a, b, await b.get_memory_context()

    a, b, b_ctx = _run(scenario())
    assert a.session_id != b.session_id
    assert b_ctx["stm_events"] == []


def test_event_types_and_order(db):
    async def scenario():
        m = await LocalMemory.create("worker", db_path=db)
        await m.record_thought("plan the report")
        await m.record_action("wrote section one")
        await m.record_observation("section one approved")
        return await m.get_memory_context()

    ctx = _run(scenario())
    types = [e["type"] for e in ctx["stm_events"]]
    assert types == ["thought", "action", "observation"]   # chronological


def test_search_is_keyword_ranked_and_labeled(db):
    async def scenario():
        m = await LocalMemory.create("worker", db_path=db)
        await m.record_thought("vector databases comparison for retrieval")
        await m.record_thought("lunch options near the office")
        return await m.search("vector retrieval comparison")

    results = _run(scenario())
    assert results
    assert "vector" in results[0]["content"]
    assert results[0]["match_type"] == "keyword"    # honest about not being semantic
    assert 0 < results[0]["similarity_score"] <= 1


def test_unified_memory_falls_back_to_local(tmp_path, monkeypatch):
    from jarviscore.memory.unified import UnifiedMemory

    monkeypatch.setenv("JARVISCORE_MEMORY_PATH", str(tmp_path / "m.db"))
    um = UnifiedMemory(
        workflow_id="wf", step_id="s1", agent_id="researcher",
        redis_store=None, blob_storage=None, athena_client=None,
    )
    tier4 = _run(um._get_athena_memory())
    assert tier4 is not None
    assert type(tier4).__name__ == "LocalMemory"


def test_tier4_off_switch(monkeypatch):
    from jarviscore.memory.unified import UnifiedMemory

    monkeypatch.setenv("JARVISCORE_MEMORY_PATH", "off")
    um = UnifiedMemory(
        workflow_id="wf", step_id="s1", agent_id="researcher",
        redis_store=None, blob_storage=None, athena_client=None,
    )
    assert _run(um._get_athena_memory()) is None
