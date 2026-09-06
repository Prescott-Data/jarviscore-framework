"""Offline provider and single-response contracts for #148."""

import asyncio
import json
from enum import Enum
from types import SimpleNamespace as NS
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarviscore.execution.llm import LLMProvider, UnifiedLLMClient
from jarviscore.profiles.autoagent import AutoAgent


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """These regressions must never reach a live provider, even on a developer machine."""
    def blocked(*args, **kwargs):
        pytest.fail("Network access is forbidden in completion contract tests")

    monkeypatch.setattr("socket.socket.connect", blocked)
    monkeypatch.setattr("socket.socket.connect_ex", blocked)


class MiniAuto(AutoAgent):
    role = "completion-test"
    capabilities: ClassVar[list[str]] = ["analysis"]
    system_prompt = "Answer once."


def client(provider):
    llm = UnifiedLLMClient.__new__(UnifiedLLMClient)
    llm.config = {"llm_max_retries_429": 0}
    llm._semaphore = None
    llm.provider_order = [LLMProvider(provider)]
    return llm


@pytest.mark.parametrize("reason,content", [("stop", "answer"), ("length", "partial"), ("content_filter", None)])
async def test_azure_chat_preserves_completion(reason, content):
    llm = client("azure")
    response = NS(
        choices=[NS(finish_reason=reason, message=NS(content=content, refusal=None),
                    content_filter_results={"test": {"filtered": reason == "content_filter"}})],
        usage=NS(prompt_tokens=10, completion_tokens=4000, total_tokens=4010,
                 completion_tokens_details={"reasoning_tokens": 3990}),
    )
    llm.azure_client = NS(chat=NS(completions=NS(create=AsyncMock(return_value=response))))
    result = await llm.generate("answer")
    assert result["finish_reason"] == reason
    assert result["content"] == content
    assert result["tokens"]["output"] == 4000
    assert result["provider_metadata"]["usage"]["completion_tokens_details"]["reasoning_tokens"] == 3990
    assert result["provider_metadata"]["content_filter_results"] == response.choices[0].content_filter_results
    json.dumps(result)


@pytest.mark.parametrize("status,reason", [("completed", None), ("incomplete", "max_output_tokens"), ("incomplete", "content_filter"), ("failed", None)])
async def test_azure_responses_preserves_status_and_details(status, reason):
    llm = client("azure")
    response = NS(output_text="partial", status=status,
                  incomplete_details=NS(reason=reason) if reason else None,
                  usage=NS(input_tokens=10, output_tokens=20, total_tokens=30),
                  error=NS(code="server_error") if status == "failed" else None)
    llm.azure_client = NS(responses=NS(create=AsyncMock(return_value=response)))
    result = await llm.generate("answer", model="gpt-5-codex")
    assert result["finish_reason"] == (reason or status)
    assert result["provider_metadata"]["status"] == status
    assert result["provider_metadata"]["incomplete_details"] == ({"reason": reason} if reason else None)
    json.dumps(result)


@pytest.mark.parametrize("reason,blocks", [
    ("end_turn", [NS(text="answer")]), ("max_tokens", [NS(text="partial")]),
    ("refusal", []), ("tool_use", [NS(type="tool_use", name="lookup")]),
    ("end_turn", [NS(type="thinking", thinking="private"), NS(text="answer")]),
])
async def test_claude_preserves_stop_reason_with_empty_or_non_text_blocks(reason, blocks):
    llm = client("claude")
    llm.claude_client = NS(messages=NS(create=MagicMock(return_value=NS(
        content=blocks, stop_reason=reason, stop_sequence=None,
        usage=NS(input_tokens=10, output_tokens=20),
    ))))
    result = await llm.generate("answer")
    assert result["finish_reason"] == reason
    assert result["provider_metadata"]["stop_reason"] == reason
    assert result["content"] == "".join(getattr(block, "text", "") for block in blocks)
    json.dumps(result)


class FinishReason(Enum):
    STOP = "STOP"
    MAX_TOKENS = "MAX_TOKENS"
    SAFETY = "SAFETY"


@pytest.mark.parametrize("provider", ["gemini", "vertex_ai"])
@pytest.mark.parametrize("reason", list(FinishReason))
async def test_genai_preserves_native_finish_reason_and_usage(provider, reason):
    llm = client(provider)
    response = NS(text=None if reason == FinishReason.SAFETY else "answer",
                  candidates=[NS(finish_reason=reason, content=None, finish_message="terminal",
                                 safety_ratings=[])],
                  usage_metadata=NS(prompt_token_count=10, candidates_token_count=None,
                                    thoughts_token_count=20, total_token_count=30))
    sdk = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=response))))
    setattr(llm, f"{provider}_client", sdk)
    setattr(llm, f"{provider}_model", "offline-model")
    result = await llm.generate("answer")
    assert result["finish_reason"] == reason.value
    assert result["provider_metadata"]["finish_message"] == "terminal"
    assert result["provider_metadata"]["usage"]["thoughts_token_count"] == 20
    assert result["tokens"]["total"] == 30
    json.dumps(result)


async def test_genai_blocked_prompt_has_no_candidates():
    llm = client("gemini")
    response = NS(text=None, candidates=[], usage_metadata=None,
                  prompt_feedback=NS(block_reason="PROHIBITED_CONTENT"))
    llm.gemini_client = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=response))))
    llm.gemini_model = "offline-model"
    result = await llm.generate("answer")
    assert result["finish_reason"] == "PROHIBITED_CONTENT"
    assert result["provider_metadata"]["prompt_feedback"]["block_reason"] == "PROHIBITED_CONTENT"


async def test_vllm_preserves_finish_reason(monkeypatch):
    llm = client("vllm")
    llm.vllm_endpoint = "http://offline.invalid"
    response = MagicMock(status=200)
    response.json = AsyncMock(return_value={
        "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    })
    response.__aenter__ = AsyncMock(return_value=response)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.post.return_value = response
    monkeypatch.setattr("jarviscore.execution.llm.aiohttp.ClientSession", lambda **kw: session)
    result = await llm.generate("answer")
    assert result["finish_reason"] == "length"
    assert result["provider_metadata"]["usage"]["completion_tokens"] == 20


def agent_with(response):
    agent = MiniAuto()
    agent._kernel = MagicMock()
    agent.llm = NS(generate=AsyncMock(return_value={
        "content": "answer", "provider": "fake", "model": "test-model",
        "tokens": {"input": 10, "output": 4000, "total": 4010}, "cost_usd": 0.1,
        **response,
    }))
    return agent


async def execute(agent, **contract):
    result = await agent.execute_task({"task": "answer", "context": {
        "execution_contract": {"execution_shape": "single_response", **contract},
    }})
    agent._kernel.execute.assert_not_called()
    return result


@pytest.mark.parametrize("content", [None, "", " \n\t"])
async def test_empty_is_failure_without_claiming_truncation(content):
    agent = agent_with({"content": content})
    result = await execute(agent)
    assert result["status"] == "failure"
    assert "empty" in result["error"]
    assert "truncat" not in result["error"]
    assert result["tokens"]["output"] == 4000
    agent.llm.generate.assert_awaited_once()


@pytest.mark.parametrize("reason", [
    "length", "max_tokens", "MAX_TOKENS", "max_output_tokens", "content_filter",
    "SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY",
    "MALFORMED_FUNCTION_CALL", "tool_calls", "function_call", "tool_use", "pause_turn",
    "refusal", "incomplete", "failed", "cancelled", "OTHER",
])
async def test_incomplete_preserves_partial_content_and_diagnostics(reason):
    metadata = {"finish_reason": reason, "usage": {"reasoning_tokens": 3000}}
    agent = agent_with({"content": "partial", "finish_reason": reason, "provider_metadata": metadata})
    result = await execute(agent)
    assert result["status"] == "failure"
    assert result["output"] == result["payload"] == "partial"
    assert result["finish_reason"] == reason
    assert result["provider_metadata"] == metadata
    assert result["provider"] == "fake" and result["model"] == "test-model"
    assert result["cost_usd"] == 0.1 and result["tokens"]["output"] == 4000
    assert result["execution_shape"] == "single_response"
    agent.llm.generate.assert_awaited_once()


@pytest.mark.parametrize("reason", [None, "stop", "STOP", "end_turn", "stop_sequence", "completed"])
async def test_complete_or_legacy_nonempty_is_success_even_at_token_limit(reason):
    agent = agent_with({"finish_reason": reason})
    result = await execute(agent)
    assert result["status"] == "success"
    assert result["finish_reason"] == reason
    assert "max_tokens" not in agent.llm.generate.call_args.kwargs


@pytest.mark.parametrize("metadata", [{"refusal": "refused"}, {"status": "incomplete"}])
async def test_provider_metadata_can_indicate_non_answer(metadata):
    result = await execute(agent_with({"finish_reason": "stop", "provider_metadata": metadata}))
    assert result["status"] == "failure"


async def test_tool_call_is_not_a_completed_answer():
    result = await execute(agent_with({"finish_reason": "STOP", "tool_calls": [{"name": "lookup"}]}))
    assert result["status"] == "failure"
    assert result["tool_calls"] == [{"name": "lookup"}]


async def test_explicit_output_budget_is_forwarded_once():
    agent = agent_with({"finish_reason": "stop"})
    assert (await execute(agent, max_output_tokens=8192))["status"] == "success"
    assert agent.llm.generate.call_args.kwargs["max_tokens"] == 8192
    agent.llm.generate.assert_awaited_once()


@pytest.mark.parametrize("budget", [0, -1, True, "8000", 1.5, None])
async def test_invalid_output_budget_fails_before_model_call(budget):
    agent = agent_with({})
    result = await execute(agent, max_output_tokens=budget)
    assert result["status"] == "failure"
    assert "max_output_tokens" in result["error"]
    agent.llm.generate.assert_not_awaited()


async def test_cancellation_is_propagated():
    agent = agent_with({})
    agent.llm.generate.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await execute(agent)


@pytest.mark.parametrize("status", ["failed", "cancelled", "incomplete"])
async def test_responses_without_usage_keeps_failure_diagnostics(status):
    llm = client("azure")
    response = NS(output_text="partial", status=status, usage=None,
                  incomplete_details=None, error=NS(code="server_error"))
    llm.azure_client = NS(responses=NS(create=AsyncMock(return_value=response)))
    result = await llm.generate("answer", model="gpt-5-codex")
    assert result["finish_reason"] == status
    assert result["provider_metadata"]["error"] == {"code": "server_error"}
    assert result["provider_metadata"]["usage"] is None
    assert result["tokens"] == {"input": 0, "output": 0, "total": 0}
    assert result["content"] == "partial"
    json.dumps(result)


@pytest.mark.parametrize("provider", ["gemini", "vertex_ai"])
async def test_genai_mixed_tool_call_keeps_partial_text(provider):
    from google.genai import types

    llm = client(provider)
    response = types.GenerateContentResponse(
        candidates=[types.Candidate(
            finish_reason=types.FinishReason.STOP,
            content=types.Content(parts=[
                types.Part(text="partial explanation"),
                types.Part(function_call=types.FunctionCall(name="lookup", args={"q": "test"})),
            ]),
        )],
    )
    sdk = NS(aio=NS(models=NS(generate_content=AsyncMock(return_value=response))))
    setattr(llm, f"{provider}_client", sdk)
    setattr(llm, f"{provider}_model", "offline-model")
    agent = agent_with({})
    agent.llm = llm
    result = await execute(agent)
    assert result["status"] == "failure"
    assert result["output"] == result["payload"] == "partial explanation"
    assert result["tool_calls"] == [{"name": "lookup", "args": {"q": "test"}}]
    sdk.aio.models.generate_content.assert_awaited_once()
    json.dumps(result)


async def test_responses_function_call_with_text_is_not_complete():
    llm = client("azure")
    response = NS(output_text="partial explanation", status="completed", usage=None,
                  output=[NS(type="function_call", name="lookup", arguments="{}", call_id="call1")])
    llm.config["azure_deployment"] = "gpt-5-codex"
    llm.azure_client = NS(responses=NS(create=AsyncMock(return_value=response)))
    agent = agent_with({})
    agent.llm = llm
    result = await execute(agent)
    assert result["status"] == "failure"
    assert result["output"] == "partial explanation"
    assert result["provider_metadata"]["tool_calls"][0]["name"] == "lookup"
    json.dumps(result)


async def test_partial_output_is_preserved_verbatim():
    result = await execute(agent_with({"content": "  partial\n", "finish_reason": "length"}))
    assert result["status"] == "failure"
    assert result["output"] == result["payload"] == "  partial\n"


@pytest.mark.parametrize("provider,reason", [
    ("azure", "length"), ("azure", "stop"), ("azure", None),
    ("claude", "max_tokens"), ("claude", "end_turn"), ("claude", None),
    ("gemini", "MAX_TOKENS"), ("gemini", "STOP"), ("gemini", None),
    ("vertex_ai", "SAFETY"), ("vertex_ai", "STOP"), ("vertex_ai", None),
    ("promo", "length"), ("promo", "stop"), ("promo", None),
])
async def test_adapter_to_single_response_contract(provider, reason):
    llm = client(provider)
    if provider == "azure":
        response = NS(choices=[NS(finish_reason=reason, message=NS(content="answer"))],
                      usage=NS(prompt_tokens=10, completion_tokens=20, total_tokens=30))
        call = AsyncMock(return_value=response)
        llm.azure_client = NS(chat=NS(completions=NS(create=call)))
    elif provider == "claude":
        response = NS(content=[NS(text="answer")], stop_reason=reason,
                      usage=NS(input_tokens=10, output_tokens=20))
        call = MagicMock(return_value=response)
        llm.claude_client = NS(messages=NS(create=call))
    elif provider == "promo":
        response = {"content": "answer", "finish_reason": reason, "provider": "promo",
                    "model": "jarviscore-promo", "tokens": {"input": 10, "output": 20, "total": 30}}
        call = AsyncMock(return_value=response)
        llm.promo_client = NS(generate=call)
    else:
        response = NS(text="answer", candidates=[NS(content=None, finish_reason=reason)],
                      usage_metadata=NS(prompt_token_count=10, candidates_token_count=20))
        call = AsyncMock(return_value=response)
        sdk = NS(aio=NS(models=NS(generate_content=call)))
        setattr(llm, f"{provider}_client", sdk)
        setattr(llm, f"{provider}_model", "offline-model")
    agent = agent_with({})
    agent.llm = llm
    result = await execute(agent, max_output_tokens=8192)
    expected = "success" if reason in (None, "stop", "STOP", "end_turn") else "failure"
    assert result["status"] == expected
    assert result["finish_reason"] == reason
    assert result["output"] == "answer"
    assert result["provider"] == provider
    assert result["tokens"] == {"input": 10, "output": 20, "total": 30}
    call.assert_called_once()
    options = call.call_args.kwargs
    budget = (options.get("max_completion_tokens") if provider == "azure"
              else options["config"]["max_output_tokens"] if provider in ("gemini", "vertex_ai")
              else options["max_tokens"])
    assert budget == 8192
    json.dumps(result)


async def test_provider_exception_is_a_failure_without_retry():
    agent = agent_with({})
    agent.llm.generate.side_effect = RuntimeError("offline failure")
    result = await execute(agent)
    assert result["status"] == "failure"
    assert "offline failure" in result["error"]
    agent.llm.generate.assert_awaited_once()


@pytest.mark.parametrize("options,budget", [({}, 1234), ({"max_tokens": 2222}, 2222),
                                          ({"max_completion_tokens": 3333}, 3333)])
async def test_generate_preserves_configured_and_explicit_budgets(options, budget):
    llm = client("promo")
    llm.config["llm_default_max_tokens"] = 1234
    llm.promo_client = NS(generate=AsyncMock(return_value={"content": "answer"}))
    await llm.generate("answer", **options)
    assert llm.promo_client.generate.call_args.kwargs["max_tokens"] == budget