import pytest
from pydantic import BaseModel
from jarviscore.kernel.defaults.coder import CoderSubAgent

class UserProfile(BaseModel):
    name: str
    age: int

@pytest.mark.asyncio
async def test_output_schema_enforcement():
    class MockSandbox:
        async def execute(self, code, context=None):
            return {
                "status": "success",
                "output": {"data": {"name": "John"}} # Missing age
            }

    agent = CoderSubAgent(agent_id="test", llm_client=None, sandbox=MockSandbox())
    agent._run_context = {"output_schema": UserProfile}

    result = await agent._tool_execute_code(code="pass")

    assert result["status"] == "failure"
    assert "Output schema validation failed" in result["error"]
    assert "age" in result["error"]

@pytest.mark.asyncio
async def test_output_schema_success():
    class MockSandbox:
        async def execute(self, code, context=None):
            return {
                "status": "success",
                "output": {"data": {"name": "John", "age": 30}}
            }

    agent = CoderSubAgent(agent_id="test", llm_client=None, sandbox=MockSandbox())
    agent._run_context = {"output_schema": UserProfile}

    result = await agent._tool_execute_code(code="pass")

    assert result["status"] == "success"
