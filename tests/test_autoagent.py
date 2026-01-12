"""
Tests for AutoAgent profile.
"""
import pytest
from jarviscore.profiles.autoagent import AutoAgent


class ValidAutoAgent(AutoAgent):
    """Valid AutoAgent for testing."""
    role = "test_auto"
    capabilities = ["testing"]
    system_prompt = "You are a test agent that performs testing tasks."


class NoPromptAutoAgent(AutoAgent):
    """AutoAgent without system_prompt (should fail)."""
    role = "no_prompt"
    capabilities = ["testing"]


class TestAutoAgentInitialization:
    """Test AutoAgent initialization."""

    def test_valid_autoagent_creation(self):
        """Test creating a valid AutoAgent."""
        agent = ValidAutoAgent()

        assert agent.role == "test_auto"
        assert agent.capabilities == ["testing"]
        assert agent.system_prompt == "You are a test agent that performs testing tasks."

    def test_autoagent_without_system_prompt_fails(self):
        """Test that AutoAgent without system_prompt raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            NoPromptAutoAgent()

        assert "must define 'system_prompt'" in str(exc_info.value)

    def test_autoagent_execution_components_initially_none(self):
        """Test that execution components are initially None."""
        agent = ValidAutoAgent()

        assert agent.llm is None
        assert agent.codegen is None
        assert agent.sandbox is None
        assert agent.repair is None


class TestAutoAgentSetup:
    """Test AutoAgent setup."""

    @pytest.mark.asyncio
    async def test_autoagent_setup(self):
        """Test AutoAgent setup hook."""
        agent = ValidAutoAgent()
        await agent.setup()

        # Day 1: Just verify it runs without error
        # Day 4: Will test actual LLM initialization


class TestAutoAgentExecution:
    """Test AutoAgent task execution."""

    @pytest.mark.asyncio
    async def test_execute_task_without_setup_fails(self):
        """Test AutoAgent execute_task fails gracefully without setup."""
        agent = ValidAutoAgent()

        task = {"task": "Test task description"}
        result = await agent.execute_task(task)

        # Day 4: Should fail gracefully when components not initialized
        assert result["status"] == "failure"
        assert "Fatal error" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_execute_task_with_mock_components(self):
        """Test AutoAgent with mocked execution components."""
        from unittest.mock import Mock, AsyncMock

        agent = ValidAutoAgent()

        # Mock the execution components
        agent.codegen = Mock()
        agent.codegen.generate = AsyncMock(return_value="result = 42")

        agent.sandbox = Mock()
        agent.sandbox.execute = AsyncMock(return_value={
            "status": "success",
            "output": 42
        })

        agent.repair = Mock()  # Not called if execution succeeds

        # Mock result handler (Phase 1)
        agent.result_handler = Mock()
        agent.result_handler.process_result = Mock(return_value={
            'result_id': 'test-result-id',
            'status': 'success'
        })

        # Mock code registry (Phase 3)
        agent.code_registry = Mock()
        agent.code_registry.register = Mock(return_value='test-function-id')

        task = {"task": "Calculate 21 * 2"}
        result = await agent.execute_task(task)

        # Should succeed with mocked components
        assert result["status"] == "success"
        assert result["output"] == 42
        assert result["code"] == "result = 42"


class TestAutoAgentInheritance:
    """Test AutoAgent inheritance from Profile and Agent."""

    def test_autoagent_inherits_agent_methods(self):
        """Test that AutoAgent inherits Agent methods."""
        agent = ValidAutoAgent()

        # Should have Agent methods
        assert hasattr(agent, "can_handle")
        assert hasattr(agent, "execute_task")
        assert hasattr(agent, "setup")
        assert hasattr(agent, "teardown")

    def test_autoagent_can_handle_tasks(self):
        """Test that AutoAgent can check task compatibility."""
        agent = ValidAutoAgent()

        task1 = {"role": "test_auto", "task": "Do something"}
        assert agent.can_handle(task1) is True

        task2 = {"capability": "testing", "task": "Run tests"}
        assert agent.can_handle(task2) is True

        task3 = {"role": "different", "task": "Won't handle"}
        assert agent.can_handle(task3) is False
