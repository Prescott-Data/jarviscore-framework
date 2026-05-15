import pytest
from unittest.mock import AsyncMock, patch
from jarviscore.kernel.defaults.coder import CoderSubAgent

@pytest.mark.asyncio
async def test_intent_normalizer_called():
    class DummyRegistry:
        def semantic_search(self, task, limit=5):
            return []

    class DummyLLM:
        async def generate(self, messages, **kwargs):
            return {"content": "fetch user profile"}

    agent = CoderSubAgent(agent_id="test", llm_client=DummyLLM(), code_registry=DummyRegistry())

    # We pass a verbose task
    task = "Hello! I would like you to fetch the user profile for user ID 123. Please format it nicely."

    # Check registry should normalize it to "fetch user profile" and do semantic search
    with patch.object(DummyRegistry, "semantic_search", return_value=[]) as mock_search:
        result = await agent._tool_check_registry(task=task)
        print("Result:", result)

        # It should call semantic_search with the normalized task, not the verbose one
        mock_search.assert_called_once_with("fetch user profile", limit=5)
