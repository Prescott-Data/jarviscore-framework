import pytest
from jarviscore.execution.result_handler import ResultHandler
from jarviscore.kernel.defaults.coder import CoderSubAgent

@pytest.mark.asyncio
async def test_semantic_vs_syntactic_success_result_handler(tmp_path):
    handler = ResultHandler(log_directory=str(tmp_path))

    # 1. Syntactic success, semantic success
    res1 = handler.process_result(
        agent_id="test_agent",
        task="test",
        code="pass",
        output={"success": True, "data": "all good"},
        status="success"
    )
    assert res1["success"] is True
    assert res1["semantic_success"] is True

    # 2. Syntactic success, semantic failure (explicit success=False)
    res2 = handler.process_result(
        agent_id="test_agent",
        task="test",
        code="pass",
        output={"success": False, "error": "No data found"},
        status="success"
    )
    assert res2["success"] is True
    assert res2["semantic_success"] is False

    # 3. Syntactic success, semantic failure (explicit status="error")
    res3 = handler.process_result(
        agent_id="test_agent",
        task="test",
        code="pass",
        output={"status": "error", "error": "API rate limit"},
        status="success"
    )
    assert res3["success"] is True
    assert res3["semantic_success"] is False

@pytest.mark.asyncio
async def test_evaluator_hook_in_coder_subagent():
    # Mock sandbox
    class MockSandbox:
        async def execute(self, code, context=None):
            # Returns syntactic success but semantic failure
            return {
                "status": "success",
                "output": {"success": False, "error": "Mocked semantic failure"}
            }

    agent = CoderSubAgent(agent_id="test", llm_client=None, sandbox=MockSandbox())

    result = await agent._tool_execute_code(code="print('hello')")

    # The evaluator hook should override status to failure
    assert result["status"] == "failure"
    assert result["semantic_success"] is False
    assert result["error"] == "Mocked semantic failure"
