"""extract_api_details turns documentation into api_specs through the researcher's own model client."""

import asyncio
import json

from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
from jarviscore.kernel.state import KernelState


class _SpecLLM:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return {"content": self.content, "tokens": {"input": 1, "output": 1, "total": 2}}


def _researcher(llm):
    r = ResearcherSubAgent(agent_id="r", llm_client=llm)
    r.current_state = KernelState(workflow_id="w", step_id="s", agent_id="r", task="t", context={})
    return r


def test_documentation_becomes_api_specs():
    spec = {"api_specs": [{"method": "POST", "path": "/v1/charges", "body_schema": {"amount": "int"}}]}
    llm = _SpecLLM(json.dumps(spec))
    r = _researcher(llm)

    result = asyncio.run(r._tool_extract_api_details("POST /v1/charges amount (int, required)"))

    assert "error" not in result
    assert r.current_state.internal_variables["api_specs"][0]["path"] == "/v1/charges"
    assert llm.calls[0]["response_format"] == {"type": "json_object"}


def test_long_documentation_is_read_whole():
    llm = _SpecLLM('{"api_specs": []}')
    page = "x" * 30_000 + " POST /v1/refunds"

    asyncio.run(_researcher(llm)._tool_extract_api_details(page))

    assert "POST /v1/refunds" in llm.calls[0]["messages"][-1]["content"]


def test_a_reply_without_json_is_reported_not_guessed():
    result = asyncio.run(_researcher(_SpecLLM("I could not find any endpoints."))._tool_extract_api_details("text"))

    assert result == {"error": "API extraction returned no JSON object"}
