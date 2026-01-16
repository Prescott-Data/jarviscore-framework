"""
Tests for JarvisCore context module.

Tests MemoryAccessor, DependencyAccessor, and JarvisContext classes
which provide the orchestration primitives for Custom Profile agents.
"""
import pytest
from jarviscore.context import (
    JarvisContext,
    MemoryAccessor,
    DependencyAccessor,
    create_context
)


class TestMemoryAccessor:
    """Tests for MemoryAccessor class."""

    def test_init_with_empty_memory(self):
        """Test initialization with empty memory dict."""
        memory = MemoryAccessor({}, "step1")
        assert len(memory) == 0
        assert memory.keys() == []

    def test_init_with_existing_memory(self):
        """Test initialization with pre-populated memory."""
        data = {"step0": {"status": "success", "output": [1, 2, 3]}}
        memory = MemoryAccessor(data, "step1")
        assert len(memory) == 1
        assert "step0" in memory.keys()

    def test_get_extracts_output(self):
        """Test that get() extracts 'output' from result dicts."""
        data = {
            "step0": {"status": "success", "output": {"result": "data"}}
        }
        memory = MemoryAccessor(data, "step1")

        result = memory.get("step0")
        assert result == {"result": "data"}

    def test_get_returns_raw_value_if_no_output_key(self):
        """Test get() returns raw value if no 'output' key."""
        data = {"step0": "raw_string_value"}
        memory = MemoryAccessor(data, "step1")

        result = memory.get("step0")
        assert result == "raw_string_value"

    def test_get_returns_default_for_missing_key(self):
        """Test get() returns default for missing key."""
        memory = MemoryAccessor({}, "step1")

        assert memory.get("missing") is None
        assert memory.get("missing", default="fallback") == "fallback"
        assert memory.get("missing", default=[]) == []

    def test_get_raw_returns_full_dict(self):
        """Test get_raw() returns full result dict."""
        data = {
            "step0": {"status": "success", "output": "data", "agent": "agent1"}
        }
        memory = MemoryAccessor(data, "step1")

        result = memory.get_raw("step0")
        assert result == {"status": "success", "output": "data", "agent": "agent1"}

    def test_put_stores_value(self):
        """Test put() stores value in memory."""
        data = {}
        memory = MemoryAccessor(data, "step1")

        memory.put("intermediate", {"processed": True})

        assert "intermediate" in data
        assert data["intermediate"] == {"processed": True}

    def test_has_returns_true_for_existing_key(self):
        """Test has() returns True for existing key."""
        data = {"step0": "value"}
        memory = MemoryAccessor(data, "step1")

        assert memory.has("step0") is True
        assert memory.has("missing") is False

    def test_all_extracts_outputs(self):
        """Test all() extracts outputs from all results."""
        data = {
            "step0": {"status": "success", "output": [1, 2, 3]},
            "step1": {"status": "success", "output": {"key": "value"}},
            "raw": "raw_value"
        }
        memory = MemoryAccessor(data, "step2")

        result = memory.all()

        assert result["step0"] == [1, 2, 3]
        assert result["step1"] == {"key": "value"}
        assert result["raw"] == "raw_value"

    def test_keys_returns_all_keys(self):
        """Test keys() returns all memory keys."""
        data = {"step0": "a", "step1": "b", "step2": "c"}
        memory = MemoryAccessor(data, "step3")

        keys = memory.keys()

        assert set(keys) == {"step0", "step1", "step2"}

    def test_contains_operator(self):
        """Test 'in' operator support."""
        data = {"step0": "value"}
        memory = MemoryAccessor(data, "step1")

        assert "step0" in memory
        assert "missing" not in memory

    def test_getitem_operator(self):
        """Test dict-style access with []."""
        data = {"step0": {"status": "success", "output": "data"}}
        memory = MemoryAccessor(data, "step1")

        assert memory["step0"] == "data"

    def test_setitem_operator(self):
        """Test dict-style assignment with []."""
        data = {}
        memory = MemoryAccessor(data, "step1")

        memory["key"] = "value"

        assert data["key"] == "value"

    def test_len(self):
        """Test len() returns number of items."""
        data = {"a": 1, "b": 2, "c": 3}
        memory = MemoryAccessor(data, "step1")

        assert len(memory) == 3

    def test_repr(self):
        """Test string representation."""
        data = {"step0": "a", "step1": "b"}
        memory = MemoryAccessor(data, "step2")

        repr_str = repr(memory)

        assert "MemoryAccessor" in repr_str
        assert "step0" in repr_str or "keys=" in repr_str


class TestDependencyAccessor:
    """Tests for DependencyAccessor class."""

    def test_init_without_manager(self):
        """Test initialization without dependency manager."""
        memory = {"step0": "value"}
        deps = DependencyAccessor(None, memory)

        assert deps._manager is None
        assert deps._memory == memory

    def test_is_ready_returns_true_for_existing_step(self):
        """Test is_ready() returns True for step in memory."""
        memory = {"step0": {"output": "data"}}
        deps = DependencyAccessor(None, memory)

        assert deps.is_ready("step0") is True
        assert deps.is_ready("missing") is False

    def test_all_ready_returns_true_when_all_present(self):
        """Test all_ready() returns True when all steps present."""
        memory = {"step0": "a", "step1": "b", "step2": "c"}
        deps = DependencyAccessor(None, memory)

        assert deps.all_ready(["step0", "step1"]) is True
        assert deps.all_ready(["step0", "step1", "step2"]) is True
        assert deps.all_ready(["step0", "missing"]) is False

    def test_any_ready_returns_true_when_any_present(self):
        """Test any_ready() returns True when any step present."""
        memory = {"step0": "a"}
        deps = DependencyAccessor(None, memory)

        assert deps.any_ready(["step0", "missing"]) is True
        assert deps.any_ready(["missing1", "missing2"]) is False

    def test_check_without_manager(self):
        """Test check() works without manager (fallback mode)."""
        memory = {"step0": "a", "step1": "b"}
        deps = DependencyAccessor(None, memory)

        ready, missing = deps.check(["step0", "step1"])
        assert ready is True
        assert missing == []

        ready, missing = deps.check(["step0", "step2"])
        assert ready is False
        assert missing == ["step2"]

    def test_simple_wait_without_manager(self):
        """Test _simple_wait() extracts outputs."""
        memory = {
            "step0": {"status": "success", "output": [1, 2, 3]},
            "step1": "raw_value"
        }
        deps = DependencyAccessor(None, memory)

        result = deps._simple_wait(["step0", "step1"])

        assert result["step0"] == [1, 2, 3]
        assert result["step1"] == "raw_value"

    def test_repr(self):
        """Test string representation."""
        memory = {"step0": "a", "step1": "b"}
        deps = DependencyAccessor(None, memory)

        repr_str = repr(deps)

        assert "DependencyAccessor" in repr_str


class TestJarvisContext:
    """Tests for JarvisContext class."""

    @pytest.fixture
    def sample_memory(self):
        """Sample memory dict for tests."""
        return {
            "step0": {"status": "success", "output": {"data": [1, 2, 3]}},
            "step1": {"status": "success", "output": "processed"}
        }

    @pytest.fixture
    def sample_context(self, sample_memory):
        """Create a sample JarvisContext."""
        memory_accessor = MemoryAccessor(sample_memory, "step2")
        dep_accessor = DependencyAccessor(None, sample_memory)

        return JarvisContext(
            workflow_id="test-workflow",
            step_id="step2",
            task="Process data",
            params={"threshold": 0.5, "mode": "fast"},
            memory=memory_accessor,
            deps=dep_accessor
        )

    def test_context_attributes(self, sample_context):
        """Test context has correct attributes."""
        assert sample_context.workflow_id == "test-workflow"
        assert sample_context.step_id == "step2"
        assert sample_context.task == "Process data"
        assert sample_context.params == {"threshold": 0.5, "mode": "fast"}

    def test_previous_gets_step_output(self, sample_context):
        """Test previous() retrieves step output."""
        result = sample_context.previous("step0")
        assert result == {"data": [1, 2, 3]}

        result = sample_context.previous("step1")
        assert result == "processed"

    def test_previous_returns_default_for_missing(self, sample_context):
        """Test previous() returns default for missing step."""
        result = sample_context.previous("missing")
        assert result is None

        result = sample_context.previous("missing", default={})
        assert result == {}

    def test_all_previous_gets_all_outputs(self, sample_context):
        """Test all_previous() retrieves all outputs."""
        result = sample_context.all_previous()

        assert "step0" in result
        assert "step1" in result
        assert result["step0"] == {"data": [1, 2, 3]}
        assert result["step1"] == "processed"

    def test_previous_results_property(self, sample_context):
        """Test previous_results property is alias for all_previous()."""
        result = sample_context.previous_results
        assert result == sample_context.all_previous()

    def test_has_previous(self, sample_context):
        """Test has_previous() checks step existence."""
        assert sample_context.has_previous("step0") is True
        assert sample_context.has_previous("step1") is True
        assert sample_context.has_previous("missing") is False

    def test_get_param(self, sample_context):
        """Test get_param() retrieves task parameters."""
        assert sample_context.get_param("threshold") == 0.5
        assert sample_context.get_param("mode") == "fast"
        assert sample_context.get_param("missing") is None
        assert sample_context.get_param("missing", default=1.0) == 1.0

    def test_memory_accessor_available(self, sample_context):
        """Test memory accessor is available on context."""
        assert sample_context.memory is not None
        assert isinstance(sample_context.memory, MemoryAccessor)
        assert sample_context.memory.get("step0") == {"data": [1, 2, 3]}

    def test_deps_accessor_available(self, sample_context):
        """Test dependency accessor is available on context."""
        assert sample_context.deps is not None
        assert isinstance(sample_context.deps, DependencyAccessor)
        assert sample_context.deps.is_ready("step0") is True

    def test_context_with_none_memory(self):
        """Test context handles None memory gracefully."""
        ctx = JarvisContext(
            workflow_id="test",
            step_id="step0",
            task="test",
            params={},
            memory=None,
            deps=None
        )

        assert ctx.previous("any") is None
        assert ctx.all_previous() == {}
        assert ctx.has_previous("any") is False

    def test_repr(self, sample_context):
        """Test string representation."""
        repr_str = repr(sample_context)

        assert "JarvisContext" in repr_str
        assert "test-workflow" in repr_str
        assert "step2" in repr_str


class TestCreateContext:
    """Tests for create_context factory function."""

    def test_create_context_basic(self):
        """Test creating context with basic parameters."""
        memory_dict = {"step0": {"output": "data"}}

        ctx = create_context(
            workflow_id="workflow-1",
            step_id="step1",
            task="Process",
            params={"key": "value"},
            memory_dict=memory_dict,
            dependency_manager=None
        )

        assert ctx.workflow_id == "workflow-1"
        assert ctx.step_id == "step1"
        assert ctx.task == "Process"
        assert ctx.params == {"key": "value"}
        assert ctx.memory is not None
        assert ctx.deps is not None

    def test_create_context_memory_works(self):
        """Test that created context's memory accessor works."""
        memory_dict = {"step0": {"output": [1, 2, 3]}}

        ctx = create_context(
            workflow_id="w1",
            step_id="step1",
            task="test",
            params={},
            memory_dict=memory_dict
        )

        assert ctx.previous("step0") == [1, 2, 3]

    def test_create_context_deps_works(self):
        """Test that created context's deps accessor works."""
        memory_dict = {"step0": "data", "step1": "more"}

        ctx = create_context(
            workflow_id="w1",
            step_id="step2",
            task="test",
            params={},
            memory_dict=memory_dict
        )

        assert ctx.deps.is_ready("step0") is True
        assert ctx.deps.all_ready(["step0", "step1"]) is True

    def test_create_context_empty_params(self):
        """Test creating context with empty params."""
        ctx = create_context(
            workflow_id="w1",
            step_id="step0",
            task="test",
            params={},
            memory_dict={}
        )

        assert ctx.params == {}
        assert ctx.get_param("any") is None


class TestMemoryAccessorEdgeCases:
    """Edge case tests for MemoryAccessor."""

    def test_nested_output_extraction(self):
        """Test extraction with nested output structure."""
        data = {
            "step0": {
                "status": "success",
                "output": {
                    "nested": {
                        "deep": {"value": 42}
                    }
                }
            }
        }
        memory = MemoryAccessor(data, "step1")

        result = memory.get("step0")
        assert result["nested"]["deep"]["value"] == 42

    def test_list_output_extraction(self):
        """Test extraction when output is a list."""
        data = {
            "step0": {"status": "success", "output": [1, 2, 3, 4, 5]}
        }
        memory = MemoryAccessor(data, "step1")

        result = memory.get("step0")
        assert result == [1, 2, 3, 4, 5]

    def test_none_output_extraction(self):
        """Test extraction when output is None."""
        data = {
            "step0": {"status": "success", "output": None}
        }
        memory = MemoryAccessor(data, "step1")

        result = memory.get("step0")
        assert result is None

    def test_empty_dict_output(self):
        """Test extraction when output is empty dict."""
        data = {
            "step0": {"status": "success", "output": {}}
        }
        memory = MemoryAccessor(data, "step1")

        result = memory.get("step0")
        assert result == {}

    def test_mutation_through_accessor(self):
        """Test that mutations through accessor affect original dict."""
        data = {}
        memory = MemoryAccessor(data, "step1")

        memory.put("key", {"nested": "value"})

        # Original dict should be mutated
        assert data["key"] == {"nested": "value"}

        # Modify through get and verify
        result = memory.get("key")
        result["new_key"] = "new_value"

        # Original should reflect change (same reference)
        assert data["key"]["new_key"] == "new_value"
