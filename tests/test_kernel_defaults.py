"""
Tests for kernel default subagents: CoderSubAgent, ResearcherSubAgent, CommunicatorSubAgent.

Tests use MockLLMClient to control LLM responses and verify the tool dispatch
loop, artifact tracking, and error handling without real LLM calls.
"""

import json

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


def _coder_write_response(code: str):
    return _llm_response(
        "THOUGHT: Write executable code\n"
        "TOOL: write_code\n"
        f"PARAMS: {json.dumps({'code': code})}"
    )


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
        assert "execute_code" in prompt
        assert "result" in prompt.lower()

    @pytest.mark.asyncio
    async def test_write_code_tool_versions_candidates(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        coder._candidates = []  # fresh

        r1 = coder._tool_write_code(code="result = 1")
        assert r1["candidate_id"] == 1
        assert r1["status"] == "validated"

        r2 = coder._tool_write_code(code="result = 2")
        assert r2["candidate_id"] == 2
        assert len(coder.candidates) == 2

    def test_validate_code_valid(self, mock_llm):
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        result = coder._tool_validate_code(code="result = 1 + 2")
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
        """Coder rejects DONE without executable proof of work."""
        mock_llm.responses = [
            _llm_response("THOUGHT: Simple task\nDONE: Completed\nRESULT: {\"value\": 42}")
        ]
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm)
        output = await coder.run("compute 42", max_turns=1)
        assert output.status == "yield"
        assert output.metadata["typed_outcome"] == "YIELD_EMERGENCY_TURN_FUSE"

    @pytest.mark.asyncio
    async def test_full_run_tool_then_done(self, mock_llm, mock_sandbox):
        """Coder uses write_code tool and completes from sandbox execution evidence."""
        mock_sandbox.responses = [
            {"status": "success", "output": 2, "error": None, "execution_time": 0.1}
        ]
        mock_llm.responses = [
            _coder_write_response("result = 1+1"),
        ]
        coder = CoderSubAgent(agent_id="c1", llm_client=mock_llm, sandbox=mock_sandbox)
        output = await coder.run("write addition code", max_turns=3)
        assert output.status == "success"
        assert output.payload == 2
        assert len(coder.candidates) == 1
        assert len(output.trajectory) == 1

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
        assert "search_internet" in researcher.tool_names
        assert "search_internet_batch" in researcher.tool_names
        assert "read_web_content" in researcher.tool_names
        assert "publish_research_findings" in researcher.tool_names
        assert "probe_target_api" in researcher.tool_names
        assert "grep_codebase" in researcher.tool_names

    @pytest.mark.asyncio
    async def test_publish_research_findings_returns_structured_output(self, mock_llm):
        """publish_research_findings returns api_specs, libraries, evidence, summary."""
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        result = await researcher._tool_publish_research_findings(
            api_specs=[{"endpoint": "/users", "method": "GET"}],
            libraries=["requests", "httpx"],
            evidence=[{"url": "https://docs.example.com", "snippet": "API docs"}],
            summary="Found the API docs.",
        )
        assert result["api_specs"] == [{"endpoint": "/users", "method": "GET"}]
        assert "requests" in result["libraries"]
        assert result["summary"] == "Found the API docs."
        assert len(result["evidence"]) >= 1

    @pytest.mark.asyncio
    async def test_publish_research_findings_empty_args(self, mock_llm):
        """publish_research_findings works with no arguments (empty research)."""
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        result = await researcher._tool_publish_research_findings()
        assert "api_specs" in result
        assert "libraries" in result
        assert "evidence" in result
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_grep_codebase_finds_pattern(self, mock_llm):
        """grep_codebase returns structured match results for a known pattern."""
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        result = await researcher._tool_grep_codebase(
            pattern="def test_",
            path="tests",
            file_glob="*.py",
            max_results=5,
        )
        assert "matches" in result
        assert isinstance(result["matches"], list)

    @pytest.mark.asyncio
    async def test_full_run_with_findings(self, mock_llm, monkeypatch):
        """Researcher calls publish_research_findings and completes (phase checks disabled)."""
        monkeypatch.setenv("RESEARCH_STRICT_PHASE_CONTRACT", "false")
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "false")
        mock_llm.responses = [
            _llm_response(
                'THOUGHT: Research complete\n'
                'TOOL: publish_research_findings\n'
                'PARAMS: {"api_specs": [], "libraries": ["requests"], '
                '"evidence": [{"url": "https://example.com", "snippet": "API docs"}], '
                '"summary": "Done"}'
            ),
            _llm_response(
                'THOUGHT: Published\nDONE: Research complete\n'
                'RESULT: {"summary": "Done", "evidence": [{"url": "https://example.com"}]}'
            ),
        ]
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        output = await researcher.run("research topic X", max_turns=5)
        assert output.status == "success"

    @pytest.mark.asyncio
    async def test_run_completes_on_done(self, mock_llm, monkeypatch):
        """Researcher run() returns success on DONE signal (validation disabled)."""
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "false")
        mock_llm.responses = [
            _llm_response(
                'THOUGHT: done\nDONE: run complete\n'
                'RESULT: {"summary": "done", "evidence": [{"url": "https://x.com"}]}'
            ),
        ]
        researcher = ResearcherSubAgent(agent_id="r1", llm_client=mock_llm)
        output = await researcher.run("task", max_turns=5)
        assert output.status == "success"


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
    async def test_full_run_accepts_json_done_protocol(self, mock_llm):
        """Structured JSON completion is a valid protocol, not raw prose."""
        mock_llm.responses = [
            _llm_response(json.dumps({
                "thought": "The task is answerable directly.",
                "done": "Message drafted",
                "result": {"message": "Status update: all systems go."},
            }))
        ]
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        output = await comm.run("draft status update", max_turns=1)
        assert output.status == "success"
        assert output.payload == {"message": "Status update: all systems go."}

    @pytest.mark.asyncio
    async def test_full_run_repairs_protocol_violation(self, mock_llm):
        """A raw response becomes visible feedback before final failure."""
        mock_llm.responses = [
            _llm_response("Here is the status update without the protocol."),
            _llm_response(
                'THOUGHT: Repair protocol\nDONE: Message drafted\n'
                'RESULT: {"message": "Status update: all systems go."}'
            ),
        ]
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        output = await comm.run("draft status update", max_turns=2)
        assert output.status == "success"
        assert output.trajectory[0]["status"] == "protocol_violation"
        assert output.payload == {"message": "Status update: all systems go."}

    @pytest.mark.asyncio
    async def test_full_run_fails_after_unrepaired_protocol_violation(self, mock_llm):
        """Invalid protocol is never coerced into completion."""
        mock_llm.responses = [
            _llm_response("Plain prose with no protocol."),
        ]
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        output = await comm.run("draft status update", max_turns=1)
        assert output.status == "failure"
        assert output.metadata["typed_outcome"] == "PROTOCOL_VIOLATION"

    @pytest.mark.asyncio
    async def test_full_run_fails_after_repeated_protocol_violation(self, mock_llm):
        """The repair loop is bounded; repeated raw output fails visibly."""
        mock_llm.responses = [
            _llm_response("First plain prose response."),
            _llm_response("Second plain prose response."),
            _llm_response("Third plain prose response."),
        ]
        comm = CommunicatorSubAgent(agent_id="m1", llm_client=mock_llm)
        output = await comm.run("draft status update", max_turns=3)
        assert output.status == "failure"
        assert output.metadata["typed_outcome"] == "PROTOCOL_VIOLATION"
        assert output.metadata["protocol_violations"] == 2
        assert len(output.trajectory) == 2

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
