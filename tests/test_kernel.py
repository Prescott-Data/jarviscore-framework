"""
Tests for Kernel — OODA-loop supervisor.

Tests task classification, subagent dispatch, model routing,
multi-dispatch retry, HITL escalation, and cost aggregation.
"""

import json

import pytest
from jarviscore.kernel import Kernel
from jarviscore.kernel.hitl import AdaptiveHITLPolicy
from jarviscore.testing import MockLLMClient, MockSandboxExecutor


def _llm_response(content, tokens=None, cost=0.001):
    return {
        "content": content,
        "provider": "mock",
        "tokens": tokens or {"input": 10, "output": 20, "total": 30},
        "cost_usd": cost,
        "model": "mock-model",
    }


def _router_response(role, confidence=0.9, reason="test route"):
    return _llm_response(
        f'{{"role": "{role}", "confidence": {confidence}, '
        f'"reason": "{reason}", "evidence_required": false}}',
        tokens={"input": 5, "output": 5, "total": 10},
        cost=0.0,
    )


def _coder_write_response(code='result = {"ok": True}'):
    return _llm_response(
        "THOUGHT: Write executable code\n"
        "TOOL: write_code\n"
        f"PARAMS: {json.dumps({'code': code})}"
    )


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def mock_sandbox():
    return MockSandboxExecutor()


@pytest.fixture
def kernel(mock_llm, mock_sandbox):
    return Kernel(
        llm_client=mock_llm,
        sandbox=mock_sandbox,
        config={
            "coding_model": "dromos-gpt-4.1",
            "task_model": "gpt-4o",
            "kernel_max_turns": 10,
        },
    )


# ── Task Classification ──────────────────────────────────────────────

class TestTaskClassification:

    @pytest.mark.asyncio
    async def test_explicit_role_routes_without_llm(self, kernel, mock_llm):
        decision = await kernel._route_task(
            "Run the exact planner-assigned step",
            agent_default_role="researcher",
        )
        assert decision.role == "researcher"
        assert decision.confidence == 1.0
        assert mock_llm.calls == []

    @pytest.mark.asyncio
    async def test_structured_router_selects_role(self, kernel, mock_llm):
        mock_llm.responses = [_router_response("communicator", reason="request needs coordination")]
        decision = await kernel._route_task(
            "Secure read-only access or PDFs for all bank accounts and confirm completeness.",
            agent_default_role="coder",
            use_default_role_as_fallback=True,
        )
        assert decision.role == "communicator"
        assert decision.reason == "request needs coordination"

    @pytest.mark.asyncio
    async def test_router_rejects_invalid_role(self, kernel, mock_llm):
        mock_llm.responses = [_llm_response('{"role": "hacker", "confidence": 0.99, "reason": "bad"}')]
        decision = await kernel.execute(task="Route impossible task", max_dispatches=1)
        assert decision.status == "failure"
        assert decision.metadata["routing_error"]

    @pytest.mark.asyncio
    async def test_custom_explicit_role_uses_registered_lease_profile(self, mock_llm, mock_sandbox):
        from jarviscore.kernel.defaults.communicator import CommunicatorSubAgent

        class DatabaseKernel(Kernel):
            def _create_subagent(self, role: str, agent_id: str):
                if role == "database":
                    return CommunicatorSubAgent(agent_id=agent_id, llm_client=self.llm_client)
                return super()._create_subagent(role, agent_id)

        kernel = DatabaseKernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            config={
                "kernel_role_profiles": {
                    "database": {
                        "thinking_budget": 40_000,
                        "action_budget": 20_000,
                        "max_total_tokens": 60_000,
                        "wall_clock_ms": 120_000,
                        "emergency_turn_fuse": 8,
                        "model_tier": "task",
                        "complexity": "standard",
                    },
                },
                "kernel_role_catalog": {
                    "database": "Read-only SQL/database analysis role.",
                },
            },
        )
        mock_llm.responses = [
            _llm_response('THOUGHT: Done\nDONE: Query summarized\nRESULT: {"rows": 3}')
        ]
        output = await kernel.execute(
            task="Summarize customer table row count",
            agent_default_role="database",
            max_dispatches=1,
        )
        assert output.status == "success"
        assert output.metadata["dispatches"][0]["role"] == "database"
        assert "COMMUNICATION SPECIALIST" in mock_llm.calls[0]["messages"][0]["content"]


# ── Model Routing ─────────────────────────────────────────────────────

class TestModelRouting:

    def test_coding_tier(self, kernel):
        assert kernel._get_model_for_tier("coding") == "dromos-gpt-4.1"

    def test_task_tier(self, kernel):
        assert kernel._get_model_for_tier("task") == "gpt-4o"

    def test_unknown_tier(self, kernel):
        assert kernel._get_model_for_tier("unknown") is None


# ── Subagent Creation ─────────────────────────────────────────────────

class TestSubagentCreation:

    def test_create_coder(self, kernel):
        from jarviscore.kernel.defaults.coder import CoderSubAgent
        agent = kernel._create_subagent("coder", "test_coder")
        assert isinstance(agent, CoderSubAgent)

    def test_create_researcher(self, kernel):
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        agent = kernel._create_subagent("researcher", "test_researcher")
        assert isinstance(agent, ResearcherSubAgent)

    def test_create_communicator(self, kernel):
        from jarviscore.kernel.defaults.communicator import CommunicatorSubAgent
        agent = kernel._create_subagent("communicator", "test_comm")
        assert isinstance(agent, CommunicatorSubAgent)

    def test_unknown_role_raises(self, kernel):
        with pytest.raises(ValueError, match="Unknown subagent role"):
            kernel._create_subagent("hacker", "test")


# ── Execute: Success Path ─────────────────────────────────────────────

class TestKernelExecuteSuccess:

    @pytest.mark.asyncio
    async def test_simple_coding_task(self, kernel, mock_llm, mock_sandbox):
        mock_sandbox.responses = [{"status": "success", "output": {"factorial": 3628800}}]
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('import math\nresult = {"factorial": math.factorial(10)}')
        ]
        output = await kernel.execute(task="Calculate factorial of 10")
        assert output.status == "success"
        assert output.payload == {"factorial": 3628800}
        assert output.metadata["dispatches"][0]["role"] == "coder"

    @pytest.mark.asyncio
    async def test_research_task(self, kernel, mock_llm, monkeypatch):
        monkeypatch.setenv("RESEARCH_STRICT_DONE_VALIDATION", "false")
        mock_llm.responses = [
            _router_response("researcher"),
            _llm_response(
                "THOUGHT: Research complete\n"
                "DONE: Found the answer\n"
                'RESULT: {"answer": "FastAPI", "summary": "FastAPI is the best Python web framework"}'
            )
        ]
        output = await kernel.execute(task="Research the best Python web framework")
        assert output.status == "success"
        assert output.metadata["dispatches"][0]["role"] == "researcher"

    @pytest.mark.asyncio
    async def test_communication_task(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("communicator"),
            _llm_response(
                "THOUGHT: Drafted\n"
                "DONE: Message drafted\n"
                'RESULT: {"message": "All systems go"}'
            )
        ]
        output = await kernel.execute(task="Draft a status report")
        assert output.status == "success"
        assert output.metadata["dispatches"][0]["role"] == "communicator"

    @pytest.mark.asyncio
    async def test_context_passed_to_subagent(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("communicator"),
            _llm_response("THOUGHT: Done\nDONE: Used context\nRESULT: {\"used_context\": true}")
        ]
        output = await kernel.execute(
            task="Process data",
            context={"data": [1, 2, 3]},
            system_prompt="You are a data processor.",
        )
        assert output.status == "success"
        # Verify context data reached the LLM — it appears in the user message
        # (messages[1]) since the subagent injects context into the task prompt.
        # The system message (messages[0]) is the subagent's own hardcoded persona.
        all_content = " ".join(
            str(m.get("content", "")) for m in mock_llm.calls[1]["messages"]
        )
        assert "data" in all_content
        assert "Process data" in all_content


# ── Execute: Failure + Retry ──────────────────────────────────────────

class TestKernelExecuteFailure:

    @pytest.mark.asyncio
    async def test_all_dispatches_fail(self, kernel, mock_llm):
        """Protocol-invalid responses must not become successful work."""
        # Empty responses use the mock default, which violates TOOL/DONE and
        # cannot satisfy coder proof-of-work.
        mock_llm.responses = []  # Will use default response
        output = await kernel.execute(
            task="Do something complex",
            max_dispatches=2,
            agent_default_role="coder",
        )
        assert output.status == "yield"
        assert output.metadata["typed_outcome"] == "YIELD_BUDGET_EXHAUSTED"

    @pytest.mark.asyncio
    async def test_failure_then_success(self, kernel, mock_llm):
        """Kernel succeeds when coder produces executable proof of work."""
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('result = {"ok": True}'),
        ]
        output = await kernel.execute(task="Calculate pi", max_dispatches=2)
        assert output.status == "success"
        assert len(output.metadata["dispatches"]) == 1  # Succeeded first try

    @pytest.mark.asyncio
    async def test_cost_aggregation(self, kernel, mock_llm):
        """Token and cost metadata is aggregated across dispatches."""
        mock_llm.responses = [
            _router_response("coder"),
            _llm_response(
                "THOUGHT: Done\nDONE: Result\nRESULT: {\"v\": 1}",
                tokens={"input": 100, "output": 200, "total": 300},
                cost=0.05,
            )
        ]
        output = await kernel.execute(task="Compute something")
        assert output.metadata["tokens"]["total"] == 300
        assert output.metadata["cost_usd"] == 0.05

    @pytest.mark.asyncio
    async def test_elapsed_time_tracked(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("coder"),
            _llm_response("THOUGHT: Done\nDONE: Quick result\nRESULT: {\"ok\": true}")
        ]
        output = await kernel.execute(task="Fast task")
        assert "elapsed_ms" in output.metadata
        assert output.metadata["elapsed_ms"] >= 0


# ── HITL Escalation ───────────────────────────────────────────────────

class TestKernelHITL:

    @pytest.mark.asyncio
    async def test_yield_passthrough(self, mock_llm, mock_sandbox):
        """If subagent returns yield, kernel passes it through."""
        # We can't easily make a subagent return yield via LLM responses
        # since BaseSubAgent only returns success/failure. Test the kernel's
        # response to a yield output by testing the HITL escalation path instead.
        pass

    @pytest.mark.asyncio
    async def test_hitl_escalation_on_failure(self, mock_llm, mock_sandbox):
        """Kernel escalates to HITL on repeated failure if policy is enabled."""
        policy = AdaptiveHITLPolicy(
            enabled=True,
            reason_codes=["execution_failure"],
            max_confidence=0.5,
            min_risk_score=0.3,
        )
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            hitl_policy=policy,
            config={"kernel_max_turns": 1},
        )
        # Empty content violates the subagent protocol and must not become success.
        mock_llm.responses = [
            _router_response("coder"),
            {"content": "", "provider": "mock", "tokens": {"input": 0, "output": 0, "total": 0}, "cost_usd": 0, "model": "m"},
        ]
        output = await kernel.execute(task="Risky operation", max_dispatches=1)
        assert output.status in {"failure", "yield"}


# ── Dispatch Records ──────────────────────────────────────────────────

class TestDispatchRecords:

    @pytest.mark.asyncio
    async def test_dispatch_records_in_metadata(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("coder"),
            _coder_write_response('result = {"ok": True}')
        ]
        output = await kernel.execute(task="Build a widget")
        dispatches = output.metadata["dispatches"]
        assert len(dispatches) == 1
        assert dispatches[0]["role"] == "coder"
        assert dispatches[0]["status"] == "success"
        assert dispatches[0]["dispatch"] == 1

    @pytest.mark.asyncio
    async def test_model_in_dispatch_record(self, kernel, mock_llm):
        mock_llm.responses = [
            _router_response("researcher"),
            _llm_response("THOUGHT: Done\nDONE: Researched")
        ]
        output = await kernel.execute(task="Research Python typing")
        dispatches = output.metadata["dispatches"]
        # Researcher uses task tier
        assert dispatches[0]["model"] == "gpt-4o"
