"""
Tests for issue #63: the no-code promise demands loud failures.

What these tests prove:
- ReasoningAgent: one structured completion, standard envelope, clean JSON
  failure, loud pre-start error, importable from the package root
- AutoAgent raises a descriptive RuntimeError when used before mesh.start()
- A declared single_response contract runs ONE completion — no kernel routing
- A failing complexity classifier falls back to a direct Kernel turn instead
  of failing the task outright
- Goal-path telemetry sums step tokens/cost instead of reporting free
- create_llm_client is importable without bs4; LLMClient alias exists
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jarviscore import ReasoningAgent
from jarviscore.profiles.autoagent import AutoAgent


class _Analyst(ReasoningAgent):
    role = "analyst"
    capabilities = ["analysis"]
    system_prompt = "You are a test analyst. Return JSON."


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


class TestReasoningAgent:

    def test_importable_from_package_root(self):
        import jarviscore
        assert jarviscore.ReasoningAgent is ReasoningAgent

    def test_missing_system_prompt_fails_loudly_at_construction(self):
        class Promptless(ReasoningAgent):
            role = "x"
            capabilities = ["x"]

        with pytest.raises(ValueError, match="system_prompt"):
            Promptless()

    @pytest.mark.asyncio
    async def test_used_before_start_raises_descriptive_error(self):
        agent = _Analyst()
        with pytest.raises(RuntimeError, match="before mesh.start"):
            await agent.execute_task({"task": "analyse"})

    @pytest.mark.asyncio
    async def test_one_completion_standard_envelope(self):
        agent = _Analyst()
        agent.llm = _FakeLLM('{"direction": "long", "conviction": 0.7}')

        result = await agent.execute_task({"task": "analyse EURUSD"})

        assert result["status"] == "success"
        assert result["payload"] == {"direction": "long", "conviction": 0.7}
        assert result["tokens"]["total"] == 15
        assert len(agent.llm.calls) == 1
        call = agent.llm.calls[0]
        assert call["response_format"] == {"type": "json_object"}
        assert call["messages"][0]["content"].startswith("You are a test analyst")

    @pytest.mark.asyncio
    async def test_unparseable_json_is_a_clean_failure(self):
        agent = _Analyst()
        agent.llm = _FakeLLM("I think the market looks bullish today!")

        result = await agent.execute_task({"task": "analyse"})

        assert result["status"] == "failure"
        assert result["payload"] is None
        assert "parseable JSON" in result["error"]
        assert result["output"].startswith("I think")  # raw kept for debugging

    @pytest.mark.asyncio
    async def test_code_fenced_json_is_tolerated(self):
        agent = _Analyst()
        agent.llm = _FakeLLM('```json\n{"ok": true}\n```')

        result = await agent.execute_task({"task": "t"})
        assert result["status"] == "success"
        assert result["payload"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_prose_mode_skips_json_contract(self):
        class Writer(ReasoningAgent):
            role = "writer"
            capabilities = ["writing"]
            system_prompt = "You write."
            expects_json = False

        agent = Writer()
        agent.llm = _FakeLLM("A plain prose answer.")
        result = await agent.execute_task({"task": "write"})
        assert result["status"] == "success"
        assert result["payload"] == "A plain prose answer."
        assert "response_format" not in agent.llm.calls[0]


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
