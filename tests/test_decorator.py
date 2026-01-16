"""
Tests for @jarvis_agent decorator.

Tests the decorator that converts any class into a JarvisCore agent,
enabling Custom Profile usage with existing agents (LangChain, CrewAI, raw Python).
"""
import pytest
from jarviscore import jarvis_agent, JarvisContext, Mesh
from jarviscore.adapter.decorator import detect_execute_method, EXECUTE_METHODS
from jarviscore.profiles.customagent import CustomAgent


class TestDetectExecuteMethod:
    """Tests for execute method detection."""

    def test_detects_run_method(self):
        """Test detection of 'run' method."""
        class Agent:
            def run(self, data):
                return data

        assert detect_execute_method(Agent) == "run"

    def test_detects_invoke_method(self):
        """Test detection of 'invoke' method (LangChain style)."""
        class Agent:
            def invoke(self, input):
                return input

        assert detect_execute_method(Agent) == "invoke"

    def test_detects_execute_method(self):
        """Test detection of 'execute' method."""
        class Agent:
            def execute(self, task):
                return task

        assert detect_execute_method(Agent) == "execute"

    def test_detects_call_method(self):
        """Test detection of 'call' method."""
        class Agent:
            def call(self, args):
                return args

        assert detect_execute_method(Agent) == "call"

    def test_detects_dunder_call(self):
        """Test detection of '__call__' method."""
        class Agent:
            def __call__(self, x):
                return x

        assert detect_execute_method(Agent) == "__call__"

    def test_detects_process_method(self):
        """Test detection of 'process' method."""
        class Agent:
            def process(self, data):
                return data

        assert detect_execute_method(Agent) == "process"

    def test_detects_handle_method(self):
        """Test detection of 'handle' method."""
        class Agent:
            def handle(self, request):
                return request

        assert detect_execute_method(Agent) == "handle"

    def test_prefers_run_over_others(self):
        """Test that 'run' is preferred when multiple methods exist."""
        class Agent:
            def run(self, data):
                return data

            def invoke(self, data):
                return data

        assert detect_execute_method(Agent) == "run"

    def test_returns_none_for_no_method(self):
        """Test returns None when no execute method found."""
        class Agent:
            def custom_method(self, data):
                return data

        assert detect_execute_method(Agent) is None

    def test_execute_methods_list(self):
        """Test EXECUTE_METHODS contains expected methods."""
        assert "run" in EXECUTE_METHODS
        assert "invoke" in EXECUTE_METHODS
        assert "execute" in EXECUTE_METHODS
        assert "__call__" in EXECUTE_METHODS


class TestJarvisAgentDecorator:
    """Tests for @jarvis_agent decorator."""

    def test_decorator_sets_role(self):
        """Test decorator sets role attribute."""
        @jarvis_agent(role="test_role", capabilities=["cap1"])
        class TestAgent:
            def run(self, data):
                return data

        assert TestAgent.role == "test_role"

    def test_decorator_sets_capabilities(self):
        """Test decorator sets capabilities attribute."""
        @jarvis_agent(role="test", capabilities=["cap1", "cap2", "cap3"])
        class TestAgent:
            def run(self, data):
                return data

        assert TestAgent.capabilities == ["cap1", "cap2", "cap3"]

    def test_decorator_creates_customagent_subclass(self):
        """Test decorator creates CustomAgent subclass."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return data

        assert issubclass(TestAgent, CustomAgent)

    def test_decorator_preserves_class_name(self):
        """Test decorator preserves original class name."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class MySpecialAgent:
            def run(self, data):
                return data

        assert MySpecialAgent.__name__ == "MySpecialAgent"

    def test_decorator_preserves_docstring(self):
        """Test decorator preserves class docstring."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class DocAgent:
            """This is a documented agent."""
            def run(self, data):
                return data

        assert "documented agent" in DocAgent.__doc__

    def test_decorator_stores_wrapped_class(self):
        """Test decorator stores reference to wrapped class."""
        class OriginalClass:
            def run(self, data):
                return data

        Wrapped = jarvis_agent(role="test", capabilities=["cap"])(OriginalClass)

        assert Wrapped._wrapped_class is OriginalClass

    def test_decorator_stores_execute_method_name(self):
        """Test decorator stores execute method name."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return data

        assert TestAgent._execute_method == "run"

    def test_decorator_with_custom_execute_method(self):
        """Test decorator with explicit execute_method."""
        @jarvis_agent(role="test", capabilities=["cap"], execute_method="custom_run")
        class TestAgent:
            def custom_run(self, data):
                return {"result": data}

        assert TestAgent._execute_method == "custom_run"

    def test_decorator_detects_context_parameter(self):
        """Test decorator detects ctx parameter in method."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, task, ctx: JarvisContext):
                return task

        assert TestAgent._expects_context is True

    def test_decorator_detects_no_context_parameter(self):
        """Test decorator detects absence of ctx parameter."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return data

        assert TestAgent._expects_context is False

    def test_decorator_detects_context_named_context(self):
        """Test decorator detects 'context' parameter name."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, task, context):
                return task

        assert TestAgent._expects_context is True

    def test_decorator_raises_for_missing_method(self):
        """Test decorator raises error if method not found."""
        with pytest.raises(ValueError) as exc_info:
            @jarvis_agent(role="test", capabilities=["cap"], execute_method="missing")
            class TestAgent:
                def run(self, data):
                    return data

        assert "has no method 'missing'" in str(exc_info.value)

    def test_decorator_raises_for_no_detectable_method(self):
        """Test decorator raises error if no method detected."""
        with pytest.raises(ValueError) as exc_info:
            @jarvis_agent(role="test", capabilities=["cap"])
            class TestAgent:
                def custom_only(self, data):
                    return data

        assert "Could not detect execute method" in str(exc_info.value)


class TestDecoratedAgentInstantiation:
    """Tests for instantiating decorated agents."""

    def test_instantiation_creates_agent(self):
        """Test instantiation creates agent instance."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return data

        agent = TestAgent()

        assert agent is not None
        assert agent.role == "test"

    def test_instantiation_generates_agent_id(self):
        """Test instantiation generates agent_id."""
        @jarvis_agent(role="calculator", capabilities=["math"])
        class Calculator:
            def run(self, data):
                return data

        agent = Calculator()

        assert agent.agent_id is not None
        assert agent.agent_id.startswith("calculator-")

    def test_instantiation_with_custom_agent_id(self):
        """Test instantiation with custom agent_id."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return data

        agent = TestAgent(agent_id="custom-id-123")

        assert agent.agent_id == "custom-id-123"

    def test_instantiation_creates_wrapped_instance(self):
        """Test instantiation creates instance of wrapped class."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def __init__(self):
                self.initialized = True

            def run(self, data):
                return data

        agent = TestAgent()

        assert hasattr(agent, "_instance")
        assert agent._instance.initialized is True

    def test_instantiation_with_kwargs(self):
        """Test instantiation passes kwargs to wrapped class."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class ConfigurableAgent:
            def __init__(self, config_value=None):
                self.config = config_value

            def run(self, data):
                return data

        agent = ConfigurableAgent(config_value="custom_config")

        assert agent._instance.config == "custom_config"


class TestDecoratedAgentSetup:
    """Tests for decorated agent setup."""

    @pytest.mark.asyncio
    async def test_setup_calls_wrapped_setup(self):
        """Test setup calls wrapped class setup if exists."""
        setup_called = []

        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def setup(self):
                setup_called.append("wrapped_setup")

            def run(self, data):
                return data

        agent = TestAgent()
        await agent.setup()

        assert "wrapped_setup" in setup_called

    @pytest.mark.asyncio
    async def test_setup_handles_async_wrapped_setup(self):
        """Test setup handles async wrapped setup."""
        setup_called = []

        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            async def setup(self):
                setup_called.append("async_setup")

            def run(self, data):
                return data

        agent = TestAgent()
        await agent.setup()

        assert "async_setup" in setup_called

    @pytest.mark.asyncio
    async def test_setup_works_without_wrapped_setup(self):
        """Test setup works when wrapped class has no setup."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return data

        agent = TestAgent()
        await agent.setup()  # Should not raise


class TestDecoratedAgentExecution:
    """Tests for decorated agent task execution."""

    @pytest.mark.asyncio
    async def test_execute_task_calls_wrapped_method(self):
        """Test execute_task calls wrapped class method."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return {"doubled": data * 2}

        agent = TestAgent()
        result = await agent.execute_task({"params": 5})

        assert result["status"] == "success"
        assert result["output"]["doubled"] == 10

    @pytest.mark.asyncio
    async def test_execute_task_handles_async_method(self):
        """Test execute_task handles async wrapped method."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            async def run(self, data):
                return {"async_result": data}

        agent = TestAgent()
        result = await agent.execute_task({"params": "test"})

        assert result["status"] == "success"
        assert result["output"]["async_result"] == "test"

    @pytest.mark.asyncio
    async def test_execute_task_normalizes_dict_result(self):
        """Test execute_task normalizes dict result."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return {"key": "value"}  # No status field

        agent = TestAgent()
        result = await agent.execute_task({"params": {}})

        assert result["status"] == "success"
        assert result["output"] == {"key": "value"}
        assert "agent" in result

    @pytest.mark.asyncio
    async def test_execute_task_normalizes_non_dict_result(self):
        """Test execute_task normalizes non-dict result."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return [1, 2, 3, 4, 5]

        agent = TestAgent()
        result = await agent.execute_task({"params": {}})

        assert result["status"] == "success"
        assert result["output"] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_execute_task_preserves_existing_status(self):
        """Test execute_task preserves status if already present."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return {"status": "custom_status", "data": "value"}

        agent = TestAgent()
        result = await agent.execute_task({"params": {}})

        assert result["status"] == "custom_status"

    @pytest.mark.asyncio
    async def test_execute_task_handles_exception(self):
        """Test execute_task handles exceptions gracefully."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                raise ValueError("Test error")

        agent = TestAgent()
        result = await agent.execute_task({"params": {}})

        assert result["status"] == "failure"
        assert "Test error" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_task_with_task_string(self):
        """Test execute_task passes task string correctly."""
        received_task = []

        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, task):
                received_task.append(task)
                return {"received": task}

        agent = TestAgent()
        await agent.execute_task({"task": "Do something"})

        assert "Do something" in str(received_task)

    @pytest.mark.asyncio
    async def test_execute_task_with_params_dict(self):
        """Test execute_task passes params dict correctly."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, params):
                return {"a": params.get("a"), "b": params.get("b")}

        agent = TestAgent()
        result = await agent.execute_task({
            "task": "Calculate",
            "params": {"a": 5, "b": 3}
        })

        assert result["output"]["a"] == 5
        assert result["output"]["b"] == 3


class TestDecoratedAgentTeardown:
    """Tests for decorated agent teardown."""

    @pytest.mark.asyncio
    async def test_teardown_calls_wrapped_teardown(self):
        """Test teardown calls wrapped class teardown if exists."""
        teardown_called = []

        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def teardown(self):
                teardown_called.append("wrapped_teardown")

            def run(self, data):
                return data

        agent = TestAgent()
        await agent.teardown()

        assert "wrapped_teardown" in teardown_called

    @pytest.mark.asyncio
    async def test_teardown_handles_async_wrapped_teardown(self):
        """Test teardown handles async wrapped teardown."""
        teardown_called = []

        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            async def teardown(self):
                teardown_called.append("async_teardown")

            def run(self, data):
                return data

        agent = TestAgent()
        await agent.teardown()

        assert "async_teardown" in teardown_called


class TestDecoratedAgentWithContext:
    """Tests for decorated agents using JarvisContext."""

    @pytest.mark.asyncio
    async def test_context_not_passed_when_not_expected(self):
        """Test context is not passed when method doesn't expect it."""
        received_args = []

        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                received_args.append(data)
                return {"received": data}

        agent = TestAgent()
        await agent.execute_task({"params": {"key": "value"}})

        # Should receive params, not context
        assert len(received_args) == 1
        assert not isinstance(received_args[0], JarvisContext)

    @pytest.mark.asyncio
    async def test_context_passed_when_expected(self):
        """Test context is passed when method expects it."""
        received_ctx = []

        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, task, ctx: JarvisContext):
                received_ctx.append(ctx)
                return {"has_ctx": ctx is not None}

        agent = TestAgent()
        agent._mesh = None  # Simulate no mesh

        result = await agent.execute_task({
            "task": "test",
            "context": {"workflow_id": "w1", "step_id": "s1"}
        })

        assert len(received_ctx) == 1
        assert isinstance(received_ctx[0], JarvisContext)


class TestDecoratedAgentInheritance:
    """Tests for decorated agent inheritance."""

    def test_inherits_can_handle(self):
        """Test decorated agent inherits can_handle method."""
        @jarvis_agent(role="processor", capabilities=["processing", "transform"])
        class TestAgent:
            def run(self, data):
                return data

        agent = TestAgent()

        assert agent.can_handle({"role": "processor"}) is True
        assert agent.can_handle({"capability": "processing"}) is True
        assert agent.can_handle({"capability": "transform"}) is True
        assert agent.can_handle({"role": "other"}) is False

    def test_inherits_agent_methods(self):
        """Test decorated agent has all Agent methods."""
        @jarvis_agent(role="test", capabilities=["cap"])
        class TestAgent:
            def run(self, data):
                return data

        agent = TestAgent()

        assert hasattr(agent, "setup")
        assert hasattr(agent, "teardown")
        assert hasattr(agent, "execute_task")
        assert hasattr(agent, "can_handle")


class TestMultipleDecoratedAgents:
    """Tests for multiple decorated agents."""

    def test_multiple_agents_independent(self):
        """Test multiple decorated agents are independent."""
        @jarvis_agent(role="agent1", capabilities=["cap1"])
        class Agent1:
            def run(self, data):
                return {"from": "agent1"}

        @jarvis_agent(role="agent2", capabilities=["cap2"])
        class Agent2:
            def run(self, data):
                return {"from": "agent2"}

        assert Agent1.role == "agent1"
        assert Agent2.role == "agent2"
        assert Agent1.capabilities == ["cap1"]
        assert Agent2.capabilities == ["cap2"]

    @pytest.mark.asyncio
    async def test_multiple_instances_independent(self):
        """Test multiple instances of same agent are independent."""
        @jarvis_agent(role="counter", capabilities=["count"])
        class Counter:
            def __init__(self):
                self.count = 0

            def run(self, data):
                self.count += 1
                return {"count": self.count}

        agent1 = Counter()
        agent2 = Counter()

        await agent1.execute_task({"params": {}})
        await agent1.execute_task({"params": {}})

        result1 = await agent1.execute_task({"params": {}})
        result2 = await agent2.execute_task({"params": {}})

        assert result1["output"]["count"] == 3
        assert result2["output"]["count"] == 1
