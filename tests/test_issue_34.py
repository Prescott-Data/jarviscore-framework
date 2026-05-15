import pytest
from unittest.mock import AsyncMock, patch

from jarviscore.profiles.autoagent import AutoAgent

class DummyGoalAgent(AutoAgent):
    role = "test_goal_agent"
    capabilities = ["test"]
    system_prompt = "You are a test agent."
    goal_oriented = True

@pytest.mark.asyncio
@patch("jarviscore.planning.classifier.TaskComplexityClassifier")
async def test_complexity_gate_trivial(MockClassifier):
    # Setup mock classifier to return trivial
    mock_classifier_instance = AsyncMock()
    MockClassifier.return_value = mock_classifier_instance
    mock_classifier_instance.classify.return_value.level = "trivial"
    mock_classifier_instance.classify.return_value.reason = "Simple task"

    agent = DummyGoalAgent()
    # Mock LLM since setup isn't fully run
    agent.llm = AsyncMock()
    agent._kernel = AsyncMock()

    class MockOutput:
        status = "success"
        payload = {"result": "success"}
        summary = "Done"
        metadata = {}

    agent._kernel.execute.return_value = MockOutput()

    result = await agent.execute_task({"task": "Say hello"})

    # Assert classifier was called
    mock_classifier_instance.classify.assert_called_once_with("Say hello", context={})

    # Assert kernel was called directly.
    agent._kernel.execute.assert_called_once()

    # Result should be from the kernel
    assert result["status"] == "success"

@pytest.mark.asyncio
@patch("jarviscore.planning.classifier.TaskComplexityClassifier")
@patch.object(DummyGoalAgent, "execute_goal", new_callable=AsyncMock)
async def test_complexity_gate_complex(mock_execute_goal, MockClassifier):
    # Setup mock classifier to return complex
    mock_classifier_instance = AsyncMock()
    MockClassifier.return_value = mock_classifier_instance
    mock_classifier_instance.classify.return_value.level = "complex"
    mock_classifier_instance.classify.return_value.reason = "Needs planning"

    agent = DummyGoalAgent()
    agent.llm = AsyncMock()

    class MockGoalExecution:
        status = "complete"
        result = "Done"
        error = None
        def to_summary_dict(self):
            return {}

    mock_execute_goal.return_value = MockGoalExecution()

    result = await agent.execute_task({"task": "Do research"})

    # Assert classifier was called
    mock_classifier_instance.classify.assert_called_once_with("Do research", context={})

    # Assert execute_goal was called.
    mock_execute_goal.assert_called_once()

    # Result should be from the goal execution
    assert result["status"] == "success"

@pytest.mark.asyncio
@patch("jarviscore.planning.classifier.TaskComplexityClassifier")
@patch.object(DummyGoalAgent, "execute_goal", new_callable=AsyncMock)
async def test_complexity_gate_failure_is_visible(mock_execute_goal, MockClassifier):
    mock_classifier_instance = AsyncMock()
    MockClassifier.return_value = mock_classifier_instance
    mock_classifier_instance.classify.side_effect = RuntimeError("invalid classifier JSON")

    agent = DummyGoalAgent()
    agent.llm = AsyncMock()

    result = await agent.execute_task({"task": "Do research"})

    assert result["status"] == "failure"
    assert "Complexity classification failed" in result["error"]
    mock_execute_goal.assert_not_called()
