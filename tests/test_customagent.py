"""
Tests for CustomAgent profile.
"""
import pytest
from jarviscore.profiles.customagent import CustomAgent


class ValidCustomAgent(CustomAgent):
    """Valid CustomAgent with execute_task implementation."""
    role = "test_custom"
    capabilities = ["custom_testing"]

    async def execute_task(self, task):
        return {
            "status": "success",
            "output": f"Custom result for: {task.get('task', '')}",
            "custom_field": "user_data"
        }


class NoExecuteCustomAgent(CustomAgent):
    """CustomAgent without execute_task (should raise NotImplementedError)."""
    role = "no_execute"
    capabilities = ["testing"]


class TestCustomAgentInitialization:
    """Test CustomAgent initialization."""

    def test_valid_customagent_creation(self):
        """Test creating a valid CustomAgent."""
        agent = ValidCustomAgent()

        assert agent.role == "test_custom"
        assert agent.capabilities == ["custom_testing"]

    def test_customagent_with_custom_attributes(self):
        """Test CustomAgent with user-defined attributes."""
        class APICustomAgent(CustomAgent):
            role = "api_agent"
            capabilities = ["api_calls"]
            api_endpoint = "https://api.example.com"
            api_key = "test-key-123"

            async def execute_task(self, task):
                return {"status": "success"}

        agent = APICustomAgent()

        assert agent.api_endpoint == "https://api.example.com"
        assert agent.api_key == "test-key-123"


class TestCustomAgentSetup:
    """Test CustomAgent setup."""

    @pytest.mark.asyncio
    async def test_customagent_setup(self):
        """Test CustomAgent setup hook."""
        agent = ValidCustomAgent()
        await agent.setup()

        # Should run without error

    @pytest.mark.asyncio
    async def test_customagent_setup_with_framework_initialization(self):
        """Test CustomAgent setup with framework initialization."""
        setup_called = []

        class FrameworkCustomAgent(CustomAgent):
            role = "framework_agent"
            capabilities = ["framework"]

            async def setup(self):
                await super().setup()
                # Simulate initializing a framework (e.g., LangChain, MCP)
                setup_called.append("framework_initialized")

            async def execute_task(self, task):
                return {"status": "success"}

        agent = FrameworkCustomAgent()
        await agent.setup()

        assert "framework_initialized" in setup_called


class TestCustomAgentExecution:
    """Test CustomAgent task execution."""

    @pytest.mark.asyncio
    async def test_execute_task_implementation(self):
        """Test CustomAgent execute_task with user implementation."""
        agent = ValidCustomAgent()

        task = {"task": "Process data"}
        result = await agent.execute_task(task)

        assert result["status"] == "success"
        assert "Process data" in result["output"]
        assert result["custom_field"] == "user_data"

    @pytest.mark.asyncio
    async def test_execute_task_not_implemented_raises_error(self):
        """Test that CustomAgent without execute_task raises NotImplementedError."""
        agent = NoExecuteCustomAgent()

        task = {"task": "Should fail"}

        with pytest.raises(NotImplementedError) as exc_info:
            await agent.execute_task(task)

        assert "must implement execute_task" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_execute_task_with_optional_cost_tracking(self):
        """Test CustomAgent returning optional cost tracking fields."""
        class CostTrackingAgent(CustomAgent):
            role = "cost_tracker"
            capabilities = ["tracking"]

            async def execute_task(self, task):
                return {
                    "status": "success",
                    "output": "result",
                    "tokens_used": 1500,
                    "cost_usd": 0.003
                }

        agent = CostTrackingAgent()
        result = await agent.execute_task({"task": "Track costs"})

        assert result["tokens_used"] == 1500
        assert result["cost_usd"] == 0.003


class TestCustomAgentFrameworkIntegration:
    """Test CustomAgent with various framework integrations."""

    @pytest.mark.asyncio
    async def test_langchain_integration_example(self):
        """Test CustomAgent simulating LangChain integration."""
        class LangChainAgent(CustomAgent):
            role = "langchain_agent"
            capabilities = ["langchain"]

            async def setup(self):
                await super().setup()
                # Simulate LangChain initialization
                self.lc_agent = "mock_langchain_agent"

            async def execute_task(self, task):
                # Simulate LangChain execution
                return {
                    "status": "success",
                    "output": f"LangChain result: {task['task']}"
                }

        agent = LangChainAgent()
        await agent.setup()

        result = await agent.execute_task({"task": "Query database"})

        assert result["status"] == "success"
        assert "LangChain result" in result["output"]

    @pytest.mark.asyncio
    async def test_mcp_integration_example(self):
        """Test CustomAgent simulating MCP integration."""
        class MCPAgent(CustomAgent):
            role = "mcp_agent"
            capabilities = ["mcp_tools"]
            mcp_server_url = "stdio://./server.py"

            async def setup(self):
                await super().setup()
                # Simulate MCP connection
                self.mcp_client = "mock_mcp_client"

            async def execute_task(self, task):
                # Simulate MCP tool call
                return {
                    "status": "success",
                    "data": {"tool": "executed", "params": task.get("params")}
                }

        agent = MCPAgent()
        await agent.setup()

        result = await agent.execute_task({
            "task": "Call MCP tool",
            "params": {"arg1": "value1"}
        })

        assert result["status"] == "success"
        assert result["data"]["tool"] == "executed"

    @pytest.mark.asyncio
    async def test_raw_python_integration_example(self):
        """Test CustomAgent with raw Python logic."""
        class DataProcessor(CustomAgent):
            role = "processor"
            capabilities = ["data_processing"]

            async def execute_task(self, task):
                # Pure Python logic
                data = task.get("params", {}).get("data", [])
                processed = [x * 2 for x in data]
                return {
                    "status": "success",
                    "output": processed
                }

        agent = DataProcessor()
        result = await agent.execute_task({
            "task": "Double values",
            "params": {"data": [1, 2, 3, 4, 5]}
        })

        assert result["status"] == "success"
        assert result["output"] == [2, 4, 6, 8, 10]


class TestCustomAgentInheritance:
    """Test CustomAgent inheritance from Profile and Agent."""

    def test_customagent_inherits_agent_methods(self):
        """Test that CustomAgent inherits Agent methods."""
        agent = ValidCustomAgent()

        # Should have Agent methods
        assert hasattr(agent, "can_handle")
        assert hasattr(agent, "execute_task")
        assert hasattr(agent, "setup")
        assert hasattr(agent, "teardown")

    def test_customagent_can_handle_tasks(self):
        """Test that CustomAgent can check task compatibility."""
        agent = ValidCustomAgent()

        task1 = {"role": "test_custom", "task": "Do something"}
        assert agent.can_handle(task1) is True

        task2 = {"capability": "custom_testing", "task": "Run tests"}
        assert agent.can_handle(task2) is True

        task3 = {"role": "different", "task": "Won't handle"}
        assert agent.can_handle(task3) is False
