"""
Tests for kernel default subagents: CoderSubAgent, ResearcherSubAgent, CommunicatorSubAgent.

Tests use MockLLMClient to control LLM responses and verify the tool dispatch
loop, artifact tracking, and error handling without real LLM calls.
"""

import pytest
from jarviscore.kernel.defaults import CoderSubAgent, ResearcherSubAgent, CommunicatorSubAgent
from jarviscore.kernel.defaults.coder import classify_auth_error
from jarviscore.testing import MockLLMClient, MockSandboxExecutor


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def mock_sandbox():
    return MockSandboxExecutor()


def _llm_response(content, tokens=None):
    """Build a mock LLM response dict."""
    return {
        "content": content,
        "provider": "mock",
        "tokens": tokens or {"input": 10, "output": 20, "total": 30},
        "cost_usd": 0.001,
        "model": "mock-model",
    }


# ══════════════════════════════════════════════════════════════════════
# CoderSubAgent Tests
# ══════════════════════════════════════════════════════════════════════

class TestCoderSubAgent:
    """Tests for CoderSubAgent."""

    def test_registers_expected_tools(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        assert "write_code" in coder.tool_names
        assert "validate_code" in coder.tool_names
        assert "execute_code" in coder.tool_names

    def test_system_prompt_contains_workflow(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        prompt = coder.get_system_prompt()
        assert "write_code" in prompt
        assert "validate_code" in prompt
        assert "result" in prompt.lower()

    @pytest.mark.asyncio
    async def test_write_code_tool_versions_candidates(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        coder._candidates = []  # fresh

        r1 = coder._tool_write_code(code="x = 1")
        assert r1["version"] == 1
        assert r1["status"] == "drafted"

        r2 = coder._tool_write_code(code="x = 2")
        assert r2["version"] == 2
        assert len(coder.candidates) == 2

    def test_validate_code_valid(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        result = coder._tool_validate_code(code="x = 1 + 2")
        assert result["valid"] is True

    def test_validate_code_invalid(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        result = coder._tool_validate_code(code="def foo(")
        assert result["valid"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_execute_code_calls_sandbox(self, mock_llm, mock_sandbox):
        mock_sandbox.responses = [
            {"status": "success", "output": 42, "error": None, "execution_time": 0.1}
        ]
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm, sandbox=mock_sandbox)
        coder._candidates = [{"version": 1, "code": "result = 42", "status": "drafted"}]

        result = await coder._tool_execute_code(code="result = 42")
        assert result["status"] == "success"
        assert result["output"] == 42
        assert len(mock_sandbox.calls) == 1

    @pytest.mark.asyncio
    async def test_execute_code_no_sandbox(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm, sandbox=None)
        result = await coder._tool_execute_code(code="x = 1")
        assert result["status"] == "error"
        assert "No sandbox" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_code_classifies_auth_error(self, mock_llm, mock_sandbox):
        mock_sandbox.responses = [
            {"status": "failure", "output": None, "error": "Token expired for API", "execution_time": 0.1}
        ]
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm, sandbox=mock_sandbox)
        result = await coder._tool_execute_code(code="api_call()")
        assert result["auth_error_type"] == "expired_token"

    @pytest.mark.asyncio
    async def test_full_run_done_immediately(self, mock_llm):
        """Coder gets a DONE response on first turn."""
        mock_llm.responses = [
            _llm_response("THOUGHT: Simple task\nDONE: Completed\nRESULT: {\"value\": 42}")
        ]
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        output = await coder.run("compute 42")
        assert output.status == "success"
        assert output.payload == {"value": 42}
        assert output.summary == "Completed"

    @pytest.mark.asyncio
    async def test_full_run_tool_then_done(self, mock_llm, mock_sandbox):
        """Coder uses write_code tool, then completes."""
        mock_llm.responses = [
            _llm_response("THOUGHT: Write code\nTOOL: write_code\nPARAMS: {\"code\": \"result = 1+1\"}"),
            _llm_response("THOUGHT: Done\nDONE: Code written\nRESULT: {\"code\": \"result = 1+1\"}"),
        ]
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm, sandbox=mock_sandbox)
        output = await coder.run("write addition code", max_turns=3)
        assert output.status == "success"
        assert len(coder.candidates) == 1
        assert len(output.trajectory) == 2  # tool_call + done

    @pytest.mark.asyncio
    async def test_run_resets_candidates(self, mock_llm):
        """Each run() call starts with fresh candidates."""
        mock_llm.responses = [
            _llm_response("THOUGHT: done\nDONE: first run"),
            _llm_response("THOUGHT: done\nDONE: second run"),
        ]
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        await coder.run("task1")
        await coder.run("task2")
        # Candidates should be empty (no write_code called in second run)
        assert len(coder.candidates) == 0


# ══════════════════════════════════════════════════════════════════════
# ResearcherSubAgent Tests
# ══════════════════════════════════════════════════════════════════════

class TestResearcherSubAgent:
    """Tests for ResearcherSubAgent."""

    def test_registers_expected_tools(self, mock_llm):
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        assert "search_registry" in researcher.tool_names
        assert "web_search" in researcher.tool_names
        assert "read_url" in researcher.tool_names
        assert "note_finding" in researcher.tool_names
        assert "check_sufficiency" in researcher.tool_names

    def test_note_finding_tracks_with_source(self, mock_llm):
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        researcher._findings = []
        researcher._sources = []

        result = researcher._tool_note_finding(
            finding="Python 3.12 supports PEP 695",
            source="docs.python.org",
            confidence=0.9,
        )
        assert result["recorded"] is True
        assert result["total_findings"] == 1
        assert len(researcher.findings) == 1
        assert researcher.findings[0]["confidence"] == 0.9
        assert "docs.python.org" in researcher.sources

    def test_note_finding_clamps_confidence(self, mock_llm):
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        researcher._findings = []
        researcher._sources = []

        researcher._tool_note_finding(finding="x", source="s", confidence=1.5)
        assert researcher.findings[0]["confidence"] == 1.0

        researcher._tool_note_finding(finding="y", source="s", confidence=-0.3)
        assert researcher.findings[1]["confidence"] == 0.0

    def test_check_sufficiency_insufficient(self, mock_llm):
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        researcher._findings = []
        researcher._sources = []

        result = researcher._tool_check_sufficiency()
        assert result["sufficient"] is False
        assert result["findings_needed"] > 0

    def test_check_sufficiency_sufficient(self, mock_llm):
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        researcher._findings = []
        researcher._sources = []

        # Add enough findings and sources
        researcher._tool_note_finding(finding="f1", source="src1", confidence=0.8)
        researcher._tool_note_finding(finding="f2", source="src2", confidence=0.7)

        result = researcher._tool_check_sufficiency()
        assert result["sufficient"] is True
        assert result["sources_count"] == 2
        assert result["findings_count"] == 2

    def test_search_registry_no_registry(self, mock_llm):
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm, code_registry=None)
        result = researcher._tool_search_registry(query="test")
        assert result["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_web_search_no_client(self, mock_llm):
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm, search_client=None)
        result = await researcher._tool_web_search(query="test")
        assert result["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_full_run_with_findings(self, mock_llm):
        """Researcher notes findings and completes."""
        mock_llm.responses = [
            _llm_response(
                'THOUGHT: Note a finding\nTOOL: note_finding\n'
                'PARAMS: {"finding": "Found info", "source": "web", "confidence": 0.8}'
            ),
            _llm_response(
                'THOUGHT: Note another\nTOOL: note_finding\n'
                'PARAMS: {"finding": "More info", "source": "docs", "confidence": 0.9}'
            ),
            _llm_response(
                'THOUGHT: Research complete\nDONE: Gathered 2 findings\n'
                'RESULT: {"findings": 2}'
            ),
        ]
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        output = await researcher.run("research topic X", max_turns=5)
        assert output.status == "success"
        assert len(researcher.findings) == 2
        assert len(researcher.sources) == 2

    @pytest.mark.asyncio
    async def test_run_resets_findings(self, mock_llm):
        """Each run() starts with empty findings."""
        mock_llm.responses = [
            _llm_response("THOUGHT: done\nDONE: first"),
            _llm_response("THOUGHT: done\nDONE: second"),
        ]
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        await researcher.run("task1")
        await researcher.run("task2")
        assert len(researcher.findings) == 0
        assert len(researcher.sources) == 0


# ══════════════════════════════════════════════════════════════════════
# CommunicatorSubAgent Tests
# ══════════════════════════════════════════════════════════════════════

class TestCommunicatorSubAgent:
    """Tests for CommunicatorSubAgent."""

    def test_registers_expected_tools(self, mock_llm):
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        assert "draft_message" in comm.tool_names
        assert "format_report" in comm.tool_names
        assert "send_to_peer" in comm.tool_names

    def test_draft_message_versions(self, mock_llm):
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        comm._drafts = []

        r1 = comm._tool_draft_message(content="Hello world", audience="non-technical")
        assert r1["version"] == 1
        assert r1["status"] == "drafted"

        r2 = comm._tool_draft_message(content="Details here", audience="technical", format="markdown")
        assert r2["version"] == 2
        assert len(comm.drafts) == 2

    def test_format_report_markdown(self, mock_llm):
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        comm._drafts = []

        result = comm._tool_format_report(
            title="Test Report",
            sections=[
                {"heading": "Summary", "body": "All good."},
                {"heading": "Details", "body": "Nothing to report."},
            ],
            format="markdown",
        )
        assert result["sections_count"] == 2
        assert "# Test Report" in result["report"]
        assert "## Summary" in result["report"]
        assert len(comm.drafts) == 1

    def test_format_report_plain(self, mock_llm):
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        comm._drafts = []

        result = comm._tool_format_report(
            title="Plain Report",
            sections=[{"heading": "Sec1", "body": "Content"}],
            format="plain",
        )
        assert "Plain Report" in result["report"]
        assert "===" in result["report"]
        assert "---" in result["report"]

    @pytest.mark.asyncio
    async def test_send_to_peer_no_mailbox(self, mock_llm):
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm, mailbox=None)
        result = await comm._tool_send_to_peer(peer_role="analyst", message="hello")
        assert result["status"] == "error"
        assert "No mailbox" in result["error"]

    @pytest.mark.asyncio
    async def test_send_to_peer_with_mailbox(self, mock_llm):
        class FakeMailbox:
            def __init__(self):
                self.sent = []
            def send(self, to_role, message, priority="normal"):
                self.sent.append({"to": to_role, "msg": message, "priority": priority})
                return {"ok": True}

        mailbox = FakeMailbox()
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm, mailbox=mailbox)
        result = await comm._tool_send_to_peer(peer_role="analyst", message="data ready", priority="high")
        assert result["status"] == "sent"
        assert result["peer"] == "analyst"
        assert len(mailbox.sent) == 1
        assert mailbox.sent[0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_full_run_draft_and_done(self, mock_llm):
        """Communicator drafts a message and completes."""
        mock_llm.responses = [
            _llm_response(
                'THOUGHT: Draft message\nTOOL: draft_message\n'
                'PARAMS: {"content": "Status update: all systems go.", "audience": "non-technical"}'
            ),
            _llm_response(
                'THOUGHT: Done\nDONE: Message drafted\nRESULT: {"message": "Status update: all systems go."}'
            ),
        ]
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        output = await comm.run("draft status update", max_turns=3)
        assert output.status == "success"
        assert len(comm.drafts) == 1

    @pytest.mark.asyncio
    async def test_run_resets_drafts(self, mock_llm):
        """Each run() starts with fresh drafts."""
        mock_llm.responses = [
            _llm_response("THOUGHT: done\nDONE: first"),
            _llm_response("THOUGHT: done\nDONE: second"),
        ]
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        await comm.run("task1")
        await comm.run("task2")
        assert len(comm.drafts) == 0


# ══════════════════════════════════════════════════════════════════════
# Auth Error Classification Tests
# ══════════════════════════════════════════════════════════════════════

class TestAuthErrorClassification:
    """Tests for classify_auth_error utility."""

    def test_expired_token(self):
        assert classify_auth_error("Token expired for this request") == "expired_token"

    def test_missing_auth(self):
        assert classify_auth_error("Authentication required") == "missing_auth"

    def test_invalid_token(self):
        assert classify_auth_error("Invalid token provided") == "invalid_token"

    def test_permission_denied(self):
        assert classify_auth_error("Access denied: insufficient scope") == "permission_denied"

    def test_unrelated_error(self):
        assert classify_auth_error("Connection timeout") is None

    def test_case_insensitive(self):
        assert classify_auth_error("TOKEN EXPIRED") == "expired_token"
