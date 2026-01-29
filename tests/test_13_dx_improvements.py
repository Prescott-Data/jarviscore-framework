"""
Test 13: DX Improvements - FastAPI Integration, ListenerAgent, Cognitive Context

Tests the Developer Experience improvements:
- JarvisLifespan for FastAPI integration
- ListenerAgent profile for API-first agents
- Cognitive context generation for LLM prompts

Run with: pytest tests/test_13_dx_improvements.py -v -s
"""
import asyncio
import sys
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, '.')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: FASTAPI INTEGRATION (JarvisLifespan)
# ═══════════════════════════════════════════════════════════════════════════════

class TestJarvisLifespan:
    """Test FastAPI JarvisLifespan integration."""

    @pytest.mark.asyncio
    async def test_lifespan_creates_and_starts_mesh(self):
        """Test lifespan creates mesh and starts it during startup."""
        from jarviscore.profiles import CustomAgent
        from jarviscore.integrations.fastapi import JarvisLifespan

        class TestAgent(CustomAgent):
            role = "test_agent"
            capabilities = ["testing"]

            async def execute_task(self, task):
                return {"status": "success", "output": "test"}

        # Mock FastAPI app
        mock_app = MagicMock()
        mock_app.state = MagicMock()

        agent = TestAgent()
        lifespan = JarvisLifespan(agent, mode="p2p", bind_port=7890)

        # Enter lifespan context
        async with lifespan(mock_app):
            # Verify mesh was created and started
            assert lifespan.mesh is not None
            assert lifespan.mesh._started is True

            # Verify state was injected into app
            assert hasattr(mock_app.state, 'jarvis_mesh')
            assert hasattr(mock_app.state, 'jarvis_agents')
            assert 'test_agent' in mock_app.state.jarvis_agents

        # After context exit, mesh should be stopped
        assert lifespan.mesh._started is False

    @pytest.mark.asyncio
    async def test_lifespan_with_multiple_agents(self):
        """Test lifespan handles multiple agents correctly."""
        from jarviscore.profiles import CustomAgent
        from jarviscore.integrations.fastapi import JarvisLifespan

        class AgentA(CustomAgent):
            role = "agent_a"
            capabilities = ["capability_a"]
            async def execute_task(self, task):
                return {"status": "success"}

        class AgentB(CustomAgent):
            role = "agent_b"
            capabilities = ["capability_b"]
            async def execute_task(self, task):
                return {"status": "success"}

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        agents = [AgentA(), AgentB()]
        lifespan = JarvisLifespan(agents, mode="p2p", bind_port=7891)

        async with lifespan(mock_app):
            assert len(lifespan.mesh.agents) == 2
            assert 'agent_a' in mock_app.state.jarvis_agents
            assert 'agent_b' in mock_app.state.jarvis_agents

    @pytest.mark.asyncio
    async def test_lifespan_launches_background_tasks_for_run_loops(self):
        """Test lifespan launches background tasks for agents with run() methods."""
        from jarviscore.profiles import CustomAgent
        from jarviscore.integrations.fastapi import JarvisLifespan

        run_called = False

        class AgentWithRun(CustomAgent):
            role = "runner"
            capabilities = ["running"]

            async def run(self):
                nonlocal run_called
                run_called = True
                # Short loop that exits
                while not self.shutdown_requested:
                    await asyncio.sleep(0.1)

            async def execute_task(self, task):
                return {"status": "success"}

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        agent = AgentWithRun()
        lifespan = JarvisLifespan(agent, mode="p2p", bind_port=7892)

        async with lifespan(mock_app):
            # Wait a bit for background task to start
            await asyncio.sleep(0.3)
            assert run_called is True
            assert len(lifespan._background_tasks) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: LISTENER AGENT PROFILE
# ═══════════════════════════════════════════════════════════════════════════════

class TestListenerAgent:
    """Test ListenerAgent profile."""

    @pytest.mark.asyncio
    async def test_listener_dispatches_request_to_handler(self):
        """Test ListenerAgent dispatches REQUEST messages to on_peer_request."""
        from jarviscore.profiles import ListenerAgent
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        request_received = False
        request_data = None

        class TestListener(ListenerAgent):
            role = "listener"
            capabilities = ["listening"]

            async def on_peer_request(self, msg):
                nonlocal request_received, request_data
                request_received = True
                request_data = msg.data
                return {"handled": True, "echo": msg.data.get("value")}

        agent = TestListener()
        agent._logger = MagicMock()

        # Mock peers
        agent.peers = MagicMock()
        agent.peers.respond = AsyncMock()

        # Create test request message
        msg = IncomingMessage(
            sender="test_sender",
            sender_node="localhost:7946",
            type=MessageType.REQUEST,
            data={"action": "test", "value": 42},
            correlation_id="corr-123",
            timestamp=0
        )

        # Dispatch the message
        await agent._dispatch_message(msg)

        # Verify handler was called
        assert request_received is True
        assert request_data == {"action": "test", "value": 42}

        # Verify response was sent (auto_respond=True by default)
        agent.peers.respond.assert_called_once()
        call_args = agent.peers.respond.call_args
        assert call_args[0][1] == {"handled": True, "echo": 42}

    @pytest.mark.asyncio
    async def test_listener_dispatches_notify_to_handler(self):
        """Test ListenerAgent dispatches NOTIFY messages to on_peer_notify."""
        from jarviscore.profiles import ListenerAgent
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        notify_received = False
        notify_data = None

        class TestListener(ListenerAgent):
            role = "listener"
            capabilities = ["listening"]

            async def on_peer_request(self, msg):
                return {}

            async def on_peer_notify(self, msg):
                nonlocal notify_received, notify_data
                notify_received = True
                notify_data = msg.data

        agent = TestListener()
        agent._logger = MagicMock()

        # Create test notify message
        msg = IncomingMessage(
            sender="test_sender",
            sender_node="localhost:7946",
            type=MessageType.NOTIFY,
            data={"event": "task_complete", "result": "success"},
            correlation_id=None,
            timestamp=0
        )

        await agent._dispatch_message(msg)

        assert notify_received is True
        assert notify_data == {"event": "task_complete", "result": "success"}

    @pytest.mark.asyncio
    async def test_listener_auto_respond_disabled(self):
        """Test ListenerAgent respects auto_respond=False setting."""
        from jarviscore.profiles import ListenerAgent
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        class TestListener(ListenerAgent):
            role = "listener"
            capabilities = ["listening"]
            auto_respond = False  # Disable auto response

            async def on_peer_request(self, msg):
                return {"result": "this should not be sent automatically"}

        agent = TestListener()
        agent._logger = MagicMock()
        agent.peers = MagicMock()
        agent.peers.respond = AsyncMock()

        msg = IncomingMessage(
            sender="test",
            sender_node="local",
            type=MessageType.REQUEST,
            data={},
            correlation_id="123",
            timestamp=0
        )

        await agent._dispatch_message(msg)

        # Response should NOT be sent
        agent.peers.respond.assert_not_called()

    @pytest.mark.asyncio
    async def test_listener_error_handling(self):
        """Test ListenerAgent calls on_error when handler raises exception."""
        from jarviscore.profiles import ListenerAgent
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        error_received = None
        error_msg = None

        class TestListener(ListenerAgent):
            role = "listener"
            capabilities = ["listening"]

            async def on_peer_request(self, msg):
                raise ValueError("Test error")

            async def on_error(self, error, msg):
                nonlocal error_received, error_msg
                error_received = error
                error_msg = msg

        agent = TestListener()
        agent._logger = MagicMock()
        agent.peers = MagicMock()

        msg = IncomingMessage(
            sender="test",
            sender_node="local",
            type=MessageType.REQUEST,
            data={},
            correlation_id="123",
            timestamp=0
        )

        await agent._dispatch_message(msg)

        assert error_received is not None
        assert isinstance(error_received, ValueError)
        assert str(error_received) == "Test error"
        assert error_msg is not None

    @pytest.mark.asyncio
    async def test_listener_workflow_compatibility(self):
        """Test ListenerAgent.execute_task() delegates to on_peer_request."""
        from jarviscore.profiles import ListenerAgent

        class TestListener(ListenerAgent):
            role = "processor"
            capabilities = ["processing"]

            async def on_peer_request(self, msg):
                task = msg.data.get("task", "")
                return {"processed": task.upper()}

        agent = TestListener()
        agent._logger = MagicMock()

        result = await agent.execute_task({"task": "hello world"})

        assert result["status"] == "success"
        assert result["output"] == {"processed": "HELLO WORLD"}


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: COGNITIVE CONTEXT
# ═══════════════════════════════════════════════════════════════════════════════

class TestCognitiveContext:
    """Test PeerClient cognitive context generation."""

    def test_get_cognitive_context_markdown_format(self):
        """Test markdown format output for LLM prompts."""
        from jarviscore.p2p.peer_client import PeerClient

        # Create mock peer client
        client = PeerClient(
            coordinator=MagicMock(),
            agent_id="test-agent",
            agent_role="tester",
            agent_registry={},
            node_id="localhost:7946"
        )

        # Mock list_peers to return test data
        client.list_peers = MagicMock(return_value=[
            {
                "role": "analyst",
                "agent_id": "analyst-abc123",
                "capabilities": ["analysis", "charting", "reporting"],
                "description": "Analyzes data and generates insights"
            },
            {
                "role": "scout",
                "agent_id": "scout-def456",
                "capabilities": ["research", "reconnaissance"],
                "description": ""
            },
        ])

        context = client.get_cognitive_context(format="markdown")

        # Verify structure
        assert "## AVAILABLE MESH PEERS" in context
        assert "**analyst**" in context
        assert "**scout**" in context
        assert "analyst-abc123" in context
        assert "analysis, charting, reporting" in context
        assert "Analyzes data and generates insights" in context
        assert "ask_peer" in context

    def test_get_cognitive_context_json_format(self):
        """Test JSON format output."""
        import json
        from jarviscore.p2p.peer_client import PeerClient

        client = PeerClient(
            coordinator=MagicMock(),
            agent_id="test-agent",
            agent_role="tester",
            agent_registry={},
            node_id="localhost:7946"
        )

        client.list_peers = MagicMock(return_value=[
            {"role": "analyst", "agent_id": "analyst-1", "capabilities": ["analysis"]},
        ])

        context = client.get_cognitive_context(format="json")

        # Should be valid JSON
        data = json.loads(context)
        assert "available_peers" in data
        assert len(data["available_peers"]) == 1
        assert data["available_peers"][0]["role"] == "analyst"

    def test_get_cognitive_context_text_format(self):
        """Test plain text format output."""
        from jarviscore.p2p.peer_client import PeerClient

        client = PeerClient(
            coordinator=MagicMock(),
            agent_id="test-agent",
            agent_role="tester",
            agent_registry={},
            node_id="localhost:7946"
        )

        client.list_peers = MagicMock(return_value=[
            {"role": "analyst", "agent_id": "analyst-1", "capabilities": ["analysis"]},
            {"role": "scout", "agent_id": "scout-1", "capabilities": ["research"]},
        ])

        context = client.get_cognitive_context(format="text")

        assert "Available Peers:" in context
        assert "- analyst: analysis" in context
        assert "- scout: research" in context

    def test_get_cognitive_context_empty_mesh(self):
        """Test output when no peers are available."""
        from jarviscore.p2p.peer_client import PeerClient

        client = PeerClient(
            coordinator=MagicMock(),
            agent_id="test-agent",
            agent_role="tester",
            agent_registry={},
            node_id="localhost:7946"
        )

        client.list_peers = MagicMock(return_value=[])

        context = client.get_cognitive_context()

        assert "No other agents" in context

    def test_get_cognitive_context_custom_tool_name(self):
        """Test custom tool name in output."""
        from jarviscore.p2p.peer_client import PeerClient

        client = PeerClient(
            coordinator=MagicMock(),
            agent_id="test-agent",
            agent_role="tester",
            agent_registry={},
            node_id="localhost:7946"
        )

        client.list_peers = MagicMock(return_value=[
            {"role": "analyst", "agent_id": "a-1", "capabilities": ["analysis"]},
        ])

        context = client.get_cognitive_context(tool_name="delegate_to_peer")

        assert "delegate_to_peer" in context
        assert "ask_peer" not in context

    def test_build_system_prompt(self):
        """Test build_system_prompt combines base prompt with context."""
        from jarviscore.p2p.peer_client import PeerClient

        client = PeerClient(
            coordinator=MagicMock(),
            agent_id="test-agent",
            agent_role="tester",
            agent_registry={},
            node_id="localhost:7946"
        )

        client.list_peers = MagicMock(return_value=[
            {"role": "analyst", "agent_id": "a-1", "capabilities": ["analysis"]},
        ])

        base_prompt = "You are a helpful assistant that processes data."
        prompt = client.build_system_prompt(base_prompt)

        # Should contain both base prompt and context
        assert "You are a helpful assistant" in prompt
        assert "AVAILABLE MESH PEERS" in prompt
        assert "analyst" in prompt

    def test_build_system_prompt_with_options(self):
        """Test build_system_prompt passes options to get_cognitive_context."""
        from jarviscore.p2p.peer_client import PeerClient

        client = PeerClient(
            coordinator=MagicMock(),
            agent_id="test-agent",
            agent_role="tester",
            agent_registry={},
            node_id="localhost:7946"
        )

        client.list_peers = MagicMock(return_value=[
            {"role": "analyst", "agent_id": "a-1", "capabilities": ["analysis"]},
        ])

        prompt = client.build_system_prompt(
            "Base prompt.",
            include_capabilities=False,
            tool_name="custom_tool"
        )

        assert "custom_tool" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: INTEGRATION - ListenerAgent + JarvisLifespan
# ═══════════════════════════════════════════════════════════════════════════════

class TestListenerAgentWithFastAPI:
    """Integration test for ListenerAgent with FastAPI lifespan."""

    @pytest.mark.asyncio
    async def test_listener_agent_in_fastapi_lifespan(self):
        """Test ListenerAgent works correctly with JarvisLifespan."""
        from jarviscore.profiles import ListenerAgent
        from jarviscore.integrations.fastapi import JarvisLifespan

        messages_received = []

        class APIAgent(ListenerAgent):
            role = "api_processor"
            capabilities = ["api_processing"]
            listen_timeout = 0.1  # Fast timeout for test

            async def on_peer_request(self, msg):
                messages_received.append(msg.data)
                return {"processed": True}

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        agent = APIAgent()
        lifespan = JarvisLifespan(agent, mode="p2p", bind_port=7893)

        async with lifespan(mock_app):
            # Verify agent is accessible from app state
            assert 'api_processor' in mock_app.state.jarvis_agents
            registered_agent = mock_app.state.jarvis_agents['api_processor']

            # Verify agent has peers injected
            assert hasattr(registered_agent, 'peers')
            assert registered_agent.peers is not None

            # Verify cognitive context is available
            context = registered_agent.peers.get_cognitive_context()
            assert isinstance(context, str)

            # Give background task time to start
            await asyncio.sleep(0.2)


# ═══════════════════════════════════════════════════════════════════════════════
# RUN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
