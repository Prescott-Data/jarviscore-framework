"""
Tests for Phase 8C: LongTermMemory.

What these tests prove:
- save_summary() writes to both Redis and Blob
- load_summary() prefers Redis (hot path)
- load_summary() falls back to Blob when Redis returns None
- load_summary() returns None when neither tier has data
- Blob fallback rehydrates Redis cache
- compress() calls llm_client.generate() and returns its content
- compress() returns "" for empty entry list
"""
from unittest.mock import AsyncMock, MagicMock
import pytest

from jarviscore.memory.ltm import LongTermMemory
from jarviscore.testing import MockRedisContextStore, MockBlobStorage


@pytest.fixture
def store():
    return MockRedisContextStore()


@pytest.fixture
def blob():
    return MockBlobStorage()


@pytest.fixture
def ltm(store, blob):
    return LongTermMemory(store, blob, "wf-1")


# ======================================================================
# save_summary() + load_summary()
# ======================================================================

class TestSaveLoad:
    @pytest.mark.asyncio
    async def test_save_then_load_roundtrip(self, ltm):
        await ltm.save_summary("This workflow processed 500 records.")
        result = await ltm.load_summary()
        assert result == "This workflow processed 500 records."

    @pytest.mark.asyncio
    async def test_save_writes_to_redis(self, ltm, store):
        await ltm.save_summary("cached summary")
        assert store.load_ltm("wf-1") == "cached summary"

    @pytest.mark.asyncio
    async def test_save_writes_to_blob(self, ltm, blob):
        await ltm.save_summary("durable summary")
        raw = await blob.read("workflows/wf-1/ltm/summary.txt")
        assert raw == "durable summary"

    @pytest.mark.asyncio
    async def test_load_returns_none_when_empty(self, ltm):
        result = await ltm.load_summary()
        assert result is None


class TestLoadFallback:
    @pytest.mark.asyncio
    async def test_prefers_redis_over_blob(self, store, blob):
        # Put different values in each tier
        store.save_ltm("wf-2", "redis value")
        await blob.save("workflows/wf-2/ltm/summary.txt", "blob value")

        ltm = LongTermMemory(store, blob, "wf-2")
        result = await ltm.load_summary()
        assert result == "redis value"

    @pytest.mark.asyncio
    async def test_falls_back_to_blob_when_redis_empty(self, store, blob):
        # Only blob has data
        await blob.save("workflows/wf-3/ltm/summary.txt", "only in blob")

        ltm = LongTermMemory(store, blob, "wf-3")
        result = await ltm.load_summary()
        assert result == "only in blob"

    @pytest.mark.asyncio
    async def test_blob_fallback_rehydrates_redis(self, store, blob):
        await blob.save("workflows/wf-4/ltm/summary.txt", "rehydrated")

        ltm = LongTermMemory(store, blob, "wf-4")
        await ltm.load_summary()  # triggers rehydration

        # Redis should now have the value
        assert store.load_ltm("wf-4") == "rehydrated"


# ======================================================================
# compress()
# ======================================================================

class TestCompress:
    @pytest.mark.asyncio
    async def test_compress_empty_returns_empty_string(self, ltm):
        llm = MagicMock()
        result = await ltm.compress([], llm)
        assert result == ""
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_compress_calls_llm_generate(self, ltm):
        llm = MagicMock()
        llm.generate = AsyncMock(return_value={"content": "Summary text.", "tokens": {"total": 50}})

        entries = [{"turn": 1, "thought": "analysing"}, {"turn": 2, "result": "done"}]
        result = await ltm.compress(entries, llm)

        assert result == "Summary text."
        llm.generate.assert_awaited_once()
        call_kwargs = llm.generate.call_args
        assert call_kwargs.kwargs.get("temperature") == 0.3

    @pytest.mark.asyncio
    async def test_compress_result_contains_entry_content(self, ltm):
        """Verify the entries are serialised into the prompt."""
        captured_prompt = {}

        async def fake_generate(prompt, **kwargs):
            captured_prompt["value"] = prompt
            return {"content": "compressed", "tokens": {"total": 10}}

        llm = MagicMock()
        llm.generate = fake_generate

        await ltm.compress([{"turn": 1, "thought": "important detail"}], llm)
        assert "important detail" in captured_prompt["value"]
