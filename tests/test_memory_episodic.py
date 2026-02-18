"""
Tests for Phase 8B: EpisodicLedger.

What these tests prove:
- append() returns a non-empty Redis Stream entry ID
- tail() returns at most N entries in chronological order
- full_history() returns all entries, oldest first
- Empty workflow returns [] for both tail and full_history
- Multiple appends accumulate and are retrieved correctly
"""
import pytest

from jarviscore.memory.episodic import EpisodicLedger
from jarviscore.testing import MockRedisContextStore


@pytest.fixture
def store():
    return MockRedisContextStore()


@pytest.fixture
def ledger(store):
    return EpisodicLedger(store, "wf-1")


# ======================================================================
# append()
# ======================================================================

class TestAppend:
    @pytest.mark.asyncio
    async def test_returns_entry_id(self, ledger):
        entry_id = await ledger.append({"turn": 1, "thought": "test"})
        assert entry_id is not None
        assert entry_id != ""

    @pytest.mark.asyncio
    async def test_multiple_appends_return_distinct_ids(self, ledger):
        id1 = await ledger.append({"turn": 1})
        id2 = await ledger.append({"turn": 2})
        assert id1 != id2


# ======================================================================
# tail()
# ======================================================================

class TestTail:
    @pytest.mark.asyncio
    async def test_empty_ledger_returns_empty(self, ledger):
        result = await ledger.tail()
        assert result == []

    @pytest.mark.asyncio
    async def test_tail_returns_recent_entries(self, ledger):
        for i in range(5):
            await ledger.append({"turn": i, "value": i})
        result = await ledger.tail(3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_tail_is_chronological(self, ledger):
        for i in range(3):
            await ledger.append({"turn": i})
        result = await ledger.tail(3)
        turns = [e["turn"] for e in result]
        assert turns == sorted(turns)

    @pytest.mark.asyncio
    async def test_tail_count_respected(self, ledger):
        for i in range(10):
            await ledger.append({"turn": i})
        assert len(await ledger.tail(5)) == 5
        assert len(await ledger.tail(1)) == 1


# ======================================================================
# full_history()
# ======================================================================

class TestFullHistory:
    @pytest.mark.asyncio
    async def test_empty_returns_empty(self, ledger):
        assert await ledger.full_history() == []

    @pytest.mark.asyncio
    async def test_all_entries_returned(self, ledger):
        for i in range(7):
            await ledger.append({"turn": i})
        history = await ledger.full_history()
        assert len(history) == 7

    @pytest.mark.asyncio
    async def test_full_history_is_chronological(self, ledger):
        for i in range(4):
            await ledger.append({"turn": i})
        history = await ledger.full_history()
        turns = [e["turn"] for e in history]
        assert turns == sorted(turns)

    @pytest.mark.asyncio
    async def test_full_vs_tail_consistent(self, ledger):
        for i in range(3):
            await ledger.append({"turn": i})
        full = await ledger.full_history()
        tail = await ledger.tail(3)
        assert full == tail


# ======================================================================
# Isolation between workflows
# ======================================================================

class TestWorkflowIsolation:
    @pytest.mark.asyncio
    async def test_separate_workflows_do_not_mix(self, store):
        ledger_a = EpisodicLedger(store, "wf-a")
        ledger_b = EpisodicLedger(store, "wf-b")

        await ledger_a.append({"source": "a"})
        await ledger_b.append({"source": "b"})

        history_a = await ledger_a.full_history()
        history_b = await ledger_b.full_history()

        assert all(e.get("source") == "a" for e in history_a)
        assert all(e.get("source") == "b" for e in history_b)
