"""
Tests for Phase 8D: UnifiedMemory.

What these tests prove:
- log_turn() writes to both scratchpad and episodic ledger
- save_checkpoint() / load_checkpoint() round-trip via Redis
- rehydrate_bundle() assembles all tiers into one dict
- Graceful degradation: no-ops when stores are None
- Tier availability flags match constructor args
"""
import pytest

from jarviscore.memory.unified import UnifiedMemory
from jarviscore.testing import MockRedisContextStore, MockBlobStorage


@pytest.fixture
def store():
    return MockRedisContextStore()


@pytest.fixture
def blob():
    return MockBlobStorage()


@pytest.fixture
def mem(store, blob):
    return UnifiedMemory("wf-1", "step1", "analyst", store, blob)


@pytest.fixture
def mem_no_blob(store):
    return UnifiedMemory("wf-1", "step1", "analyst", store, None)


@pytest.fixture
def mem_no_redis(blob):
    return UnifiedMemory("wf-1", "step1", "analyst", None, blob)


@pytest.fixture
def mem_bare():
    return UnifiedMemory("wf-1", "step1", "analyst", None, None)


# ======================================================================
# Tier availability
# ======================================================================

class TestTierAvailability:
    def test_all_tiers_active_with_both_stores(self, mem):
        assert mem.working is not None
        assert mem.episodic is not None
        assert mem.ltm is not None

    def test_no_blob_disables_scratchpad_and_ltm(self, mem_no_blob):
        assert mem_no_blob.working is None
        assert mem_no_blob.episodic is not None
        assert mem_no_blob.ltm is None

    def test_no_redis_disables_episodic_and_ltm(self, mem_no_redis):
        assert mem_no_redis.working is not None
        assert mem_no_redis.episodic is None
        assert mem_no_redis.ltm is None

    def test_no_stores_all_tiers_none(self, mem_bare):
        assert mem_bare.working is None
        assert mem_bare.episodic is None
        assert mem_bare.ltm is None


# ======================================================================
# log_turn()
# ======================================================================

class TestLogTurn:
    @pytest.mark.asyncio
    async def test_log_turn_writes_to_scratchpad(self, mem, blob):
        await mem.log_turn("t1", "thinking", "search", "found 10 results")
        entries = await mem.working.read_all()
        assert len(entries) == 1
        assert entries[0]["turn_id"] == "t1"

    @pytest.mark.asyncio
    async def test_log_turn_writes_to_episodic(self, mem, store):
        await mem.log_turn("t1", "thinking", "search", "results")
        history = await mem.episodic.full_history()
        assert len(history) == 1
        assert history[0]["turn_id"] == "t1"

    @pytest.mark.asyncio
    async def test_log_turn_no_blob_skips_scratchpad(self, mem_no_blob):
        # Should not raise
        await mem_no_blob.log_turn("t1", "thinking", "search", "results")
        history = await mem_no_blob.episodic.full_history()
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_log_turn_bare_no_error(self, mem_bare):
        # All tiers None — should be a clean no-op
        await mem_bare.log_turn("t1", "thinking", "search", "results")


# ======================================================================
# save_checkpoint() / load_checkpoint()
# ======================================================================

class TestCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_roundtrip(self, mem):
        state = '{"turn": 3, "plan": "step 2 next"}'
        await mem.save_checkpoint(state)
        loaded = await mem.load_checkpoint()
        assert loaded == state

    @pytest.mark.asyncio
    async def test_load_checkpoint_returns_none_when_empty(self, mem):
        result = await mem.load_checkpoint()
        assert result is None

    @pytest.mark.asyncio
    async def test_checkpoint_no_redis_no_error(self, mem_bare):
        await mem_bare.save_checkpoint('{"x": 1}')
        result = await mem_bare.load_checkpoint()
        assert result is None


# ======================================================================
# rehydrate_bundle()
# ======================================================================

class TestRehydrateBundle:
    @pytest.mark.asyncio
    async def test_bundle_has_all_keys(self, mem):
        bundle = await mem.rehydrate_bundle()
        assert "ltm_summary" in bundle
        assert "recent_turns" in bundle
        assert "checkpoint" in bundle
        assert "scratchpad" in bundle

    @pytest.mark.asyncio
    async def test_bundle_empty_when_nothing_stored(self, mem):
        bundle = await mem.rehydrate_bundle()
        assert bundle["ltm_summary"] is None
        assert bundle["recent_turns"] == []
        assert bundle["checkpoint"] is None
        assert bundle["scratchpad"] == ""

    @pytest.mark.asyncio
    async def test_bundle_assembles_all_tiers(self, mem):
        # Populate all tiers
        await mem.log_turn("t1", "reasoning", "tool_call", "result")
        await mem.save_checkpoint('{"state": "ok"}')
        await mem.ltm.save_summary("Prior: processed 100 records")

        bundle = await mem.rehydrate_bundle(ledger_tail=5)

        assert len(bundle["recent_turns"]) == 1
        assert bundle["checkpoint"] == '{"state": "ok"}'
        assert "100 records" in bundle["ltm_summary"]
        assert bundle["scratchpad"] != ""

    @pytest.mark.asyncio
    async def test_bundle_bare_mode_no_error(self, mem_bare):
        bundle = await mem_bare.rehydrate_bundle()
        assert bundle["ltm_summary"] is None
        assert bundle["recent_turns"] == []
