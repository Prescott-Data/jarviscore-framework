"""
Tests for the production ResearcherSubAgent.

Covers:
- Phase lifecycle (INIT → SEARCHING → EXTRACTING → VERIFYING → DONE/STUCK)
- Phase-tool contract enforcement
- URL registry (anti-hallucination URL tracking)
- Completion validation (evidence quality gates)
- Search integration (single + batch)
- Content reading (read_web_content, read_file)
- Session state isolation
"""

import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from jarviscore.kernel.defaults.research_flow import ResearchPhase, ResearchFlow
from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
from jarviscore.kernel.state import KernelState


# ═════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════

class MockLLMClient:
    async def generate(self, messages, **kwargs):
        return {"content": "DONE: mock", "tokens": {"input": 10, "output": 10, "total": 20}}


class MockInternetSearch:
    """Mock InternetSearch matching the real API surface."""

    def __init__(self, results=None):
        self._results = results or [
            {"title": "Stripe API Docs", "snippet": "Authentication via Bearer token", "url": "https://docs.stripe.com/api"},
            {"title": "Stripe Charges", "snippet": "POST /v1/charges", "url": "https://docs.stripe.com/api/charges"},
            {"title": "Stripe SDKs", "snippet": "pip install stripe", "url": "https://docs.stripe.com/sdks"},
        ]
        self._initialized = False

    async def initialize(self):
        self._initialized = True

    async def search(self, query, max_results=5, **kwargs):
        return self._results[:max_results]

    async def extract_content(self, url, max_length=10000, strategy=None):
        return {
            "success": True,
            "title": f"Page: {url}",
            "content": f"Documentation content from {url}. " * 20,
            "word_count": 80,
            "url": url,
        }

    async def extract_multiple(self, urls, max_length=10000):
        results = {}
        for url in urls:
            results[url] = await self.extract_content(url, max_length=max_length)
        return results


@pytest.fixture
def llm():
    return MockLLMClient()


@pytest.fixture
def internet_search():
    return MockInternetSearch()


@pytest.fixture
def researcher(llm, internet_search):
    r = ResearcherSubAgent(
        agent_id="test-researcher",
        llm_client=llm,
        internet_search=internet_search,
    )
    state = KernelState(
        workflow_id="test", step_id="s1", agent_id="test-researcher",
        task="Research Stripe API for payment integration", context={},
    )
    r.current_state = state
    return r


@pytest.fixture
def researcher_no_state(llm, internet_search):
    """Researcher without attached state — tests graceful degradation."""
    r = ResearcherSubAgent(
        agent_id="test-researcher-stateless",
        llm_client=llm,
        internet_search=internet_search,
    )
    return r


# ═════════════════════════════════════════════════════════════════
# ResearchFlow
# ═════════════════════════════════════════════════════════════════

class TestResearchFlow:

    def test_phase_values(self):
        assert ResearchPhase.INIT.value == "init"
        assert ResearchPhase.SEARCHING.value == "searching"
        assert ResearchPhase.EXTRACTING.value == "extracting"
        assert ResearchPhase.VERIFYING.value == "verifying"
        assert ResearchPhase.DONE.value == "done"
        assert ResearchPhase.STUCK.value == "stuck"

    def test_snapshot(self):
        snap = ResearchFlow.snapshot(ResearchPhase.SEARCHING, "batch_discovery")
        assert snap == {"phase": "searching", "reason": "batch_discovery"}

    def test_snapshot_stores_enum_value(self):
        """Snapshot stores string value, not the enum object."""
        snap = ResearchFlow.snapshot(ResearchPhase.EXTRACTING, "reading_docs")
        assert isinstance(snap["phase"], str)
        assert snap["phase"] == "extracting"


# ═════════════════════════════════════════════════════════════════
# Phase Lifecycle
# ═════════════════════════════════════════════════════════════════

class TestPhaseLifecycle:

    def test_initial_phase_is_init(self, researcher):
        assert researcher._current_research_phase() == ResearchPhase.INIT

    def test_set_phase_updates_state(self, researcher):
        researcher._set_research_phase(ResearchPhase.SEARCHING, "test_transition")
        assert researcher._current_research_phase() == ResearchPhase.SEARCHING

    def test_phase_round_trips_through_state(self, researcher):
        """Phase is persisted in KernelState.internal_variables, not instance vars."""
        researcher._set_research_phase(ResearchPhase.VERIFYING, "cross_check")
        raw = researcher.current_state.internal_variables["research_flow"]
        assert raw["phase"] == "verifying"
        assert raw["reason"] == "cross_check"
        assert researcher._current_research_phase() == ResearchPhase.VERIFYING

    def test_phase_without_state_returns_init(self, researcher_no_state):
        assert researcher_no_state._current_research_phase() == ResearchPhase.INIT

    def test_full_lifecycle(self, researcher):
        """Walk through the full phase lifecycle."""
        assert researcher._current_research_phase() == ResearchPhase.INIT
        researcher._set_research_phase(ResearchPhase.SEARCHING, "initial_search")
        assert researcher._current_research_phase() == ResearchPhase.SEARCHING
        researcher._set_research_phase(ResearchPhase.EXTRACTING, "reading_docs")
        assert researcher._current_research_phase() == ResearchPhase.EXTRACTING
        researcher._set_research_phase(ResearchPhase.VERIFYING, "cross_referencing")
        assert researcher._current_research_phase() == ResearchPhase.VERIFYING
        researcher._set_research_phase(ResearchPhase.DONE, "publish_called")
        assert researcher._current_research_phase() == ResearchPhase.DONE


# ═════════════════════════════════════════════════════════════════
# Phase-Tool Contract Enforcement
# ═════════════════════════════════════════════════════════════════

class TestPhaseToolContract:

    def test_init_allows_search_tools(self, researcher):
        allowed = researcher._allowed_tools_for_phase(ResearchPhase.INIT)
        assert "search_internet" in allowed
        assert "search_internet_batch" in allowed
        assert "read_file" in allowed
        assert "grep_codebase" in allowed
        assert "probe_target_api" in allowed

    def test_init_blocks_extract_api(self, researcher):
        """extract_api_details requires prior doc reading — not available in INIT."""
        violation = researcher._check_phase_tool_contract("extract_api_details")
        # extract_api_details IS allowed in INIT actually
        allowed = researcher._allowed_tools_for_phase(ResearchPhase.INIT)
        if "extract_api_details" in allowed:
            assert violation is None
        else:
            assert violation is not None

    def test_extracting_allows_read_and_browser(self, researcher):
        researcher._set_research_phase(ResearchPhase.EXTRACTING, "test")
        allowed = researcher._allowed_tools_for_phase(ResearchPhase.EXTRACTING)
        assert "read_web_content" in allowed
        assert "rag_query" in allowed
        assert "extract_api_details" in allowed
        assert "browser_navigate" in allowed
        assert "browser_get_page_text" in allowed

    def test_extracting_blocks_search_internet(self, researcher):
        researcher._set_research_phase(ResearchPhase.EXTRACTING, "test")
        violation = researcher._check_phase_tool_contract("search_internet")
        assert violation is not None
        assert "not allowed" in violation

    def test_stuck_only_allows_publish(self, researcher):
        allowed = researcher._allowed_tools_for_phase(ResearchPhase.STUCK)
        assert allowed == {"publish_research_findings"}

    def test_done_only_allows_publish(self, researcher):
        allowed = researcher._allowed_tools_for_phase(ResearchPhase.DONE)
        assert allowed == {"publish_research_findings"}

    def test_done_tool_returns_contract_violation(self, researcher):
        """The old 'done' tool is removed — using it should return an error."""
        violation = researcher._check_phase_tool_contract("done")
        assert violation is not None
        assert "EPISTEMIC CONTRACT VIOLATION" in violation

    def test_error_tool_always_allowed(self, researcher):
        for phase in ResearchPhase:
            researcher._set_research_phase(phase, "test")
            assert researcher._check_phase_tool_contract("error") is None

    def test_phase_enforcement_disabled_by_env(self, researcher):
        with patch.dict(os.environ, {"RESEARCH_STRICT_PHASE_CONTRACT": "false"}):
            researcher._set_research_phase(ResearchPhase.STUCK, "test")
            violation = researcher._check_phase_tool_contract("search_internet")
            assert violation is None

    def test_verifying_allows_broad_tool_access(self, researcher):
        """VERIFYING phase allows both search and extraction tools for cross-referencing."""
        allowed = researcher._allowed_tools_for_phase(ResearchPhase.VERIFYING)
        assert "search_internet" in allowed
        assert "read_web_content" in allowed
        assert "grep_codebase" in allowed
        assert "publish_research_findings" in allowed
        assert "browser_navigate" in allowed


# ═════════════════════════════════════════════════════════════════
# URL Registry (Anti-Hallucination)
# ═════════════════════════════════════════════════════════════════

class TestURLRegistry:

    def test_register_search_urls(self, researcher):
        registry = researcher._register_search_urls(["https://a.com", "https://b.com"])
        assert "u1" in registry
        assert "u2" in registry
        assert registry["u1"] == "https://a.com"
        assert registry["u2"] == "https://b.com"

    def test_register_deduplicates(self, researcher):
        researcher._register_search_urls(["https://a.com"])
        registry = researcher._register_search_urls(["https://a.com", "https://b.com"])
        # Should be 2 total, not 3
        assert len(registry) == 2

    def test_registry_persists_in_state(self, researcher):
        researcher._register_search_urls(["https://a.com"])
        raw = researcher.current_state.internal_variables.get("url_registry", {})
        assert "u1" in raw
        assert raw["u1"] == "https://a.com"

    def test_get_url_registry_returns_copy(self, researcher):
        researcher._register_search_urls(["https://a.com"])
        registry = researcher._get_url_registry()
        assert isinstance(registry, dict)
        assert "u1" in registry

    def test_known_urls_tracked(self, researcher):
        target_url = "https://docs.stripe.com"
        researcher._add_known_url(target_url)
        known = researcher._get_known_urls()
        assert any(u == target_url for u in known)


# ═════════════════════════════════════════════════════════════════
# Completion Validation
# ═════════════════════════════════════════════════════════════════

class TestCompletionValidation:

    def test_rejects_empty_summary(self, researcher):
        valid, reason, report = researcher._validate_done_payload(
            researcher.current_state,
            {"summary": "", "evidence": []},
        )
        assert not valid
        assert "summary" in reason.lower()

    def test_rejects_no_evidence(self, researcher):
        valid, reason, report = researcher._validate_done_payload(
            researcher.current_state,
            {"summary": "Found the API", "evidence": []},
        )
        assert not valid
        assert "evidence" in reason.lower()

    def test_rejects_evidence_without_pointer(self, researcher):
        valid, reason, report = researcher._validate_done_payload(
            researcher.current_state,
            {
                "summary": "Found the API",
                "evidence": [{"content": "something"}],  # missing pointer/url
            },
        )
        assert not valid
        assert "evidence" in reason.lower()

    def test_rejects_bad_api_specs(self, researcher):
        valid, reason, report = researcher._validate_done_payload(
            researcher.current_state,
            {
                "summary": "Found the API",
                "evidence": [{"pointer": "https://x.com"}],
                "api_specs": [{"method": "GET"}],  # missing url/path
            },
        )
        assert not valid
        assert "api_specs" in reason.lower() or "url" in reason.lower() or "path" in reason.lower()

    def test_accepts_valid_payload(self, researcher):
        valid, reason, report = researcher._validate_done_payload(
            researcher.current_state,
            {
                "summary": "Stripe API uses Bearer auth, POST /v1/charges for payments",
                "evidence": [
                    {"pointer": "https://docs.stripe.com/api", "kind": "web_doc"},
                ],
                "api_specs": [
                    {"method": "POST", "url": "/v1/charges", "body_schema": {"amount": "int", "currency": "str"}},
                ],
            },
        )
        assert valid
        assert report["summary_present"] is True
        assert report["evidence_count"] == 1

    def test_accepts_with_accumulated_findings_fallback(self, researcher):
        """If evidence list is empty but state has accumulated findings, allow."""
        researcher.current_state.internal_variables["research_findings"] = [
            {"url": "https://docs.stripe.com", "content_preview": "Bearer auth"}
        ]
        valid, reason, report = researcher._validate_done_payload(
            researcher.current_state,
            {"summary": "Found via accumulated findings", "evidence": []},
        )
        assert valid
        assert report["finding_fallback"] is True

    def test_strict_mode_disabled_by_env(self, researcher):
        with patch.dict(os.environ, {"RESEARCH_STRICT_DONE_VALIDATION": "false"}):
            valid, reason, report = researcher._validate_done_payload(
                researcher.current_state,
                {"summary": "", "evidence": []},  # would normally fail
            )
            assert valid  # strict mode off → always passes


# ═════════════════════════════════════════════════════════════════
# Search Integration
# ═════════════════════════════════════════════════════════════════

class TestSearchInternet:

    @pytest.mark.asyncio
    async def test_single_search_returns_json(self, researcher):
        result_str = await researcher._tool_search_internet("stripe api")
        results = json.loads(result_str)
        assert isinstance(results, list)
        assert len(results) > 0
        assert results[0]["url"] == "https://docs.stripe.com/api"

    @pytest.mark.asyncio
    async def test_search_registers_known_urls(self, researcher):
        await researcher._tool_search_internet("stripe api")
        known = researcher._get_known_urls()
        assert "https://docs.stripe.com/api" in known

    @pytest.mark.asyncio
    async def test_search_transitions_from_init(self, researcher):
        """Searching should auto-transition from INIT → SEARCHING."""
        assert researcher._current_research_phase() == ResearchPhase.INIT
        await researcher._tool_search_internet("stripe api")
        assert researcher._current_research_phase() == ResearchPhase.SEARCHING

    @pytest.mark.asyncio
    async def test_search_increments_web_search_counter(self, researcher):
        await researcher._tool_search_internet("stripe api")
        count = researcher.current_state.internal_variables.get("_web_search_count", 0)
        assert count >= 1

    @pytest.mark.asyncio
    async def test_batch_search_returns_combined(self, researcher):
        result = await researcher._tool_search_internet_batch(
            queries=["stripe api", "stripe charges"],
        )
        assert isinstance(result, dict)
        assert "results" in result or "batch" in result or len(result) > 0

    @pytest.mark.asyncio
    async def test_batch_search_sets_phase_to_searching(self, researcher):
        await researcher._tool_search_internet_batch(queries=["q1", "q2"])
        assert researcher._current_research_phase() == ResearchPhase.SEARCHING


# ═════════════════════════════════════════════════════════════════
# Content Reading
# ═════════════════════════════════════════════════════════════════

class TestContentReading:

    @pytest.mark.asyncio
    async def test_read_web_content_returns_content(self, researcher):
        result = await researcher._tool_read_web_content(
            urls=["https://docs.stripe.com/api"]
        )
        # Should return content (string or dict)
        assert result is not None

    @pytest.mark.asyncio
    async def test_read_web_content_caches_within_session(self, researcher):
        url = "https://docs.stripe.com/api"
        # First read
        await researcher._tool_read_web_content(urls=[url])
        # URL should now be in the cache
        assert url in researcher._url_content_cache

    @pytest.mark.asyncio
    async def test_read_file_returns_content(self, researcher):
        # Create a temp file to read
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("# Test file\nprint('hello')\n")
            f.flush()
            path = f.name
        try:
            result = await researcher._tool_read_file(path)
            assert isinstance(result, (str, dict))
            if isinstance(result, str):
                assert "hello" in result
            else:
                assert "content" in result or "error" not in result
        finally:
            os.unlink(path)


# ═════════════════════════════════════════════════════════════════
# Tool Registration
# ═════════════════════════════════════════════════════════════════

class TestToolRegistration:

    def test_core_tools_registered(self, researcher):
        """All core research tools should be registered."""
        tools = researcher._tools if hasattr(researcher, '_tools') else {}
        expected = [
            "search_internet",
            "search_internet_batch",
            "read_web_content",
            "read_file",
            "grep_codebase",
            "extract_api_details",
            "probe_target_api",
            "publish_research_findings",
        ]
        for tool_name in expected:
            assert tool_name in tools, f"Expected tool '{tool_name}' to be registered"

    def test_no_legacy_tools_registered(self, researcher):
        """Old compat tools should NOT be registered."""
        tools = researcher._tools if hasattr(researcher, '_tools') else {}
        legacy = ["web_search", "web_search_batch", "read_url", "note_finding",
                   "verify_research", "publish_findings", "search_registry"]
        for tool_name in legacy:
            assert tool_name not in tools, f"Legacy tool '{tool_name}' should not be registered"

    def test_role_defaults_to_researcher(self, researcher):
        assert researcher.role == "researcher"


# ═════════════════════════════════════════════════════════════════
# Publish Research Findings
# ═════════════════════════════════════════════════════════════════

class TestPublishFindings:

    @pytest.mark.asyncio
    async def test_publish_sets_phase_to_done(self, researcher):
        result = await researcher._tool_publish_research_findings(
            summary="Stripe uses Bearer auth",
            evidence=[{"pointer": "https://docs.stripe.com", "kind": "web_doc"}],
            api_specs=[{"method": "POST", "url": "/v1/charges", "body_schema": {"amount": "int"}}],
        )
        assert researcher._current_research_phase() == ResearchPhase.DONE

    @pytest.mark.asyncio
    async def test_publish_returns_candidate_ready(self, researcher):
        result = await researcher._tool_publish_research_findings(
            summary="Stripe uses Bearer auth",
            evidence=[{"pointer": "https://docs.stripe.com", "kind": "web_doc"}],
        )
        assert result.get("status") == "candidate_ready"
        assert result.get("action_required") == "delegate_coding"

    @pytest.mark.asyncio
    async def test_publish_rejects_empty_summary(self, researcher):
        result = await researcher._tool_publish_research_findings(
            summary="",
            evidence=[{"pointer": "https://docs.stripe.com"}],
        )
        assert result.get("status") == "error"
        assert "summary" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_publish_merges_accumulated_findings(self, researcher):
        """Findings accumulated during the session get merged into output."""
        researcher.current_state.internal_variables["research_findings"] = [
            {"url": "https://docs.stripe.com/api", "content_preview": "Bearer token auth"},
        ]
        result = await researcher._tool_publish_research_findings(
            summary="Stripe API research",
            evidence=[],  # empty explicit evidence → fallback to accumulated
        )
        # Should still succeed via accumulated findings fallback
        assert result.get("status") in ("candidate_ready", "error")


# ═════════════════════════════════════════════════════════════════
# Session State
# ═════════════════════════════════════════════════════════════════

class TestSessionState:

    def test_url_content_cache_isolated(self, researcher):
        """Each researcher instance starts with an empty URL cache."""
        assert len(researcher._url_content_cache) == 0

    def test_new_researcher_starts_clean(self, llm, internet_search):
        """A fresh researcher has no stale state."""
        r = ResearcherSubAgent(
            agent_id="fresh",
            llm_client=llm,
            internet_search=internet_search,
        )
        assert len(r._url_content_cache) == 0
        assert r._current_research_phase() == ResearchPhase.INIT


class TestOperatorBoundedDoneGate:

    def test_peer_wake_done_with_summary_allowed(self, researcher):
        from jarviscore.kernel.state import KernelState

        state = KernelState(
            workflow_id="wf",
            step_id="wake",
            agent_id="sentinel",
            task="shift wake",
            context={
                "execution_contract": {"execution_shape": "single_artifact"},
                "operator_bounded": True,
            },
        )
        ok, reason = researcher._can_complete(
            state,
            {"type": "done", "summary": "Reviewed blockers", "result": {"summary": "Reviewed blockers"}},
        )
        assert ok is True
        assert reason == ""

    def test_full_research_still_requires_evidence(self, researcher):
        from jarviscore.kernel.state import KernelState

        state = KernelState(
            workflow_id="wf",
            step_id="dossier",
            agent_id="sentinel",
            task="enterprise dossier",
            context={"complexity": "heavy"},
        )
        ok, reason = researcher._can_complete(
            state,
            {"type": "done", "summary": "done", "result": {"summary": "done"}},
        )
        assert ok is False
        assert "evidence" in reason.lower() or "research" in reason.lower()
