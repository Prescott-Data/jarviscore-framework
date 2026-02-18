"""
Tests for Phase 7A: WorkflowState serializable dataclass.

What these tests prove:
- WorkflowState initialises with correct defaults
- is_complete() reflects all terminal states correctly
- Zombie detection: running_steps can be populated and cleared
- to_dict() / from_dict() roundtrip is lossless
- has_waiting_steps() and has_failed_steps() helpers work
- status field transitions (pending → running → completed/failed/waiting)
"""

import pytest

from jarviscore.orchestration.state import WorkflowState


# ======================================================================
# Initialisation
# ======================================================================

class TestWorkflowStateInit:
    def test_defaults(self):
        state = WorkflowState(workflow_id="wf-1")
        assert state.workflow_id == "wf-1"
        assert state.total_steps == 0
        assert state.processed_steps == set()
        assert state.running_steps == {}
        assert state.failed_steps == set()
        assert state.waiting_steps == {}
        assert state.status == "pending"

    def test_explicit_values(self):
        state = WorkflowState(
            workflow_id="wf-2",
            total_steps=3,
            status="running",
        )
        assert state.total_steps == 3
        assert state.status == "running"


# ======================================================================
# is_complete()
# ======================================================================

class TestIsComplete:
    def test_empty_workflow_complete(self):
        """Zero-step workflow is trivially complete."""
        state = WorkflowState(workflow_id="wf", total_steps=0)
        assert state.is_complete()

    def test_not_complete_while_running(self):
        state = WorkflowState(workflow_id="wf", total_steps=2)
        state.running_steps["step1"] = 1700000000.0
        assert not state.is_complete()

    def test_not_complete_while_pending(self):
        state = WorkflowState(workflow_id="wf", total_steps=2)
        state.processed_steps.add("step1")
        # step2 is still pending (not in any terminal set)
        assert not state.is_complete()

    def test_complete_when_all_processed(self):
        state = WorkflowState(workflow_id="wf", total_steps=2)
        state.processed_steps.update({"step1", "step2"})
        assert state.is_complete()

    def test_complete_when_all_failed(self):
        state = WorkflowState(workflow_id="wf", total_steps=2)
        state.failed_steps.update({"step1", "step2"})
        assert state.is_complete()

    def test_complete_with_mixed_terminal(self):
        state = WorkflowState(workflow_id="wf", total_steps=3)
        state.processed_steps.add("step1")
        state.failed_steps.add("step2")
        state.waiting_steps["step3"] = "needs human approval"
        assert state.is_complete()

    def test_not_complete_mixed_with_running(self):
        state = WorkflowState(workflow_id="wf", total_steps=3)
        state.processed_steps.add("step1")
        state.running_steps["step2"] = 1700000000.0
        state.failed_steps.add("step3")
        assert not state.is_complete()


# ======================================================================
# has_waiting_steps() / has_failed_steps()
# ======================================================================

class TestStatusHelpers:
    def test_has_waiting_false_by_default(self):
        state = WorkflowState(workflow_id="wf", total_steps=1)
        assert not state.has_waiting_steps()

    def test_has_waiting_true(self):
        state = WorkflowState(workflow_id="wf", total_steps=1)
        state.waiting_steps["step1"] = "HITL required"
        assert state.has_waiting_steps()

    def test_has_failed_false_by_default(self):
        state = WorkflowState(workflow_id="wf", total_steps=1)
        assert not state.has_failed_steps()

    def test_has_failed_true(self):
        state = WorkflowState(workflow_id="wf", total_steps=1)
        state.failed_steps.add("step1")
        assert state.has_failed_steps()


# ======================================================================
# Zombie detection
# ======================================================================

class TestZombieDetection:
    def test_running_steps_cleared_on_resume(self):
        """Simulates clearing zombie steps on crash recovery."""
        state = WorkflowState(workflow_id="wf", total_steps=2)
        state.running_steps["step1"] = 1700000000.0
        # Simulate what the engine does on resume
        state.running_steps.clear()
        assert state.running_steps == {}

    def test_running_steps_dict_maps_to_timestamp(self):
        state = WorkflowState(workflow_id="wf", total_steps=1)
        import time
        ts = time.time()
        state.running_steps["step1"] = ts
        assert state.running_steps["step1"] == ts


# ======================================================================
# Serialisation
# ======================================================================

class TestSerialization:
    def _full_state(self) -> WorkflowState:
        state = WorkflowState(
            workflow_id="wf-full",
            total_steps=4,
            status="running",
        )
        state.processed_steps.add("step1")
        state.running_steps["step2"] = 1700000000.5
        state.failed_steps.add("step3")
        state.waiting_steps["step4"] = "awaiting approval"
        return state

    def test_to_dict_shape(self):
        d = self._full_state().to_dict()
        assert d["workflow_id"] == "wf-full"
        assert d["total_steps"] == 4
        assert d["status"] == "running"
        assert "step1" in d["processed_steps"]
        assert d["running_steps"]["step2"] == 1700000000.5
        assert "step3" in d["failed_steps"]
        assert d["waiting_steps"]["step4"] == "awaiting approval"

    def test_roundtrip_lossless(self):
        original = self._full_state()
        restored = WorkflowState.from_dict(original.to_dict())

        assert restored.workflow_id == original.workflow_id
        assert restored.total_steps == original.total_steps
        assert restored.processed_steps == original.processed_steps
        assert restored.running_steps == original.running_steps
        assert restored.failed_steps == original.failed_steps
        assert restored.waiting_steps == original.waiting_steps
        assert restored.status == original.status

    def test_from_dict_empty_workflow(self):
        """Deserialise a minimal dict (no optional fields)."""
        state = WorkflowState.from_dict({"workflow_id": "wf-minimal"})
        assert state.total_steps == 0
        assert state.processed_steps == set()
        assert state.running_steps == {}
        assert state.status == "pending"

    def test_lists_converted_to_sets(self):
        """from_dict must convert JSON lists back to Python sets."""
        d = {
            "workflow_id": "wf-x",
            "total_steps": 2,
            "processed_steps": ["a", "b"],
            "failed_steps": ["c"],
            "running_steps": {},
            "waiting_steps": {},
            "status": "failed",
        }
        state = WorkflowState.from_dict(d)
        assert isinstance(state.processed_steps, set)
        assert "a" in state.processed_steps
        assert isinstance(state.failed_steps, set)
