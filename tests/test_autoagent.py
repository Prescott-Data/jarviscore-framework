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
    async def test_execute_task_mock_implementation(self):
        """Test AutoAgent execute_task mock implementation (Day 1)."""
        agent = ValidAutoAgent()

        task = {"task": "Test task description"}
        result = await agent.execute_task(task)

        # Day 1: Mock implementation
        assert result["status"] == "success"
        assert "Mock result" in result["output"]
        assert result["tokens_used"] == 0
        assert result["cost_usd"] == 0.0
        assert "Day 4" in result["message"]

    @pytest.mark.asyncio
    async def test_execute_task_with_complex_task(self):
        """Test AutoAgent with complex task specification."""
        agent = ValidAutoAgent()

        task = {
            "task": "Scrape website and extract product data",
            "params": {
                "url": "https://example.com",
                "selectors": ["h1.title", "span.price"]
            }
        }

        result = await agent.execute_task(task)

        # Day 1: Still mock
        assert result["status"] == "success"
        assert "Mock result" in result["output"]


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
