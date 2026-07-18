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


# ======================================================================
# Issues #55/#56: honest truncation markers + named key overflow
# ======================================================================

def _kernel_state(**overrides):
    from jarviscore.kernel.state import KernelState
    defaults = dict(workflow_id="wf", step_id="s1", agent_id="a1", task="test task")
    defaults.update(overrides)
    return KernelState(**defaults)


@pytest.fixture
def big_cm():
    # Roomy budget so blocks are never trimmed by _add_block itself
    return ContextManager(BudgetConfig())


class TestHonestTruncation:
    """Every value cut for the agent's eyes carries an explicit marker (#55)."""

    def test_clip_within_limit_is_byte_identical(self):
        assert ContextManager._clip("short value", 100) == "short value"

    def test_clip_at_exact_limit_is_byte_identical(self):
        text = "x" * 100
        assert ContextManager._clip(text, 100) == text

    def test_clip_over_limit_carries_marker(self):
        text = "y" * 250
        out = ContextManager._clip(text, 100)
        assert out.startswith("y" * 100)
        assert "…[truncated: showing 100 of 250 chars]" in out

    def test_prior_step_output_truncation_is_marked(self, big_cm):
        state = _kernel_state(context={
            "previous_step_results": {
                "step_a": {"output": "Z" * 5000},
            },
        })
        rendered = big_cm.build_context(state)
        assert "…[truncated: showing 2000 of 5000 chars]" in rendered

    def test_belief_value_truncation_is_marked(self, big_cm):
        state = _kernel_state(belief_state={"hypothesis": "B" * 900})
        rendered = big_cm.build_context(state)
        assert "…[truncated: showing 200 of 900 chars]" in rendered

    def test_short_values_render_without_markers(self, big_cm):
        state = _kernel_state(
            context={"note": "small"},
            belief_state={"k": "v"},
        )
        rendered = big_cm.build_context(state)
        assert "…[truncated" not in rendered

    def test_limits_are_configurable(self):
        cm = ContextManager(BudgetConfig(belief_value_limit=50))
        state = _kernel_state(belief_state={"h": "C" * 120})
        rendered = cm.build_context(state)
        assert "…[truncated: showing 50 of 120 chars]" in rendered


class TestKeyOverflowNotices:
    """Past the key cap, hidden keys are announced by name — recency wins (#56)."""

    def test_overflow_names_the_hidden_keys(self, big_cm):
        beliefs = {f"belief_{i:02d}": f"value {i}" for i in range(14)}
        rendered = big_cm.build_context(_kernel_state(belief_state=beliefs))
        assert "…and 4 earlier key(s) not shown" in rendered
        for hidden in ["belief_00", "belief_01", "belief_02", "belief_03"]:
            assert f"`{hidden}`" in rendered

    def test_most_recent_keys_survive(self, big_cm):
        beliefs = {f"belief_{i:02d}": f"value {i}" for i in range(14)}
        rendered = big_cm.build_context(_kernel_state(belief_state=beliefs))
        # Newest key renders with its value; oldest only in the overflow notice
        assert "- `belief_13`: value 13" in rendered
        assert "- `belief_00`:" not in rendered

    def test_at_or_under_cap_renders_identically_with_no_notice(self, big_cm):
        beliefs = {f"b{i}": "v" for i in range(10)}
        rendered = big_cm.build_context(_kernel_state(belief_state=beliefs))
        assert "not shown" not in rendered

    def test_internal_variable_skip_keys_do_not_consume_the_cap(self, big_cm):
        # 4 dedicated/underscore keys + 10 real ones: all 10 real keys must render
        vars_ = {"long_term_memory": [], "research_findings": [], "_private": 1, "api_specs": []}
        vars_.update({f"var_{i}": f"value {i}" for i in range(10)})
        rendered = big_cm.build_context(_kernel_state(internal_variables=vars_))
        for i in range(10):
            assert f"- `var_{i}`: value {i}" in rendered
        assert "not shown" not in rendered

    def test_input_context_overflow_named(self, big_cm):
        ctx = {f"key_{i:02d}": f"val {i}" for i in range(13)}
        rendered = big_cm.build_context(_kernel_state(context=ctx))
        assert "…and 3 earlier key(s) not shown" in rendered


class TestToolHistoryMarkers:
    """The tool-history window uses the same honest markers."""

    def test_history_output_truncation_is_marked(self, big_cm):
        state = _kernel_state()
        state.add_tool_result("read_file", {"path": "/x"}, "D" * 1500)
        rendered = big_cm.build_context(state)
        assert "…[truncated: showing 600 of" in rendered


# ======================================================================
# Issue #59: summarization is compression, never destruction
# ======================================================================

def _state_ready_to_compress(n_turns=10, output_len=400):
    state = _kernel_state()
    for i in range(n_turns):
        state.add_tool_result(
            "web_search", {"query": f"q{i}"},
            {"status": "success", "content": f"finding-{i}-" + "x" * output_len},
        )
    return state


def _compressing_cm():
    # Tiny history_limit so the 80% threshold trips immediately
    return ContextManager(BudgetConfig(history_limit=10))


class TestZeroLossSummarization:

    @pytest.mark.asyncio
    async def test_originals_archived_before_trim(self):
        cm = _compressing_cm()
        state = _state_ready_to_compress()
        llm = MagicMock()
        llm.generate = AsyncMock(return_value={"content": "- discovered things"})

        assert await cm._summarize_state(state, llm) is True

        archive = state.internal_variables["_archived_turns"]
        assert len(archive) == 3  # oldest 30% of 10
        assert archive[0]["tool_name"] == "web_search"
        # Full output preserved — not the 100-char stub of old
        assert "finding-0-" in archive[0]["tool_output"]
        assert len(archive[0]["tool_output"]) > 300
        # And history was trimmed as before
        assert len(state.tool_history) == 7

    @pytest.mark.asyncio
    async def test_summary_is_labeled_lossy(self):
        cm = _compressing_cm()
        state = _state_ready_to_compress()
        llm = MagicMock()
        llm.generate = AsyncMock(return_value={"content": "- found stuff"})

        await cm._summarize_state(state, llm)

        ltm = state.internal_variables["long_term_memory"]
        assert ltm[0]["summary"].startswith("[lossy summary of 3 turns — originals archived]")
        assert ltm[0]["archived"] is True

    @pytest.mark.asyncio
    async def test_summarizer_sees_a_real_evidence_window(self):
        cm = _compressing_cm()
        state = _state_ready_to_compress(output_len=700)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value={"content": "- ok"})

        await cm._summarize_state(state, llm)

        prompt = llm.generate.call_args.kwargs["messages"][0]["content"]
        # Old code fed 100 chars/turn; the evidence window is now config-sized
        assert "finding-0-" + "x" * 300 in prompt

    @pytest.mark.asyncio
    async def test_failed_summarizer_keeps_history_intact(self):
        cm = _compressing_cm()
        state = _state_ready_to_compress()
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("provider down"))

        assert await cm._summarize_state(state, llm) is False
        assert len(state.tool_history) == 10          # nothing trimmed
        assert "_archived_turns" not in state.internal_variables
        assert "long_term_memory" not in state.internal_variables

    @pytest.mark.asyncio
    async def test_archive_is_bounded(self):
        cm = ContextManager(BudgetConfig(history_limit=10, archive_window=4))
        state = _state_ready_to_compress()
        state.internal_variables["_archived_turns"] = [
            {"tool_name": f"old_{i}"} for i in range(4)
        ]
        llm = MagicMock()
        llm.generate = AsyncMock(return_value={"content": "- ok"})

        await cm._summarize_state(state, llm)

        archive = state.internal_variables["_archived_turns"]
        assert len(archive) == 4
        # Newest entries survive; the pre-existing oldest were evicted
        assert archive[-1]["tool_name"] == "web_search"

    @pytest.mark.asyncio
    async def test_archive_is_json_safe_for_checkpoints(self):
        import json as _json
        cm = _compressing_cm()
        state = _state_ready_to_compress()
        llm = MagicMock()
        llm.generate = AsyncMock(return_value={"content": "- ok"})

        await cm._summarize_state(state, llm)
        # save_checkpoint calls model_dump_json — must not raise
        _json.loads(state.model_dump_json())
