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


def _declining(config):
    """A client whose first model declines; answers with what was asked and the result."""
    asked = []

    def create(**kwargs):
        asked.append(kwargs)
        if len(asked) == 1:
            return SimpleNamespace(
                content=[], usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
                stop_reason="refusal", stop_sequence=None,
                stop_details=SimpleNamespace(category="reasoning_extraction"),
            )
        return SimpleNamespace(
            content=[SimpleNamespace(text="Two mentions.")],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=50),
            stop_reason="end_turn", stop_sequence=None,
        )

    client = UnifiedLLMClient.__new__(UnifiedLLMClient)
    client.claude_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.config = config
    tools = [{"type": "function", "function": {"name": "t", "description": "d",
                                               "parameters": {"type": "object", "properties": {}}}}]
    out = asyncio.run(client._call_claude(
        [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}], 0.7, 50,
        model="claude-opus-5-5", tools=tools, tool_choice="required", parallel_tool_calls=True,
    ))
    return asked, out


def test_a_declined_request_is_asked_once_of_the_declared_fallback_model():
    """A classifier decline is HTTP 200 with no content: to a caller, a model that said
    nothing. The same request goes to the fallback, shaped for that model."""
    asked, out = _declining({"claude_refusal_fallback_model": "claude-opus-4-8"})
    assert [a["model"] for a in asked] == ["claude-opus-5-5", "claude-opus-4-8"]
    first, second = asked
    assert second["messages"] == first["messages"] and second["system"] == first["system"]
    assert first["tool_choice"] == {"type": "auto"}  # 5.5 cannot be forced
    assert second["tool_choice"] == {"type": "any"}  # 4.8 can: the caller asked for a call
    assert out["content"] == "Two mentions." and out["finish_reason"] == "end_turn"
    assert out["model"] == "claude-opus-4-8"
    assert out["provider_metadata"]["declined"] == {
        "model": "claude-opus-5-5", "category": "reasoning_extraction"}
    # both attempts are counted: the declined one read the request too
    assert out["tokens"] == {"input": 2000, "output": 250, "total": 2250}
    assert out["cost_usd"] > 0


def test_without_a_fallback_a_declined_request_is_returned_as_declined():
    asked, out = _declining({})
    assert len(asked) == 1
    assert out["finish_reason"] == "refusal" and out["content"] == ""
    assert out["provider_metadata"]["declined"]["category"] == "reasoning_extraction"
    asked, out = _declining({"claude_refusal_fallback_model": "claude-opus-5-5"})
    assert len(asked) == 1  # the fallback is the model that declined: not asked again


TOOL = [{"type": "function", "function": {"name": "t", "description": "d",
                                          "parameters": {"type": "object", "properties": {}}}}]
LOOP = [
    {"role": "system", "content": "You act for one person."},
    {"role": "user", "content": "the task"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "function": {"name": "t", "arguments": "{}"}}]},
    {"role": "tool", "tool_call_id": "c1", "content": "a long document"},
    {"role": "user", "content": "state that changed this turn"},
]


def _loop(config, messages=LOOP, tools=TOOL, usage=None):
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text="ok")], stop_reason="end_turn", stop_sequence=None,
            usage=usage or SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    client = UnifiedLLMClient.__new__(UnifiedLLMClient)
    client.claude_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.config = config
    extra = {"tools": tools, "tool_choice": "required"} if tools else {}
    out = asyncio.run(client._call_claude(messages, 0.7, 50, model="claude-opus-5-5", **extra))
    return sent, out


def test_a_tool_loops_request_marks_the_system_prompt_and_tools_by_default():
    """Anthropic caches only where asked. The system prompt, with the tools before it, is
    the same on every turn of a loop: marked, it is read from the cache from turn two on."""
    sent, _ = _loop({})
    assert sent["system"] == [{"type": "text", "text": "You act for one person.",
                               "cache_control": {"type": "ephemeral"}}]
    assert not any("cache_control" in b for t in sent["messages"] for b in t["content"])


def test_a_conversation_that_only_grows_can_be_marked_up_to_its_last_tool_result():
    """For a caller whose requests extend one another unchanged: the conversation up to its
    last tool result is in the next request too; the state after it is not, so the mark goes
    before it."""
    sent, _ = _loop({"claude_prompt_cache": "conversation"})
    assert sent["system"] == [{"type": "text", "text": "You act for one person.",
                               "cache_control": {"type": "ephemeral"}}]
    last = sent["messages"][-1]["content"]
    assert [block["type"] for block in last] == ["tool_result", "text"]
    assert last[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in last[1]  # this turn's state is not in the next request
    marks = sum("cache_control" in block for turn in sent["messages"] for block in turn["content"])
    assert marks == 1 and "cache_control" not in sent["tools"][-1]


def test_a_request_with_no_tools_or_with_caching_off_is_sent_as_before():
    """One-shot calls (a plan, a summary) repeat nothing: a cache write there is only cost."""
    sent, _ = _loop({}, tools=None)
    assert sent["system"] == "You act for one person."
    assert not any("cache_control" in b for t in sent["messages"] for b in t["content"])
    sent, _ = _loop({"claude_prompt_cache": "off"})
    assert sent["system"] == "You act for one person."
    assert not any("cache_control" in b for t in sent["messages"] for b in t["content"])


def test_with_no_system_prompt_the_tools_are_marked_and_the_inputs_are_left_alone():
    turns = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    tools = [{"name": "a"}, {"name": "b"}]
    system, marked, marked_tools = native_tools.anthropic_cache_points(None, turns, tools)
    assert system is None and marked == turns
    assert marked_tools == [{"name": "a"}, {"name": "b", "cache_control": {"type": "ephemeral"}}]
    assert tools == [{"name": "a"}, {"name": "b"}]  # not changed in place


def test_cache_reads_and_writes_are_counted_and_priced():
    """Claude reports cached and written input beside input_tokens. All of it is input; a
    read bills at the cached rate, a write a quarter above the input rate."""
    from jarviscore.execution.llm import _call_cost

    usage = SimpleNamespace(input_tokens=1_000, output_tokens=100,
                            cache_read_input_tokens=100_000, cache_creation_input_tokens=10_000)
    _, out = _loop({}, usage=usage)
    assert out["tokens"] == {"input": 111_000, "output": 100, "total": 111_100}
    # opus 5.5: $4 in, $0.20 cached, $20 out per million
    expected = (1_000 * 4 + 100_000 * 0.20 + 10_000 * 4 * 1.25 + 100 * 20) / 1_000_000
    assert out["cost_usd"] == pytest.approx(expected)
    uncached, _ = _call_cost("claude-opus-5-5", 111_000, 100)
    assert out["cost_usd"] < uncached / 5
