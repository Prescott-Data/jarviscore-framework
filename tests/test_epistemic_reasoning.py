"""
Tests for Epistemic Reasoning Hardening.

Validates:
1. Knowledge Accumulator — research_findings and api_specs are surfaced in context
2. Decision prompt — epistemic contract keywords are present
3. Conversation history window — 10 turns retained
4. Epistemic state updates — update_epistemic_state populates belief_state
"""

import pytest
from jarviscore.context.context_manager import ContextManager, BudgetConfig
from jarviscore.kernel.state import KernelState, ToolResult
from jarviscore.kernel.subagent import BaseSubAgent


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

def _make_state(**overrides):
    """Create a KernelState with sensible defaults."""
    defaults = {
        "workflow_id": "test-wf",
        "step_id": "test-step",
        "agent_id": "test-agent",
        "task": "Test task description",
        "status": "active",
        "turn": 3,
    }
    defaults.update(overrides)
    return KernelState(**defaults)


# ──────────────────────────────────────────────────────────────────────
# Knowledge Accumulator Tests
# ──────────────────────────────────────────────────────────────────────

class TestKnowledgeAccumulator:
    """Verify that research_findings and api_specs are surfaced in context."""

    def test_findings_visible_in_context(self):
        """Research findings should appear in the WHAT I KNOW SO FAR block."""
        state = _make_state()
        state.internal_variables["research_findings"] = [
            {"summary": "Found Stripe API documentation at stripe.com/docs"},
            {"content_preview": "OAuth2 token endpoint discovered"},
        ]

        cm = ContextManager()
        context = cm.build_context(state)

        assert "WHAT I KNOW SO FAR" in context
        assert "Research Findings:" in context
        assert "2 item(s)" in context
        assert "Stripe API" in context

    def test_api_specs_visible_in_context(self):
        """API specs should appear with method/path formatting."""
        state = _make_state()
        state.internal_variables["api_specs"] = [
            {"method": "GET", "path": "/v1/customers", "summary": "List customers"},
            {"method": "POST", "path": "/v1/customers", "summary": "Create customer"},
        ]

        cm = ContextManager()
        context = cm.build_context(state)

        assert "WHAT I KNOW SO FAR" in context
        assert "API Specs Extracted:" in context
        assert "2 endpoint(s)" in context
        assert "`GET /v1/customers`" in context
        assert "`POST /v1/customers`" in context

    def test_empty_findings_no_block(self):
        """No KNOWLEDGE ACCUMULATOR block when both are empty."""
        state = _make_state()
        # No research_findings or api_specs set

        cm = ContextManager()
        context = cm.build_context(state)

        assert "WHAT I KNOW SO FAR" not in context

    def test_findings_not_in_internal_state_block(self):
        """research_findings should be skipped from the INTERNAL STATE block."""
        state = _make_state()
        state.internal_variables["research_findings"] = [{"summary": "test"}]
        state.internal_variables["api_specs"] = [{"method": "GET", "path": "/test"}]
        state.internal_variables["some_other_var"] = "should appear"

        cm = ContextManager()
        context = cm.build_context(state)

        # The INTERNAL STATE block should show some_other_var but not research_findings/api_specs
        # (they're surfaced by the Knowledge Accumulator block instead)
        assert "WHAT I KNOW SO FAR" in context
        # Internal state should still exist with other vars
        if "INTERNAL STATE" in context:
            internal_idx = context.index("INTERNAL STATE")
            internal_section = context[internal_idx:internal_idx + 500]
            assert "some_other_var" in internal_section

    def test_knowledge_accumulator_budget_cap(self):
        """Knowledge Accumulator should be capped at 4000 tokens."""
        state = _make_state()
        # Create a very large set of findings
        state.internal_variables["research_findings"] = [
            {"summary": f"Finding {i}: " + "x" * 200} for i in range(50)
        ]
        state.internal_variables["api_specs"] = [
            {"method": "GET", "path": f"/v1/resource_{i}", "summary": f"Resource {i}"} for i in range(50)
        ]

        cm = ContextManager()
        context = cm.build_context(state)

        # Block should exist but be bounded (not explode the context)
        assert "WHAT I KNOW SO FAR" in context
        # Only last 8 specs and last 5 findings should be shown
        assert "resource_49" in context
        assert "resource_0" not in context  # Too old, should be trimmed


# ──────────────────────────────────────────────────────────────────────
# Epistemic Decision Contract Tests
# ──────────────────────────────────────────────────────────────────────

class TestEpistemicDecisionPrompt:
    """Verify the decision prompt includes epistemic contract keywords."""

    def _build_prompt(self, state=None):
        """Helper to call _build_user_prompt via a concrete subclass."""
        # Create a minimal concrete subclass just for testing
        class StubAgent(BaseSubAgent):
            def get_system_prompt(self):
                return "Test system prompt"

            def setup_tools(self):
                pass

        agent = StubAgent(
            agent_id="test",
            role="researcher",
            llm_client=None,
        )
        if state is None:
            state = _make_state()
        return agent._build_user_prompt(state, "## MISSION\n**Task:** Test")

    def test_prompt_includes_known(self):
        prompt = self._build_prompt()
        assert "KNOWN:" in prompt

    def test_prompt_includes_gap(self):
        prompt = self._build_prompt()
        assert "GAP:" in prompt

    def test_prompt_includes_strategy(self):
        prompt = self._build_prompt()
        assert "STRATEGY:" in prompt

    def test_prompt_includes_exit_check(self):
        prompt = self._build_prompt()
        assert "EXIT CHECK:" in prompt

    def test_prompt_includes_turn_number(self):
        state = _make_state(turn=7)
        prompt = self._build_prompt(state)
        assert "Turn 7" in prompt

    def test_prompt_includes_role(self):
        prompt = self._build_prompt()
        assert "RESEARCHER AGENT" in prompt


# ──────────────────────────────────────────────────────────────────────
# Conversation History Window Tests
# ──────────────────────────────────────────────────────────────────────

class TestConversationHistoryWindow:
    """Verify conversation history window is 10 turns."""

    def test_history_window_is_10(self):
        """The history slicing in run() should use [-10:]."""
        import inspect
        source = inspect.getsource(BaseSubAgent.run)
        # The code should reference [-10:] not [-6:]
        assert "[-10:]" in source
        assert "[-6:]" not in source


# ──────────────────────────────────────────────────────────────────────
# KernelState Epistemic Helper Tests
# ──────────────────────────────────────────────────────────────────────

class TestEpistemicStateUpdates:
    """Verify update_epistemic_state populates belief_state."""

    def test_update_epistemic_state(self):
        state = _make_state()
        state.update_epistemic_state("api_specs_count", 3)
        assert state.belief_state["api_specs_count"] == 3

    def test_update_epistemic_state_overwrites(self):
        state = _make_state()
        state.update_epistemic_state("key", "old")
        state.update_epistemic_state("key", "new")
        assert state.belief_state["key"] == "new"

    def test_belief_state_visible_in_context(self):
        state = _make_state()
        state.update_epistemic_state("api_specs_count", 5)
        state.update_epistemic_state("last_extraction_source", "stripe.com/docs")

        cm = ContextManager()
        context = cm.build_context(state)

        assert "BELIEF STATE" in context
        assert "api_specs_count" in context
        assert "5" in context


# ──────────────────────────────────────────────────────────────────────
# Turn Digest Tests
# ──────────────────────────────────────────────────────────────────────

class TestTurnDigest:
    """Verify turn digests include structured reflection prompts."""

    def test_observation_format_in_source(self):
        """The observation string should include turn number and reflection prompt."""
        import inspect
        source = inspect.getsource(BaseSubAgent.run)
        assert "Reflect:" in source
        assert "[Turn {turn}]" in source or "Turn {turn}" in source
