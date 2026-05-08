"""
Tests for EpistemicLedger — deterministic enforcement of reasoning consistency.

Tests validate that:
1. Search dedup blocks semantically duplicate queries
2. URL dedup blocks re-reading the same page
3. Knowledge plateau detects stagnation
4. The ledger is wired into the OODA loop (source-level verification)
5. Failed tool calls do NOT block retries
"""

import pytest
from jarviscore.kernel.epistemic import EpistemicLedger, ValidationResult, _SearchRecord
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
# Search Dedup Tests
# ──────────────────────────────────────────────────────────────────

class TestSearchDedup:
    """Validates that semantically duplicate search queries are blocked."""

    def test_first_search_always_allowed(self):
        ledger = EpistemicLedger()
        result = ledger.validate_action(
            "search_internet", {"query": "Stripe API authentication docs"}, 1, None
        )
        assert result.action == "allow"

    def test_exact_duplicate_blocked_after_recording(self):
        ledger = EpistemicLedger()
        params = {"query": "Stripe API authentication docs"}
        # First call — allowed + recorded
        assert ledger.validate_action("search_internet", params, 1, None).action == "allow"
        ledger.record_outcome("search_internet", params, {"status": "ok"}, 1, None)
        # Second call — blocked
        result = ledger.validate_action("search_internet", params, 2, None)
        assert result.action == "redirect"
        assert "REDUNDANT_SEARCH" in result.reason

    def test_near_duplicate_blocked(self):
        """'Stripe API auth' ≈ 'Stripe REST API authentication'"""
        ledger = EpistemicLedger()
        p1 = {"query": "Stripe API authentication"}
        ledger.validate_action("search_internet", p1, 1, None)
        ledger.record_outcome("search_internet", p1, {"status": "ok"}, 1, None)

        p2 = {"query": "Stripe REST API authentication"}
        result = ledger.validate_action("search_internet", p2, 2, None)
        # These share 75% Jaccard similarity → blocked
        assert result.action == "redirect"

    def test_different_api_allowed(self):
        """'Stripe API' vs 'Shopify API' should NOT be blocked."""
        ledger = EpistemicLedger()
        p1 = {"query": "Stripe API authentication"}
        ledger.validate_action("search_internet", p1, 1, None)
        ledger.record_outcome("search_internet", p1, {"status": "ok"}, 1, None)

        p2 = {"query": "Shopify API authentication"}
        result = ledger.validate_action("search_internet", p2, 2, None)
        assert result.action == "allow"

    def test_batch_search_dedup(self):
        """search_internet_batch queries are checked individually."""
        ledger = EpistemicLedger()
        p1 = {"query": "Stripe customer endpoint"}
        ledger.validate_action("search_internet", p1, 1, None)
        ledger.record_outcome("search_internet", p1, {"status": "ok"}, 1, None)

        p2 = {"queries": ["Shopify payments API", "Stripe customer endpoint details"]}
        result = ledger.validate_action("search_internet_batch", p2, 2, None)
        # Second query in batch matches the recorded one
        assert result.action == "redirect"
        assert "Stripe" in result.reason

    def test_non_search_tool_passes_through(self):
        """Tools without search semantics are never blocked."""
        ledger = EpistemicLedger()
        result = ledger.validate_action(
            "extract_api_details", {"text": "anything"}, 1, None
        )
        assert result.action == "allow"

    def test_empty_query_not_recorded(self):
        """Empty or stop-word-only queries should not poison the history."""
        ledger = EpistemicLedger()
        p = {"query": "the and or"}
        ledger.validate_action("search_internet", p, 1, None)
        ledger.record_outcome("search_internet", p, {"status": "ok"}, 1, None)
        assert len(ledger._search_history) == 0


# ──────────────────────────────────────────────────────────────────
# URL Dedup Tests
# ──────────────────────────────────────────────────────────────────

class TestURLDedup:
    """Validates that re-reading the same URL is blocked."""

    def test_first_url_read_allowed(self):
        ledger = EpistemicLedger()
        result = ledger.validate_action(
            "read_web_content",
            {"urls": ["https://stripe.com/docs/api"]},
            1, None,
        )
        assert result.action == "allow"

    def test_exact_url_blocked_after_recording(self):
        ledger = EpistemicLedger()
        params = {"urls": ["https://stripe.com/docs/api"]}
        ledger.validate_action("read_web_content", params, 1, None)
        ledger.record_outcome("read_web_content", params, {"status": "ok"}, 1, None)

        result = ledger.validate_action("read_web_content", params, 2, None)
        assert result.action == "redirect"
        assert "REDUNDANT_URL" in result.reason

    def test_url_with_tracking_params_deduplicated(self):
        """URLs differing only in UTM params should be treated as same."""
        ledger = EpistemicLedger()
        p1 = {"urls": ["https://stripe.com/docs/api?utm_source=google"]}
        ledger.validate_action("read_web_content", p1, 1, None)
        ledger.record_outcome("read_web_content", p1, {"status": "ok"}, 1, None)

        p2 = {"urls": ["https://stripe.com/docs/api?utm_source=twitter"]}
        result = ledger.validate_action("read_web_content", p2, 2, None)
        assert result.action == "redirect"

    def test_url_with_fragment_deduplicated(self):
        """URLs differing only in fragment should be treated as same."""
        ledger = EpistemicLedger()
        p1 = {"urls": ["https://stripe.com/docs/api#authentication"]}
        ledger.validate_action("read_web_content", p1, 1, None)
        ledger.record_outcome("read_web_content", p1, {"status": "ok"}, 1, None)

        p2 = {"urls": ["https://stripe.com/docs/api#payments"]}
        result = ledger.validate_action("read_web_content", p2, 2, None)
        assert result.action == "redirect"

    def test_different_url_allowed(self):
        ledger = EpistemicLedger()
        p1 = {"urls": ["https://stripe.com/docs/api"]}
        ledger.validate_action("read_web_content", p1, 1, None)
        ledger.record_outcome("read_web_content", p1, {"status": "ok"}, 1, None)

        p2 = {"urls": ["https://stripe.com/docs/payments"]}
        result = ledger.validate_action("read_web_content", p2, 2, None)
        assert result.action == "allow"

    def test_browser_navigate_dedup(self):
        ledger = EpistemicLedger()
        p1 = {"url": "https://example.com/page"}
        ledger.validate_action("browser_navigate", p1, 1, None)
        ledger.record_outcome("browser_navigate", p1, {"status": "ok"}, 1, None)

        result = ledger.validate_action("browser_navigate", p1, 2, None)
        assert result.action == "redirect"

    def test_urls_from_result_also_tracked(self):
        """URLs extracted from tool results should also be deduplicated."""
        ledger = EpistemicLedger()
        # Simulate a tool result that reveals a URL
        ledger.record_outcome(
            "search_internet",
            {"query": "Stripe docs"},
            {"url": "https://stripe.com/docs/api", "status": "ok"},
            1, None,
        )

        # Now trying to read that URL should be blocked
        p2 = {"urls": ["https://stripe.com/docs/api"]}
        result = ledger.validate_action("read_web_content", p2, 2, None)
        assert result.action == "redirect"


# ──────────────────────────────────────────────────────────────────
# Failed Tool Retry Tests
# ──────────────────────────────────────────────────────────────────

class TestFailedRetries:
    """Failed tool calls should NOT block retries."""

    def test_failed_search_allows_retry(self):
        ledger = EpistemicLedger()
        params = {"query": "Stripe API docs"}
        ledger.validate_action("search_internet", params, 1, None)
        # Record as FAILED — should NOT be added to history
        ledger.record_outcome(
            "search_internet", params,
            {"status": "error", "error": "timeout"}, 1, None,
        )

        # Retry should be allowed
        result = ledger.validate_action("search_internet", params, 2, None)
        assert result.action == "allow"

    def test_failed_url_allows_retry(self):
        ledger = EpistemicLedger()
        params = {"urls": ["https://stripe.com/docs"]}
        ledger.validate_action("read_web_content", params, 1, None)
        ledger.record_outcome(
            "read_web_content", params,
            {"status": "error", "error": "403 Forbidden"}, 1, None,
        )

        result = ledger.validate_action("read_web_content", params, 2, None)
        assert result.action == "allow"


# ──────────────────────────────────────────────────────────────────
# Knowledge Plateau Tests
# ──────────────────────────────────────────────────────────────────

class TestKnowledgePlateau:
    """Validates plateau detection when knowledge stops growing."""

    def test_no_plateau_when_growing(self):
        """Knowledge growing each turn → no signal."""
        ledger = EpistemicLedger()
        state = _make_state()
        state.internal_variables["research_findings"] = []
        state.internal_variables["api_specs"] = []

        for turn in range(5):
            state.internal_variables["research_findings"].append(
                {"summary": f"Finding {turn}"}
            )
            signal = ledger.check_plateau(state, turn)
            assert signal is None

    def test_plateau_after_3_flat_turns(self):
        """No new knowledge for 3 turns → plateau signal."""
        ledger = EpistemicLedger()
        state = _make_state()
        state.internal_variables["research_findings"] = [{"summary": "only one"}]

        # 3 consecutive turns with no new findings
        for turn in range(3):
            signal = ledger.check_plateau(state, turn)
        assert signal is not None
        assert "KNOWLEDGE_PLATEAU" in signal

    def test_no_plateau_under_threshold(self):
        """Less than 3 flat turns → no signal yet."""
        ledger = EpistemicLedger()
        state = _make_state()
        state.internal_variables["research_findings"] = [{"summary": "one"}]

        signal_1 = ledger.check_plateau(state, 0)
        signal_2 = ledger.check_plateau(state, 1)
        assert signal_1 is None
        assert signal_2 is None

    def test_plateau_resets_on_growth(self):
        """After plateau, adding knowledge should reset the signal."""
        ledger = EpistemicLedger()
        state = _make_state()
        state.internal_variables["research_findings"] = [{"summary": "one"}]

        # 3 flat turns → plateau
        for turn in range(3):
            ledger.check_plateau(state, turn)

        # Add a finding → no plateau on next check
        state.internal_variables["research_findings"].append({"summary": "two"})
        signal = ledger.check_plateau(state, 3)
        assert signal is None


# ──────────────────────────────────────────────────────────────────
# OODA Integration Tests (source-level verification)
# ──────────────────────────────────────────────────────────────────

class TestOODAIntegration:
    """Verify the EpistemicLedger is wired into BaseSubAgent.run()."""

    def test_ledger_created_in_run(self):
        """run() should instantiate EpistemicLedger."""
        import inspect
        from jarviscore.kernel.subagent import BaseSubAgent
        source = inspect.getsource(BaseSubAgent.run)
        assert "EpistemicLedger()" in source

    def test_validate_action_called_before_execute(self):
        """validate_action() must appear BEFORE _execute_tool()."""
        import inspect
        from jarviscore.kernel.subagent import BaseSubAgent
        source = inspect.getsource(BaseSubAgent.run)
        validate_pos = source.index("validate_action")
        execute_pos = source.index("_execute_tool")
        assert validate_pos < execute_pos

    def test_record_outcome_called_after_execute(self):
        """record_outcome() must appear AFTER _execute_tool()."""
        import inspect
        from jarviscore.kernel.subagent import BaseSubAgent
        source = inspect.getsource(BaseSubAgent.run)
        execute_pos = source.index("_execute_tool")
        record_pos = source.index("record_outcome")
        assert record_pos > execute_pos

    def test_check_plateau_called_after_record(self):
        """check_plateau() must appear AFTER record_outcome()."""
        import inspect
        from jarviscore.kernel.subagent import BaseSubAgent
        source = inspect.getsource(BaseSubAgent.run)
        record_pos = source.index("record_outcome")
        plateau_pos = source.index("check_plateau")
        assert plateau_pos > record_pos

    def test_redirect_injects_into_state(self):
        """On redirect, the source should add_thought and add_tool_result."""
        import inspect
        from jarviscore.kernel.subagent import BaseSubAgent
        source = inspect.getsource(BaseSubAgent.run)
        # Find the redirect block
        redirect_block = source[source.index("ep_verdict.action"):]
        assert "add_thought" in redirect_block
        assert "add_tool_result" in redirect_block
        assert "epistemic_redirect" in redirect_block


# ──────────────────────────────────────────────────────────────────
# Normalisation Edge Cases
# ──────────────────────────────────────────────────────────────────

class TestNormalisation:
    """Edge cases in query and URL normalisation."""

    def test_query_case_insensitive(self):
        ledger = EpistemicLedger()
        p1 = {"query": "STRIPE API DOCS"}
        ledger.validate_action("search_internet", p1, 1, None)
        ledger.record_outcome("search_internet", p1, {"status": "ok"}, 1, None)

        p2 = {"query": "stripe api docs"}
        result = ledger.validate_action("search_internet", p2, 2, None)
        assert result.action == "redirect"

    def test_url_trailing_slash_normalised(self):
        ledger = EpistemicLedger()
        p1 = {"urls": ["https://stripe.com/docs/"]}
        ledger.validate_action("read_web_content", p1, 1, None)
        ledger.record_outcome("read_web_content", p1, {"status": "ok"}, 1, None)

        p2 = {"urls": ["https://stripe.com/docs"]}
        result = ledger.validate_action("read_web_content", p2, 2, None)
        assert result.action == "redirect"

    def test_url_case_normalised(self):
        ledger = EpistemicLedger()
        p1 = {"urls": ["https://STRIPE.COM/Docs/API"]}
        ledger.validate_action("read_web_content", p1, 1, None)
        ledger.record_outcome("read_web_content", p1, {"status": "ok"}, 1, None)

        p2 = {"urls": ["https://stripe.com/docs/api"]}
        result = ledger.validate_action("read_web_content", p2, 2, None)
        assert result.action == "redirect"

    def test_jaccard_edge_empty_sets(self):
        """Both empty word sets → Jaccard = 1.0 (identical nothingness)."""
        assert EpistemicLedger._jaccard(frozenset(), frozenset()) == 1.0
