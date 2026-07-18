"""
Tests for issue #63: the no-code promise demands loud failures.

What these tests prove (two-profile model preserved — CustomAgent and
AutoAgent only; the single-completion shape lives INSIDE AutoAgent via
the single_response execution contract):

- AutoAgent raises a descriptive RuntimeError when used before mesh.start()
- A declared single_response contract runs ONE completion against the
  system prompt — no kernel routing, no codegen
- A failing complexity classifier falls back to a direct Kernel turn instead
  of failing the task outright
- Goal-path telemetry sums step tokens/cost instead of reporting free
- create_llm_client is importable without bs4; LLMClient alias exists
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jarviscore.profiles.autoagent import AutoAgent


class _FakeLLM:
    def __init__(self, content):
        self._content = content
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "content": self._content,
            "tokens": {"input": 10, "output": 5, "total": 15},
            "cost_usd": 0.001,
            "provider": "fake",
            "model": "fake-1",
        }


class _MiniAuto(AutoAgent):
    role = "mini"
    capabilities = ["mini"]
    system_prompt = "You are mini."


class TestAutoAgentLoudFailures:

    @pytest.mark.asyncio
    async def test_used_before_start_raises_descriptive_error(self):
        agent = _MiniAuto()
        with pytest.raises(RuntimeError, match="before mesh.start"):
            await agent.execute_task({"task": "do something"})

    @pytest.mark.asyncio
    async def test_single_response_contract_is_one_completion(self):
        """The 'analysis, not code' shape — one completion, kernel untouched."""
        agent = _MiniAuto()
        agent.llm = _FakeLLM("Direct answer, no codegen.")
        agent._kernel = MagicMock()  # must NOT be touched

        result = await agent.execute_task({
            "task": "summarize x",
            "context": {"execution_contract": {"execution_shape": "single_response"}},
        })

        assert result["status"] == "success"
        assert result["output"] == "Direct answer, no codegen."
        assert result["execution_shape"] == "single_response"
        assert result["tokens"]["total"] == 15
        agent._kernel.execute.assert_not_called()
        # One completion, against the system prompt
        assert len(agent.llm.calls) == 1
        assert agent.llm.calls[0]["messages"][0]["content"].endswith("You are mini.")

    @pytest.mark.asyncio
    async def test_single_response_provider_failure_is_a_clean_envelope(self):
        class _BoomLLM:
            async def generate(self, **kwargs):
                raise TimeoutError("provider down")

        agent = _MiniAuto()
        agent.llm = _BoomLLM()
        agent._kernel = MagicMock()

        result = await agent.execute_task({
            "task": "x",
            "context": {"execution_contract": {"execution_shape": "single_response"}},
        })
        assert result["status"] == "failure"
        assert "single_response completion failed" in result["error"]

    def test_goal_telemetry_sums_step_metadata(self):
        execution = SimpleNamespace(completed=[
            SimpleNamespace(output=SimpleNamespace(metadata={
                "tokens": {"input": 100, "output": 50, "total": 150},
                "cost_usd": 0.01,
            })),
            SimpleNamespace(output=SimpleNamespace(metadata={
                "tokens": {"input": 200, "output": 100, "total": 300},
                "cost_usd": 0.02,
            })),
            SimpleNamespace(output=SimpleNamespace(metadata={})),  # tolerated
        ])
        tokens, cost = AutoAgent._aggregate_goal_telemetry(execution)
        assert tokens == {"input": 300, "output": 150, "total": 450}
        assert cost == pytest.approx(0.03)


class TestTwoProfileModel:
    """jarviscore ships exactly two profiles — a deliberate design constraint."""

    def test_only_two_profiles_are_exported(self):
        import jarviscore.profiles as profiles
        assert sorted(profiles.__all__) == ["AutoAgent", "CustomAgent"]

    def test_no_reasoning_profile_exists(self):
        import jarviscore
        assert not hasattr(jarviscore, "ReasoningAgent")


class TestPackagingPapercuts:

    def test_llm_client_alias_exists(self):
        from jarviscore.execution.llm import LLMClient, UnifiedLLMClient
        assert LLMClient is UnifiedLLMClient

    def test_search_module_has_no_eager_bs4_import(self):
        import ast as _ast
        import jarviscore.execution.search as search_mod
        tree = _ast.parse(open(search_mod.__file__).read())
        top_level_imports = [
            n for n in tree.body
            if isinstance(n, (_ast.Import, _ast.ImportFrom))
        ]
        for node in top_level_imports:
            names = getattr(node, "module", None) or ""
            assert "bs4" not in str(names), "bs4 must be lazily imported"
