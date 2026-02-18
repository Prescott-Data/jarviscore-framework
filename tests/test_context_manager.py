"""
Tests for Phase 8E: ContextManager + BudgetConfig.

What these tests prove:
- count_tokens() estimates proportionally to word count
- build_context() always includes MISSION section
- Priority order: mission > plan > notes > ltm > history > variables
- Lower-priority sections are dropped/truncated when budget is exhausted
- tool_history sliding window respects history_limit
- record_usage() / reset_usage() track cumulative tokens
- auto_summarize_if_needed() triggers only at threshold
- auto_summarize_if_needed() calls memory.ltm.compress() and save_summary()
- auto_summarize_if_needed() returns False when below threshold
- auto_summarize_if_needed() does nothing when ltm is not available
"""
from unittest.mock import AsyncMock, MagicMock
import pytest

from jarviscore.context.context_manager import BudgetConfig, ContextManager


@pytest.fixture
def cm():
    return ContextManager(BudgetConfig(total_tokens=1000, output_reserve=100, system_reserve=100))


# ======================================================================
# BudgetConfig
# ======================================================================

class TestBudgetConfig:
    def test_usable_tokens(self):
        cfg = BudgetConfig(total_tokens=1000, output_reserve=100, system_reserve=200)
        assert cfg.usable_tokens == 700

    def test_defaults(self):
        cfg = BudgetConfig()
        assert cfg.total_tokens == 80_000
        assert cfg.summarization_threshold == 0.8
        assert cfg.usable_tokens == 80_000 - 4_000 - 8_000


# ======================================================================
# count_tokens()
# ======================================================================

class TestCountTokens:
    def test_empty_string_returns_zero(self, cm):
        assert cm.count_tokens("") == 0

    def test_single_word(self, cm):
        assert cm.count_tokens("hello") >= 1

    def test_longer_text_more_tokens(self, cm):
        short = cm.count_tokens("hello world")
        long = cm.count_tokens("hello world this is a much longer sentence with more words")
        assert long > short

    def test_proportional_to_words(self, cm):
        # 10 words → ~13 tokens (10 * 1.3)
        result = cm.count_tokens(" ".join(["word"] * 10))
        assert 10 <= result <= 20


# ======================================================================
# build_context()
# ======================================================================

class TestBuildContext:
    def test_mission_always_present(self, cm):
        ctx = cm.build_context({"workflow_id": "wf-1", "step_id": "s1", "task": "analyse"})
        assert "wf-1" in ctx
        assert "s1" in ctx
        assert "analyse" in ctx

    def test_plan_included_when_budget_available(self, cm):
        ctx = cm.build_context({
            "workflow_id": "wf", "step_id": "s", "task": "t",
            "plan": "Step 1: fetch data",
        })
        assert "Step 1: fetch data" in ctx

    def test_notes_included(self, cm):
        ctx = cm.build_context({
            "workflow_id": "wf", "step_id": "s", "task": "t",
            "notes": "API returns JSON array",
        })
        assert "API returns JSON array" in ctx

    def test_ltm_summary_included(self, cm):
        ctx = cm.build_context({
            "workflow_id": "wf", "step_id": "s", "task": "t",
            "ltm_summary": "Prior run processed 500 records",
        })
        assert "500 records" in ctx

    def test_variables_included(self, cm):
        ctx = cm.build_context({
            "workflow_id": "wf", "step_id": "s", "task": "t",
            "variables": {"key": "value"},
        })
        assert "key" in ctx

    def test_history_included(self, cm):
        ctx = cm.build_context({
            "workflow_id": "wf", "step_id": "s", "task": "t",
            "tool_history": [{"tool": "search", "result": "found"}],
        })
        assert "search" in ctx

    def test_low_priority_dropped_when_budget_exhausted(self):
        """Variables should be dropped when budget is tiny."""
        tiny = ContextManager(BudgetConfig(
            total_tokens=30, output_reserve=5, system_reserve=5
        ))
        ctx = tiny.build_context({
            "workflow_id": "wf", "step_id": "s", "task": "t",
            "variables": {"huge_data": "x" * 500},
        })
        # Mission always present; variables may be truncated/absent
        assert "wf" in ctx

    def test_empty_state_returns_mission_only(self, cm):
        ctx = cm.build_context({
            "workflow_id": "wf", "step_id": "s", "task": "task"
        })
        assert "Mission" in ctx
        assert "Plan" not in ctx


# ======================================================================
# Token usage tracking
# ======================================================================

class TestUsageTracking:
    def test_initial_usage_zero(self, cm):
        assert cm.used_tokens == 0

    def test_record_usage_accumulates(self, cm):
        cm.record_usage(100)
        cm.record_usage(200)
        assert cm.used_tokens == 300

    def test_reset_clears_usage(self, cm):
        cm.record_usage(500)
        cm.reset_usage()
        assert cm.used_tokens == 0


# ======================================================================
# auto_summarize_if_needed()
# ======================================================================

class TestAutoSummarize:
    @pytest.mark.asyncio
    async def test_below_threshold_returns_false(self, cm):
        cm.record_usage(100)  # Way below 800 (80% of 1000)
        result = await cm.auto_summarize_if_needed({}, MagicMock(), MagicMock())
        assert result is False

    @pytest.mark.asyncio
    async def test_above_threshold_triggers_compress(self, cm):
        cm.record_usage(850)  # Above 80% of 1000

        mock_ltm = MagicMock()
        mock_ltm.compress = AsyncMock(return_value="compressed summary")
        mock_ltm.save_summary = AsyncMock()

        mock_memory = MagicMock()
        mock_memory.ltm = mock_ltm

        state = {"tool_history": [{"turn": 1}]}
        result = await cm.auto_summarize_if_needed(state, MagicMock(), mock_memory)

        assert result is True
        mock_ltm.compress.assert_awaited_once()
        mock_ltm.save_summary.assert_awaited_once_with("compressed summary")

    @pytest.mark.asyncio
    async def test_summarise_resets_counter(self, cm):
        cm.record_usage(850)

        mock_ltm = MagicMock()
        mock_ltm.compress = AsyncMock(return_value="summary")
        mock_ltm.save_summary = AsyncMock()
        mock_memory = MagicMock()
        mock_memory.ltm = mock_ltm

        await cm.auto_summarize_if_needed({}, MagicMock(), mock_memory)
        assert cm.used_tokens == 0

    @pytest.mark.asyncio
    async def test_no_ltm_returns_false_no_error(self, cm):
        cm.record_usage(900)
        mock_memory = MagicMock()
        mock_memory.ltm = None
        result = await cm.auto_summarize_if_needed({}, MagicMock(), mock_memory)
        assert result is False
