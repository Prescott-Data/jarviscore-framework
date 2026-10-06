"""Images a tool observes reach the model as images, on every provider."""

import asyncio
import base64
import json
import struct
import zlib
from types import SimpleNamespace

import pytest

from jarviscore.execution import multimodal
from jarviscore.execution.llm import UnifiedLLMClient
from jarviscore.execution.multimodal import OBSERVED_IMAGES, Image
from jarviscore.kernel.subagent import BaseSubAgent


def _png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


SHOT = _png(1280, 720)


def _image_message():
    return {"role": "user", "content": multimodal.with_images("What is on the page?", [Image(SHOT)])}


def test_split_images_leaves_a_receipt_and_no_pixels():
    result, images = multimodal.split_images({"status": "success", OBSERVED_IMAGES: [Image(SHOT, label="page")]})

    assert images == [Image(SHOT, label="page")]
    receipt = result[OBSERVED_IMAGES][0]
    assert receipt["width"] == 1280 and receipt["height"] == 720
    assert receipt["bytes"] == len(SHOT)
    assert base64.b64encode(SHOT).decode() not in json.dumps(result)


def test_results_without_images_are_untouched():
    result = {"status": "success", "text": "hello"}
    assert multimodal.split_images(result) == (result, [])
    assert multimodal.split_images("plain") == ("plain", [])


def test_budget_reserves_image_tokens_not_base64_length():
    text_only = multimodal.count_tokens([{"role": "user", "content": "What is on the page?"}], lambda s: len(s) // 4)
    with_image = multimodal.count_tokens([_image_message()], lambda s: len(s) // 4)

    # 1280x720 scales to 1366x768: 3x2 tiles of 512px.
    assert with_image - text_only == pytest.approx(85 + 170 * 6, abs=10)


def test_claude_receives_a_base64_image_block():
    blocks = multimodal.to_anthropic(_image_message()["content"])

    assert blocks[0] == {"type": "text", "text": "What is on the page?"}
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"]["media_type"] == "image/png"
    assert base64.b64decode(blocks[1]["source"]["data"]) == SHOT


def test_responses_api_receives_input_image():
    message = multimodal.to_responses(_image_message())

    assert message["content"][0] == {"type": "input_text", "text": "What is on the page?"}
    assert message["content"][1]["type"] == "input_image"
    assert message["content"][1]["image_url"].startswith("data:image/png;base64,")


def test_gemini_receives_inline_image_bytes_in_order():
    contents = multimodal.to_genai([
        {"role": "system", "content": "You read pages."},
        _image_message(),
    ])

    assert contents[0].startswith("System: You read pages.")
    assert contents[0].rstrip().endswith("User: What is on the page?")
    assert contents[1].inline_data.data == SHOT
    assert contents[1].inline_data.mime_type == "image/png"


def test_text_only_providers_see_where_an_image_was():
    client = UnifiedLLMClient.__new__(UnifiedLLMClient)
    assert "User: What is on the page?\n[image]" in client._messages_to_prompt([_image_message()])


def test_claude_call_sends_image_block():
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text="a red page")],
            usage=SimpleNamespace(input_tokens=1100, output_tokens=3),
            stop_reason="end_turn",
            stop_sequence=None,
        )

    client = UnifiedLLMClient.__new__(UnifiedLLMClient)
    client.claude_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    client.config = {}
    reply = asyncio.run(client._call_claude([{"role": "system", "content": "s"}, _image_message()], 0.0, 50))

    assert reply["content"] == "a red page"
    assert sent["messages"][0]["content"][1]["type"] == "image"


class _RecordingLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def generate(self, messages=None, **kwargs):
        self.calls.append(messages)
        return {"content": self.replies.pop(0), "tokens": {"input": 1, "output": 1, "total": 2}, "cost_usd": 0.0}


class _LookingAgent(BaseSubAgent):
    def get_system_prompt(self) -> str:
        return "You look at pages."

    def setup_tools(self) -> None:
        self.register_tool("look", self._look, "See the page. Params: {}", phase="thinking")

    async def _look(self, **kwargs):
        return {"status": "success", OBSERVED_IMAGES: [Image(SHOT, label="the page")]}


def test_the_model_sees_the_screenshot_on_its_next_turn():
    llm = _RecordingLLM([
        "THOUGHT: look first\nTOOL: look\nPARAMS: {}",
        'THOUGHT: seen\nDONE: The page is red.\nRESULT: {"colour": "red"}',
    ])
    agent = _LookingAgent(agent_id="eyes", role="tester", llm_client=llm)

    asyncio.run(agent.run(task="What colour is the page?", max_turns=3))

    second_turn = llm.calls[1]
    observation = [m for m in second_turn if m["role"] == "user" and isinstance(m["content"], list)]
    assert len(observation) == 1
    image_part = observation[0]["content"][1]
    assert image_part["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(SHOT).decode()

    recorded = json.dumps(agent._current_state.model_dump(mode="json"), default=str)
    assert base64.b64encode(SHOT).decode() not in recorded
    assert "sha256" in recorded


def test_browser_screenshot_attaches_the_full_image():
    from jarviscore.kernel.defaults.browser import BrowserSubAgent

    class _Page:
        url = "https://example.com/"

        async def screenshot(self, full_page=False):
            return SHOT

        async def title(self):
            return "Example"

    agent = BrowserSubAgent(agent_id="b", llm_client=None)
    agent._page = _Page()
    result = asyncio.run(agent._tool_screenshot())

    assert result[OBSERVED_IMAGES][0].data == SHOT
    assert "screenshot_b64" not in result
