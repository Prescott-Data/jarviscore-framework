"""
Tests for Phase 8F: RedisMemoryAccessor.

What these tests prove:
- get() reads step output from Redis, extracting 'output' key
- get() returns default when step not found
- put() stores a value as a step output in Redis
- has() returns True/False correctly
- keys() returns all step IDs stored for the workflow
- all() returns all outputs with 'output' key extracted
- __contains__ / __getitem__ / __setitem__ work correctly
- len() reflects number of stored steps
- get_raw() returns full result dict including metadata
- Isolation: two accessors on different workflow IDs don't share data
"""
import pytest

from jarviscore.context.memory import RedisMemoryAccessor
from jarviscore.testing import MockRedisContextStore


@pytest.fixture
def store():
    return MockRedisContextStore()


@pytest.fixture
def acc(store):
    return RedisMemoryAccessor(store, "wf-1")


# ======================================================================
# get() / put()
# ======================================================================

class TestGetPut:
    def test_get_nonexistent_returns_default(self, acc):
        assert acc.get("missing") is None
        assert acc.get("missing", "fallback") == "fallback"

    def test_put_then_get_roundtrip(self, acc):
        acc.put("step1", {"result": 42})
        assert acc.get("step1") == {"result": 42}

    def test_get_extracts_output_key(self, store):
        store.save_step_output("wf-1", "s1", output={"val": 7}, summary="done")
        acc = RedisMemoryAccessor(store, "wf-1")
        assert acc.get("s1") == {"val": 7}

    def test_put_string_value(self, acc):
        acc.put("step2", "plain string")
        assert acc.get("step2") == "plain string"

    def test_put_list_value(self, acc):
        acc.put("step3", [1, 2, 3])
        assert acc.get("step3") == [1, 2, 3]

    def test_overwrite(self, acc):
        acc.put("step1", "first")
        acc.put("step1", "second")
        assert acc.get("step1") == "second"


# ======================================================================
# get_raw()
# ======================================================================

class TestGetRaw:
    def test_get_raw_returns_full_dict(self, store):
        store.save_step_output("wf-1", "s1", output={"val": 1}, summary="ok")
        acc = RedisMemoryAccessor(store, "wf-1")
        raw = acc.get_raw("s1")
        assert isinstance(raw, dict)
        assert "output" in raw
        assert raw["summary"] == "ok"

    def test_get_raw_nonexistent_returns_default(self, acc):
        assert acc.get_raw("missing") is None
        assert acc.get_raw("missing", "fallback") == "fallback"


# ======================================================================
# has()
# ======================================================================

class TestHas:
    def test_has_false_for_nonexistent(self, acc):
        assert acc.has("ghost") is False

    def test_has_true_after_put(self, acc):
        acc.put("step1", "data")
        assert acc.has("step1") is True


# ======================================================================
# keys() / all()
# ======================================================================

class TestKeysAll:
    def test_keys_empty_initially(self, acc):
        assert acc.keys() == []

    def test_keys_after_put(self, acc):
        acc.put("s1", "a")
        acc.put("s2", "b")
        assert set(acc.keys()) == {"s1", "s2"}

    def test_all_empty_initially(self, acc):
        assert acc.all() == {}

    def test_all_after_put(self, acc):
        acc.put("s1", "val1")
        acc.put("s2", "val2")
        result = acc.all()
        assert result["s1"] == "val1"
        assert result["s2"] == "val2"

    def test_len_matches_keys(self, acc):
        acc.put("s1", 1)
        acc.put("s2", 2)
        assert len(acc) == len(acc.keys())


# ======================================================================
# Dict-style operators
# ======================================================================

class TestDictInterface:
    def test_contains_operator(self, acc):
        assert "step1" not in acc
        acc.put("step1", "x")
        assert "step1" in acc

    def test_getitem(self, acc):
        acc.put("step1", "hello")
        assert acc["step1"] == "hello"

    def test_setitem(self, acc):
        acc["step2"] = "world"
        assert acc.get("step2") == "world"


# ======================================================================
# Workflow isolation
# ======================================================================

class TestIsolation:
    def test_separate_workflows_isolated(self, store):
        acc_a = RedisMemoryAccessor(store, "wf-a")
        acc_b = RedisMemoryAccessor(store, "wf-b")

        acc_a.put("step1", "from_a")
        assert acc_b.get("step1") is None

    def test_keys_scoped_to_workflow(self, store):
        acc_a = RedisMemoryAccessor(store, "wf-a")
        acc_b = RedisMemoryAccessor(store, "wf-b")

        acc_a.put("s1", 1)
        acc_b.put("s2", 2)

        assert "s1" not in acc_b.keys()
        assert "s2" not in acc_a.keys()
