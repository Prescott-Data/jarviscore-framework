from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.llm import LLMProvider, UnifiedLLMClient


class Chunk:
    def __init__(self, text="", finish=None, usage=None):
        self.choices = [
            SimpleNamespace(index=0, delta=SimpleNamespace(content=text), finish_reason=finish)
        ]
        self.usage = usage
        self.text, self.finish = text, finish

    def model_dump(self, mode):
        return {"delta": self.text, "finish_reason": self.finish, "tail_metadata": "preserved"}


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.close = AsyncMock()

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def client(stream):
    value = UnifiedLLMClient.__new__(UnifiedLLMClient)
    value.provider_order = [LLMProvider.AZURE]
    value.config = {"azure_deployment": "gpt-5.5"}
    value._semaphore = None
    value.azure_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=stream)))
    )
    return value


@pytest.mark.asyncio
async def test_stream_delivers_native_chunks_and_complete_large_tail():
    stream = Stream([Chunk("evidence " * 30000), Chunk("TAIL connected_to"), Chunk(finish="stop")])
    value = client(stream)
    events = [
        e async for e in value.generate_stream(messages=[{"role": "user", "content": "Hello"}])
    ]
    assert events[0]["text"] == "evidence " * 30000
    assert events[1]["raw"]["tail_metadata"] == "preserved"
    assert events[-1]["result"]["content"] == "evidence " * 30000 + "TAIL connected_to"
    assert events[-1]["result"]["finish_reason"] == "stop"
    assert events[-1]["result"]["tokens"] is None
    stream.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_completion_reason_raises_after_delivering_partial_evidence():
    stream = Stream([Chunk("Partial reply")])
    iterator = client(stream).generate_stream(messages=[])
    assert (await anext(iterator))["text"] == "Partial reply"
    with pytest.raises(RuntimeError, match="completion reason"):
        await anext(iterator)
    stream.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_unsupported_selected_provider_fails_without_fallback():
    value = client(Stream([]))
    value.provider_order = [LLMProvider.CLAUDE, LLMProvider.AZURE]
    with pytest.raises(RuntimeError, match="selected provider"):
        await anext(value.generate_stream(messages=[]))
    value.azure_client.chat.completions.create.assert_not_awaited()
