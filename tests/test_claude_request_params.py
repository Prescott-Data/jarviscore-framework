"""Claude requests carry only the parameters the model accepts."""

import asyncio
from types import SimpleNamespace

import pytest

from jarviscore.execution import native_tools
from jarviscore.execution.llm import UnifiedLLMClient, _claude_accepts_sampling


@pytest.mark.parametrize(
    "model",
    ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-sonnet-5",
     "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-fable-5-1",
     "claude-mythos-5-1", "anthropic.claude-opus-5-5"],
)
def test_newer_models_get_no_temperature(model):
    assert not _claude_accepts_sampling(model)


@pytest.mark.parametrize(
    "model", ["claude-sonnet-4-5", "claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5",
              "claude-sonnet-4", "claude-3-5-haiku-latest"],
)
def test_older_models_keep_temperature(model):
    assert _claude_accepts_sampling(model)


@pytest.mark.parametrize(
    "model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-mythos-5-1"]
)
def test_required_is_asked_as_auto_where_forcing_is_refused(model):
    assert native_tools.anthropic_tool_choice("required", True, model) == {"type": "auto"}


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "claude-opus-5", "claude-sonnet-4-5", ""])
def test_required_stays_forced_where_accepted(model):
    assert native_tools.anthropic_tool_choice("required", True, model) == {"type": "any"}
    assert native_tools.anthropic_tool_choice("required", False, model) == {
        "type": "any", "disable_parallel_tool_use": True,
    }


def _send(model):
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text="ok")],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            stop_reason="end_turn", stop_sequence=None,
        )

    client = UnifiedLLMClient.__new__(UnifiedLLMClient)
    client.claude_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.config = {}
    tools = [{"type": "function", "function": {"name": "t", "description": "d",
                                               "parameters": {"type": "object", "properties": {}}}}]
    asyncio.run(client._call_claude(
        [{"role": "user", "content": "hi"}], 0.7, 50, model=model, tools=tools,
        tool_choice="required", parallel_tool_calls=True,
    ))
    return sent


def test_a_claude_5_request_is_one_the_api_accepts():
    sent = _send("claude-opus-5-5")
    assert "temperature" not in sent and sent["tool_choice"] == {"type": "auto"}


def test_an_older_claude_request_is_unchanged():
    sent = _send("claude-sonnet-4-5")
    assert sent["temperature"] == 0.7 and sent["tool_choice"] == {"type": "any"}


def test_claude_5_calls_are_priced():
    from jarviscore.execution.llm import _call_cost

    cost, source = _call_cost("claude-opus-5-5", 1_000_000, 1_000_000)
    assert source == "builtin" and cost == 24.0
