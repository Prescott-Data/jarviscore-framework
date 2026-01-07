"""
Tests for Agent base class.
"""
import pytest
from jarviscore.core.agent import Agent


# Test agent implementations
class ValidAgent(Agent):
    """Valid agent for testing."""
    role = "test_agent"
    capabilities = ["testing", "validation"]

    async def execute_task(self, task):
        return {"status": "success", "output": "test result"}


class NoRoleAgent(Agent):
    """Agent without role (should fail validation)."""
    capabilities = ["testing"]

    async def execute_task(self, task):
        return {"status": "success"}


class NoCapabilitiesAgent(Agent):
    """Agent without capabilities (should fail validation)."""
    role = "no_caps"

    async def execute_task(self, task):
        return {"status": "success"}


class TestAgentInitialization:
    """Test agent initialization and validation."""

    def test_valid_agent_creation(self):
        """Test creating a valid agent."""
        agent = ValidAgent()

        assert agent.role == "test_agent"
        assert agent.capabilities == ["testing", "validation"]
        assert agent.agent_id.startswith("test_agent-")
        assert len(agent.agent_id.split("-")[1]) == 8  # 8-char UUID

    def test_agent_with_custom_id(self):
        """Test creating agent with custom ID."""
        agent = ValidAgent(agent_id="custom-agent-123")

        assert agent.agent_id == "custom-agent-123"
        assert agent.role == "test_agent"

    def test_agent_without_role_fails(self):
        """Test that agent without role raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            NoRoleAgent()

        assert "must define 'role' class attribute" in str(exc_info.value)

    def test_agent_without_capabilities_fails(self):
        """Test that agent without capabilities raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            NoCapabilitiesAgent()

        assert "must define 'capabilities' class attribute" in str(exc_info.value)

    def test_agent_mesh_initially_none(self):
        """Test that agent._mesh is initially None."""
        agent = ValidAgent()
        assert agent._mesh is None


class TestAgentTaskHandling:
    """Test agent task handling capabilities."""

    def test_can_handle_by_role(self):
        """Test agent can handle task by role."""
        agent = ValidAgent()

        task = {"role": "test_agent", "task": "Do something"}
        assert agent.can_handle(task) is True

    def test_can_handle_by_capability(self):
        """Test agent can handle task by capability."""
        agent = ValidAgent()

        task1 = {"capability": "testing", "task": "Run tests"}
        assert agent.can_handle(task1) is True

        task2 = {"capability": "validation", "task": "Validate data"}
        assert agent.can_handle(task2) is True

    def test_cannot_handle_wrong_role(self):
        """Test agent rejects task with wrong role."""
        agent = ValidAgent()

        task = {"role": "different_agent", "task": "Do something"}
        assert agent.can_handle(task) is False

    def test_cannot_handle_wrong_capability(self):
        """Test agent rejects task with wrong capability."""
        agent = ValidAgent()

        task = {"capability": "unknown_capability", "task": "Do something"}
        assert agent.can_handle(task) is False

    def test_can_handle_no_role_or_capability(self):
        """Test agent behavior when task has no role or capability."""
        agent = ValidAgent()

        task = {"task": "Do something"}
        assert agent.can_handle(task) is False


class TestAgentExecution:
    """Test agent task execution."""

    @pytest.mark.asyncio
    async def test_execute_task_implementation(self):
        """Test that execute_task can be called and returns result."""
        agent = ValidAgent()

        task = {"task": "Test task"}
        result = await agent.execute_task(task)

        assert result["status"] == "success"
        assert result["output"] == "test result"


class TestAgentLifecycle:
    """Test agent setup and teardown lifecycle."""

    @pytest.mark.asyncio
    async def test_setup_hook(self):
        """Test agent setup hook."""
        agent = ValidAgent()
        await agent.setup()  # Should not raise

    @pytest.mark.asyncio
    async def test_teardown_hook(self):
        """Test agent teardown hook."""
        agent = ValidAgent()
        await agent.teardown()  # Should not raise


class TestAgentRepresentation:
    """Test agent string representations."""

    def test_repr(self):
        """Test agent __repr__."""
        agent = ValidAgent(agent_id="test-123")
        repr_str = repr(agent)

        assert "ValidAgent" in repr_str
        assert "test-123" in repr_str
        assert "test_agent" in repr_str
        assert "testing" in repr_str

    def test_str(self):
        """Test agent __str__."""
        agent = ValidAgent(agent_id="test-123")
        str_repr = str(agent)

        assert "test_agent" in str_repr
        assert "test-123" in str_repr
