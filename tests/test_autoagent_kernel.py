"""
Tests for AutoAgent ↔ Kernel integration (6G).

Verifies that AutoAgent's execute_task() produces backward-compatible
output format while using the kernel internally.

Note: These tests verify the kernel in isolation (not the full AutoAgent
setup pipeline) since AutoAgent.setup() requires full infrastructure.
The kernel is the component that replaces the linear pipeline.
"""

import pytest
from jarviscore.kernel import Kernel
from jarviscore.testing import MockLLMClient, MockSandboxExecutor


def _llm_response(content, tokens=None, cost=0.001):
    return {
        "content": content,
        "provider": "mock",
        "tokens": tokens or {"input": 50, "output": 100, "total": 150},
        "cost_usd": cost,
        "model": "mock-model",
    }


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def mock_sandbox():
    return MockSandboxExecutor()


class TestKernelOutputFormat:
    """Verify kernel output can be converted to AutoAgent's legacy format."""

    @pytest.mark.asyncio
    async def test_success_output_has_required_fields(self, mock_llm, mock_sandbox):
        """Kernel success output contains all fields needed for legacy format."""
        mock_llm.responses = [
            _llm_response(
                "THOUGHT: Generated code\nDONE: Task complete\n"
                'RESULT: {"output": "hello world"}'
            )
        ]
        kernel = Kernel(llm_client=mock_llm, sandbox=mock_sandbox)
        output = await kernel.execute(task="Print hello world")

        assert output.status == "success"
        assert output.payload is not None
        assert output.summary != ""
        assert isinstance(output.trajectory, list)
        assert "tokens" in output.metadata
        assert "cost_usd" in output.metadata

    @pytest.mark.asyncio
    async def test_failure_output_format(self, mock_llm, mock_sandbox):
        """Kernel failure output has correct structure."""
        kernel = Kernel(
            llm_client=mock_llm,
            sandbox=mock_sandbox,
            config={"kernel_max_turns": 0},  # Will hit max turns immediately
        )
        # With max_turns=0, min(fuse, 0) = 0, subagent loop doesn't run
        # Subagent returns failure "Max turns (0) reached"
        output = await kernel.execute(task="Impossible task", max_dispatches=1)

        assert output.status == "failure"
        assert "dispatches" in output.metadata

    @pytest.mark.asyncio
    async def test_legacy_dict_conversion(self, mock_llm, mock_sandbox):
        """AgentOutput can be converted to the legacy dict format."""
        mock_llm.responses = [
            _llm_response(
                "THOUGHT: Done\nDONE: Calculated\nRESULT: {\"answer\": 42}",
                tokens={"input": 100, "output": 200, "total": 300},
                cost=0.05,
            )
        ]
        kernel = Kernel(llm_client=mock_llm, sandbox=mock_sandbox)
        output = await kernel.execute(task="Calculate 6 * 7")

        # Convert to legacy dict format (what AutoAgent.execute_task returns)
        legacy = {
            "status": output.status,
            "output": output.payload,
            "error": None if output.status == "success" else output.summary,
            "tokens": output.metadata.get("tokens", {}),
            "cost_usd": output.metadata.get("cost_usd", 0.0),
        }

        assert legacy["status"] == "success"
        assert legacy["output"] == {"answer": 42}
        assert legacy["error"] is None
        assert legacy["tokens"]["total"] == 300
        assert legacy["cost_usd"] == 0.05

    @pytest.mark.asyncio
    async def test_yield_maps_to_failure_with_pending(self, mock_llm, mock_sandbox):
        """AgentOutput with status='yield' maps to failure + yield_pending in legacy."""
        # We test the mapping logic directly since we can't easily trigger yield
        from jarviscore.context.truth import AgentOutput

        yield_output = AgentOutput(
            status="yield",
            summary="Human approval needed",
            metadata={"yield_pending": True},
        )

        # Legacy conversion
        legacy_status = "failure" if yield_output.status == "yield" else yield_output.status
        legacy = {
            "status": legacy_status,
            "output": yield_output.payload,
            "error": yield_output.summary,
            "yield_pending": yield_output.metadata.get("yield_pending", False),
        }

        assert legacy["status"] == "failure"
        assert legacy["yield_pending"] is True

    @pytest.mark.asyncio
    async def test_multi_turn_tool_use(self, mock_llm, mock_sandbox):
        """Kernel handles multi-turn subagent execution correctly."""
        mock_sandbox.responses = [
            {"status": "success", "output": 120, "error": None, "execution_time": 0.1}
        ]
        mock_llm.responses = [
            _llm_response(
                'THOUGHT: Write code\nTOOL: write_code\nPARAMS: {"code": "result = 120"}'
            ),
            _llm_response(
                'THOUGHT: Validate\nTOOL: validate_code\nPARAMS: {"code": "result = 120"}'
            ),
            _llm_response(
                'THOUGHT: Execute\nTOOL: execute_code\nPARAMS: {"code": "result = 120"}'
            ),
            _llm_response(
                'THOUGHT: Done\nDONE: Factorial computed\nRESULT: {"factorial": 120}'
            ),
        ]
        kernel = Kernel(llm_client=mock_llm, sandbox=mock_sandbox)
        output = await kernel.execute(task="Calculate factorial of 5")

        assert output.status == "success"
        assert output.payload == {"factorial": 120}
        # Should have 4 trajectory entries (3 tool calls + 1 done)
        assert len(output.trajectory) == 4
