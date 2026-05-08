"""
Tests for the three structural OODA loop hooks:

1. State-driven exit   — state.status == "completed" terminates the loop
2. Pre-execute hook    — _pre_execute_hook() can block tool calls
3. Done-gate           — _can_complete() can reject premature DONE

These test at the source/contract level (same strategy as TestOODAIntegration
in test_epistemic_ledger.py) — verifying the hooks exist, are called in the
right order, and have the correct signatures.
"""

import asyncio
import inspect
import pytest
from typing import Any, Dict, Optional, Tuple

from jarviscore.kernel.subagent import BaseSubAgent
from jarviscore.kernel.state import KernelState


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _make_state(**overrides):
    defaults = {
        "workflow_id": "test",
        "step_id": "test",
        "agent_id": "test",
        "task": "test task",
        "status": "active",
        "turn": 0,
    }
    defaults.update(overrides)
    return KernelState(**defaults)


# ──────────────────────────────────────────────────────────────────
# 1. State-Driven Exit Tests
# ──────────────────────────────────────────────────────────────────

class TestStateDrivenExit:
    """Verify that state.status == 'completed' terminates the loop."""

    def test_state_completed_check_exists_in_run(self):
        """run() must check state.status == 'completed' after tool execution."""
        source = inspect.getsource(BaseSubAgent.run)
        assert 'state.status' in source or "status\", None) == \"completed\"" in source

    def test_state_driven_exit_returns_success(self):
        """When state.status == 'completed', run() returns status='success'."""
        source = inspect.getsource(BaseSubAgent.run)
        # Find the state-driven exit block
        idx = source.index("state_driven")
        block = source[max(0, idx - 500):idx + 500]
        assert "status=\"success\"" in block or 'status="success"' in block

    def test_state_driven_exit_after_tool_execution(self):
        """State-driven exit must appear AFTER _execute_tool, not before."""
        source = inspect.getsource(BaseSubAgent.run)
        exec_pos = source.index("_execute_tool")
        state_exit_pos = source.index("state_driven")
        assert state_exit_pos > exec_pos

    def test_state_driven_exit_uses_tool_result_as_payload(self):
        """The exit payload should be the tool_result, not parsed content."""
        source = inspect.getsource(BaseSubAgent.run)
        idx = source.index("state_driven")
        block = source[max(0, idx - 300):idx + 100]
        assert "payload=tool_result" in block


# ──────────────────────────────────────────────────────────────────
# 2. Pre-Execute Hook Tests
# ──────────────────────────────────────────────────────────────────

class TestPreExecuteHook:
    """Verify the _pre_execute_hook mechanism."""

    def test_hook_exists_on_base(self):
        """BaseSubAgent must define _pre_execute_hook."""
        assert hasattr(BaseSubAgent, "_pre_execute_hook")

    def test_hook_is_async(self):
        """_pre_execute_hook must be async (returns a coroutine)."""
        assert asyncio.iscoroutinefunction(BaseSubAgent._pre_execute_hook)

    def test_hook_default_returns_none(self):
        """Default _pre_execute_hook returns None (allow all)."""
        class ConcreteAgent(BaseSubAgent):
            @property
            def role(self): return "test"
            def _build_system_prompt(self): return ""
            def get_system_prompt(self): return ""
            def setup_tools(self): return []

        agent = ConcreteAgent.__new__(ConcreteAgent)
        state = _make_state()
        result = asyncio.run(agent._pre_execute_hook("some_tool", {}, state))
        assert result is None

    def test_hook_signature(self):
        """_pre_execute_hook must accept (tool_name, params, state)."""
        sig = inspect.signature(BaseSubAgent._pre_execute_hook)
        params = list(sig.parameters.keys())
        # self, tool_name, params, state
        assert len(params) >= 4
        assert "tool_name" in params
        assert "params" in params
        assert "state" in params

    def test_hook_called_before_execute_in_source(self):
        """_pre_execute_hook must be called BEFORE _execute_tool."""
        source = inspect.getsource(BaseSubAgent.run)
        hook_pos = source.index("_pre_execute_hook")
        exec_pos = source.index("_execute_tool")
        assert hook_pos < exec_pos

    def test_hook_called_after_epistemic_check(self):
        """_pre_execute_hook must be after epistemic validation."""
        source = inspect.getsource(BaseSubAgent.run)
        epistemic_pos = source.index("validate_action")
        hook_pos = source.index("_pre_execute_hook")
        assert hook_pos > epistemic_pos

    def test_hook_block_uses_continue(self):
        """When hook returns a result, the loop should continue (not execute)."""
        source = inspect.getsource(BaseSubAgent.run)
        hook_idx = source.index("_pre_execute_hook")
        # Find the continue after the hook block
        block = source[hook_idx:hook_idx + 1500]
        assert "pre_execute_block" in block
        assert "continue" in block


# ──────────────────────────────────────────────────────────────────
# 3. Done-Gate Tests
# ──────────────────────────────────────────────────────────────────

class TestDoneGate:
    """Verify the _can_complete mechanism."""

    def test_can_complete_exists_on_base(self):
        """BaseSubAgent must define _can_complete."""
        assert hasattr(BaseSubAgent, "_can_complete")

    def test_default_allows_completion(self):
        """Default _can_complete returns (True, '')."""
        class ConcreteAgent(BaseSubAgent):
            @property
            def role(self): return "test"
            def _build_system_prompt(self): return ""
            def get_system_prompt(self): return ""
            def setup_tools(self): return []

        agent = ConcreteAgent.__new__(ConcreteAgent)
        state = _make_state()
        ok, reason = agent._can_complete(state, {"type": "done", "summary": "test"})
        assert ok is True
        assert reason == ""

    def test_can_complete_signature(self):
        """_can_complete must accept (state, parsed) and return tuple."""
        sig = inspect.signature(BaseSubAgent._can_complete)
        params = list(sig.parameters.keys())
        assert "state" in params
        assert "parsed" in params

    def test_done_gate_called_before_exit(self):
        """_can_complete must be called BEFORE setting state.status = 'completed'."""
        source = inspect.getsource(BaseSubAgent.run)
        # Find the DONE handler block
        done_idx = source.index("Handle DONE")
        done_block = source[done_idx:done_idx + 2000]
        gate_pos = done_block.index("_can_complete")
        completed_pos = done_block.index("state.status = \"completed\"")
        assert gate_pos < completed_pos

    def test_rejection_injects_thought(self):
        """On rejection, a [DONE_GATE] thought should be injected."""
        source = inspect.getsource(BaseSubAgent.run)
        done_idx = source.index("Handle DONE")
        done_block = source[done_idx:done_idx + 2000]
        assert "DONE_GATE" in done_block
        assert "Continue working" in done_block

    def test_rejection_continues_loop(self):
        """On rejection, the loop should continue (not exit)."""
        source = inspect.getsource(BaseSubAgent.run)
        done_idx = source.index("Handle DONE")
        # Find the not can_exit block
        block = source[done_idx:done_idx + 2000]
        gate_idx = block.index("_can_complete")
        after_gate = block[gate_idx:gate_idx + 1200]
        assert "continue" in after_gate


# ──────────────────────────────────────────────────────────────────
# 4. Researcher Hook Integration Tests
# ──────────────────────────────────────────────────────────────────

class TestResearcherHookIntegration:
    """Verify the researcher properly overrides the new hooks."""

    def test_researcher_overrides_pre_execute_hook(self):
        """ResearcherSubAgent must override _pre_execute_hook."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        # Verify it's not just the base class method
        assert (
            ResearcherSubAgent._pre_execute_hook
            is not BaseSubAgent._pre_execute_hook
        )

    def test_researcher_overrides_can_complete(self):
        """ResearcherSubAgent must override _can_complete."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        assert (
            ResearcherSubAgent._can_complete
            is not BaseSubAgent._can_complete
        )

    def test_researcher_no_longer_has_dead_act(self):
        """The dead _act() method should be removed."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        # _act should not exist on ResearcherSubAgent (it was dead code)
        assert not hasattr(ResearcherSubAgent, "_act") or \
            ResearcherSubAgent._act is getattr(BaseSubAgent, "_act", None)

    def test_researcher_pre_execute_hook_calls_phase_contract(self):
        """The override should call _check_phase_tool_contract."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        source = inspect.getsource(ResearcherSubAgent._pre_execute_hook)
        assert "_check_phase_tool_contract" in source

    def test_researcher_pre_execute_hook_returns_error_on_violation(self):
        """On phase violation, hook returns dict with status=error."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        source = inspect.getsource(ResearcherSubAgent._pre_execute_hook)
        assert "PHASE_TOOL_CONTRACT_VIOLATION" in source

    def test_researcher_can_complete_checks_evidence(self):
        """The researcher's _can_complete checks for meaningful research."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        source = inspect.getsource(ResearcherSubAgent._can_complete)
        assert "meaningful_research" in source
        assert "read_web_content" in source


# ──────────────────────────────────────────────────────────────────
# 5. Guard Ordering Tests (full pipeline)
# ──────────────────────────────────────────────────────────────────

class TestGuardOrdering:
    """Verify the complete guard ordering in the OODA ACT phase.

    The correct order is:
    1. Repeat failure guard
    2. Epistemic validation
    3. Pre-execute hook
    4. _execute_tool
    5. Epistemic recording
    6. State-driven exit check
    """

    def test_full_guard_order(self):
        source = inspect.getsource(BaseSubAgent.run)
        positions = {
            "repeat_failure": source.index("is_repeat_failure"),
            "epistemic": source.index("validate_action"),
            "pre_execute_hook": source.index("_pre_execute_hook"),
            "execute_tool": source.index("_execute_tool"),
            "record_outcome": source.index("record_outcome"),
            "state_driven_exit": source.index("state_driven"),
        }

        assert positions["repeat_failure"] < positions["epistemic"]
        assert positions["epistemic"] < positions["pre_execute_hook"]
        assert positions["pre_execute_hook"] < positions["execute_tool"]
        assert positions["execute_tool"] < positions["record_outcome"]
        assert positions["record_outcome"] < positions["state_driven_exit"]

    def test_done_gate_before_done_exit(self):
        """_can_complete appears before the AgentOutput return in DONE handler."""
        source = inspect.getsource(BaseSubAgent.run)
        done_idx = source.index("Handle DONE")
        done_block = source[done_idx:done_idx + 2500]
        gate_pos = done_block.index("_can_complete")
        return_pos = done_block.index("return AgentOutput")
        assert gate_pos < return_pos
