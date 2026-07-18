"""
Tests for issues #61 and #62.

#61 — _parse_response directive precedence:
- A quoted "DONE:" line before a real TOOL call must not falsely complete
- A quoted TOOL example before a real DONE must still complete
- RESULT alone only completes when it carries structured JSON
- Single-directive responses parse exactly as before (non-breaking)

#62 — WorkflowEngine result identity:
- Every result in the returned list carries step_id — success included
- Results that already carry a step_id keep it
"""

from typing import Any, Dict

import pytest

from jarviscore.kernel.subagent import BaseSubAgent


parse = BaseSubAgent._parse_response


# ======================================================================
# #61 — directive precedence
# ======================================================================

class TestDirectivePrecedence:

    def test_quoted_done_before_real_tool_executes_the_tool(self):
        content = (
            "THOUGHT: I still need the schema. Once I have it I will emit\n"
            "DONE: <summary> as instructed.\n"
            "TOOL: fetch_schema\n"
            'PARAMS: {"url": "https://api.example.com/spec"}'
        )
        parsed = parse(content)
        assert parsed["type"] == "tool"
        assert parsed["tool"] == "fetch_schema"
        assert parsed["params"] == {"url": "https://api.example.com/spec"}

    def test_quoted_tool_example_before_real_done_completes(self):
        content = (
            "THOUGHT: earlier I ran\n"
            "TOOL: web_search\n"
            "which gave me everything I need, so I am finishing.\n"
            "DONE: research complete\n"
            'RESULT: {"finding": "x"}'
        )
        parsed = parse(content)
        assert parsed["type"] == "done"
        assert parsed["summary"] == "research complete"
        assert parsed["result"] == {"finding": "x"}

    def test_plain_tool_response_unchanged(self):
        content = (
            "THOUGHT: need data\n"
            "TOOL: web_search\n"
            'PARAMS: {"query": "AML trends"}'
        )
        parsed = parse(content)
        assert parsed["type"] == "tool"
        assert parsed["tool"] == "web_search"

    def test_plain_done_response_unchanged(self):
        content = (
            "THOUGHT: finished\n"
            "DONE: all wrapped up\n"
            'RESULT: {"answer": 42}'
        )
        parsed = parse(content)
        assert parsed["type"] == "done"
        assert parsed["result"] == {"answer": 42}

    def test_done_without_result_still_completes(self):
        parsed = parse("THOUGHT: ok\nDONE: summary only")
        assert parsed["type"] == "done"
        assert parsed["summary"] == "summary only"


class TestResultAloneRequiresJson:

    def test_result_alone_with_json_completes(self):
        parsed = parse('RESULT: {"answer": 42}')
        assert parsed["type"] == "done"
        assert parsed["result"] == {"answer": 42}

    def test_result_alone_prose_is_not_a_completion(self):
        parsed = parse("THOUGHT: the final\nRESULT: pending — need one more read")
        assert parsed["type"] == "raw"

    def test_done_with_prose_result_keeps_historical_behavior(self):
        parsed = parse("DONE: finished\nRESULT: plain text answer")
        assert parsed["type"] == "done"
        assert parsed["result"] == "plain text answer"


# ======================================================================
# #62 — every engine result carries step_id
# ======================================================================

from jarviscore import Mesh, MeshMode  # noqa: E402
from jarviscore.core.agent import Agent  # noqa: E402


class EchoAgent(Agent):
    role = "echo"
    capabilities = ["echo"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": task.get("task", "")}


class FailingAgent(Agent):
    role = "boom"
    capabilities = ["boom"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "failure", "error": "kaput"}


class SelfIdentifyingAgent(Agent):
    role = "selfid"
    capabilities = ["selfid"]

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "success", "output": "x", "step_id": "my-own-identity"}


@pytest.mark.asyncio
class TestResultIdentity:

    async def test_success_results_carry_step_id(self):
        mesh = Mesh(mode=MeshMode.AUTONOMOUS)
        mesh.add(EchoAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-id-success", [
                {"id": "alpha", "agent": "echo", "task": "one"},
                {"id": "beta", "agent": "echo", "task": "two"},
            ])
        finally:
            await mesh.stop()

        assert [r["step_id"] for r in results] == ["alpha", "beta"]
        assert all(r["status"] == "success" for r in results)

    async def test_mixed_success_and_failure_all_carry_step_id(self):
        mesh = Mesh(mode=MeshMode.AUTONOMOUS)
        mesh.add(EchoAgent)
        mesh.add(FailingAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-id-mixed", [
                {"id": "ok", "agent": "echo", "task": "fine"},
                {"id": "bad", "agent": "boom", "task": "explode"},
            ])
        finally:
            await mesh.stop()

        assert [r["step_id"] for r in results] == ["ok", "bad"]

    async def test_agent_supplied_step_id_is_respected(self):
        mesh = Mesh(mode=MeshMode.AUTONOMOUS)
        mesh.add(SelfIdentifyingAgent)
        await mesh.start()
        try:
            results = await mesh.workflow("wf-id-own", [
                {"id": "engine-id", "agent": "selfid", "task": "t"},
            ])
        finally:
            await mesh.stop()

        assert results[0]["step_id"] == "my-own-identity"
