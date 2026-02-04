"""
Test 17: Session Context Propagation (Feature F6)

Tests the context propagation feature:
- Context parameter in notify(), request(), respond(), broadcast()
- Auto-propagation of context in respond()
- Context accessible via IncomingMessage.context

Run with: pytest tests/test_17_session_context.py -v -s
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


# =============================================================================
# TEST: CONTEXT IN OUTGOING MESSAGES
# =============================================================================

class TestContextInNotify:
    """Test context parameter in notify()."""

    @pytest.mark.asyncio
    async def test_notify_with_context(self):
        """Test notify() accepts and sends context."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="sender-1",
            agent_role="sender",
            mock_peers=[{"role": "receiver", "capabilities": ["receiving"]}]
        )

        context = {"mission_id": "mission-123", "priority": "high"}
        result = await client.notify("receiver", {"event": "test"}, context=context)

        assert result is True
        notifications = client.get_sent_notifications()
        assert len(notifications) == 1
        assert notifications[0]["context"] == context
        assert notifications[0]["message"] == {"event": "test"}

    @pytest.mark.asyncio
    async def test_notify_without_context(self):
        """Test notify() works without context (None by default)."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="sender-1",
            agent_role="sender",
            mock_peers=[{"role": "receiver", "capabilities": ["receiving"]}]
        )

        result = await client.notify("receiver", {"event": "test"})

        assert result is True
        notifications = client.get_sent_notifications()
        assert len(notifications) == 1
        assert notifications[0]["context"] is None


class TestContextInRequest:
    """Test context parameter in request()."""

    @pytest.mark.asyncio
    async def test_request_with_context(self):
        """Test request() accepts and sends context."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="sender-1",
            agent_role="sender",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}]
        )
        client.set_mock_response("analyst", {"result": "analyzed"})

        context = {"mission_id": "mission-456", "trace_id": "trace-abc"}
        response = await client.request("analyst", {"query": "test"}, context=context)

        assert response == {"result": "analyzed"}
        requests = client.get_sent_requests()
        assert len(requests) == 1
        assert requests[0]["context"] == context

    @pytest.mark.asyncio
    async def test_request_without_context(self):
        """Test request() works without context."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="sender-1",
            agent_role="sender",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}]
        )

        response = await client.request("analyst", {"query": "test"})

        assert response is not None
        requests = client.get_sent_requests()
        assert len(requests) == 1
        assert requests[0]["context"] is None


class TestContextInBroadcast:
    """Test context parameter in broadcast()."""

    @pytest.mark.asyncio
    async def test_broadcast_with_context(self):
        """Test broadcast() accepts and sends context to all peers."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="broadcaster-1",
            agent_role="broadcaster",
            mock_peers=[
                {"role": "peer1", "capabilities": ["cap1"]},
                {"role": "peer2", "capabilities": ["cap2"]}
            ]
        )

        context = {"broadcast_id": "bc-789", "source": "alert_system"}
        count = await client.broadcast({"alert": "important"}, context=context)

        assert count == 2
        broadcasts = client.get_sent_broadcasts()
        assert len(broadcasts) == 1
        assert broadcasts[0]["context"] == context


# =============================================================================
# TEST: CONTEXT IN INCOMING MESSAGES
# =============================================================================

class TestContextInIncomingMessage:
    """Test context accessible in IncomingMessage."""

    def test_incoming_message_has_context_field(self):
        """Test IncomingMessage dataclass has context field."""
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        msg = IncomingMessage(
            sender="sender-1",
            sender_node="localhost:7946",
            type=MessageType.NOTIFY,
            data={"event": "test"},
            context={"mission_id": "m-123"}
        )

        assert msg.context == {"mission_id": "m-123"}

    def test_incoming_message_context_default_none(self):
        """Test IncomingMessage context defaults to None."""
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        msg = IncomingMessage(
            sender="sender-1",
            sender_node="localhost:7946",
            type=MessageType.NOTIFY,
            data={"event": "test"}
        )

        assert msg.context is None


class TestContextInOutgoingMessage:
    """Test context in OutgoingMessage dataclass."""

    def test_outgoing_message_has_context_field(self):
        """Test OutgoingMessage dataclass has context field."""
        from jarviscore.p2p.messages import OutgoingMessage, MessageType

        msg = OutgoingMessage(
            target="receiver",
            type=MessageType.REQUEST,
            data={"query": "test"},
            context={"priority": "high"}
        )

        assert msg.context == {"priority": "high"}


# =============================================================================
# TEST: CONTEXT AUTO-PROPAGATION IN RESPOND
# =============================================================================

class TestContextAutoPropagation:
    """Test context auto-propagation in respond()."""

    @pytest.mark.asyncio
    async def test_respond_auto_propagates_context(self):
        """Test respond() auto-propagates request context if not overridden."""
        from jarviscore.p2p.peer_client import PeerClient
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        # Create a mock coordinator
        mock_coordinator = MagicMock()
        mock_coordinator._send_p2p_message = AsyncMock(return_value=True)
        mock_coordinator._remote_agent_registry = {}

        # Create mock agent registry with a sender agent
        class MockAgent:
            def __init__(self):
                self.agent_id = "sender-1"
                self.role = "sender"
                self.capabilities = ["sending"]
                self.peers = MagicMock()
                self.peers._deliver_message = AsyncMock()

        mock_sender = MockAgent()
        agent_registry = {"sender": [mock_sender]}

        # Create the responder PeerClient
        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="responder-1",
            agent_role="responder",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Create incoming request with context
        incoming = IncomingMessage(
            sender="sender-1",
            sender_node="localhost:7946",
            type=MessageType.REQUEST,
            data={"query": "test"},
            correlation_id="corr-123",
            context={"mission_id": "m-999", "trace_id": "t-abc"}
        )

        # Respond without explicitly providing context
        result = await client.respond(incoming, {"answer": "42"})

        assert result is True

        # Verify the response was delivered with propagated context
        mock_sender.peers._deliver_message.assert_called_once()
        delivered_msg = mock_sender.peers._deliver_message.call_args[0][0]
        assert delivered_msg.context == {"mission_id": "m-999", "trace_id": "t-abc"}

    @pytest.mark.asyncio
    async def test_respond_override_context(self):
        """Test respond() can override context."""
        from jarviscore.p2p.peer_client import PeerClient
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        mock_coordinator = MagicMock()
        mock_coordinator._send_p2p_message = AsyncMock(return_value=True)
        mock_coordinator._remote_agent_registry = {}

        class MockAgent:
            def __init__(self):
                self.agent_id = "sender-1"
                self.role = "sender"
                self.capabilities = ["sending"]
                self.peers = MagicMock()
                self.peers._deliver_message = AsyncMock()

        mock_sender = MockAgent()
        agent_registry = {"sender": [mock_sender]}

        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="responder-1",
            agent_role="responder",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Incoming with original context
        incoming = IncomingMessage(
            sender="sender-1",
            sender_node="localhost:7946",
            type=MessageType.REQUEST,
            data={"query": "test"},
            correlation_id="corr-456",
            context={"original": "context"}
        )

        # Respond with overridden context
        result = await client.respond(
            incoming,
            {"answer": "42"},
            context={"overridden": "context", "status": "complete"}
        )

        assert result is True
        delivered_msg = mock_sender.peers._deliver_message.call_args[0][0]
        assert delivered_msg.context == {"overridden": "context", "status": "complete"}


# =============================================================================
# TEST: CONTEXT THROUGH LOCAL DELIVERY
# =============================================================================

class TestContextLocalDelivery:
    """Test context flows through local message delivery."""

    @pytest.mark.asyncio
    async def test_context_in_local_notify(self):
        """Test context preserved in local notify delivery."""
        from jarviscore.p2p.peer_client import PeerClient
        from jarviscore.p2p.messages import MessageType

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}

        # Create receiver agent with PeerClient
        class MockReceiverAgent:
            def __init__(self):
                self.agent_id = "receiver-1"
                self.role = "receiver"
                self.capabilities = ["receiving"]
                self.peers = None

        receiver = MockReceiverAgent()
        receiver_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="receiver-1",
            agent_role="receiver",
            agent_registry={},
            node_id="localhost:7946"
        )
        receiver.peers = receiver_client

        # Create sender with receiver in registry
        agent_registry = {"receiver": [receiver]}
        sender_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="sender-1",
            agent_role="sender",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Send notify with context
        context = {"session_id": "sess-123", "user_id": "user-456"}
        result = await sender_client.notify("receiver", {"event": "test"}, context=context)

        assert result is True

        # Receive and check context
        msg = await receiver_client.receive(timeout=1)
        assert msg is not None
        assert msg.type == MessageType.NOTIFY
        assert msg.context == context


# =============================================================================
# TEST: CONTEXT IN MOCK PEER CLIENT
# =============================================================================

class TestMockPeerClientContext:
    """Test MockPeerClient supports context in all operations."""

    @pytest.mark.asyncio
    async def test_mock_inject_message_with_context(self):
        """Test MockPeerClient.inject_message() supports context."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import MessageType

        client = MockPeerClient()

        context = {"injected": "context", "test_id": "inject-1"}
        client.inject_message(
            sender="injector",
            message_type=MessageType.NOTIFY,
            data={"injected": True},
            context=context
        )

        msg = await client.receive(timeout=1)
        assert msg is not None
        assert msg.context == context
        assert msg.data == {"injected": True}

    @pytest.mark.asyncio
    async def test_mock_tracks_context_in_sent_messages(self):
        """Test MockPeerClient tracks context in all sent messages."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "target", "capabilities": []}]
        )

        # Send notification with context
        await client.notify("target", {"n": 1}, context={"ctx": "notify"})
        assert client.get_sent_notifications()[0]["context"] == {"ctx": "notify"}

        # Send request with context
        await client.request("target", {"r": 2}, context={"ctx": "request"})
        assert client.get_sent_requests()[0]["context"] == {"ctx": "request"}

        # Send broadcast with context
        await client.broadcast({"b": 3}, context={"ctx": "broadcast"})
        assert client.get_sent_broadcasts()[0]["context"] == {"ctx": "broadcast"}


# =============================================================================
# TEST: CONTEXT IN CUSTOM AGENT HANDLERS
# =============================================================================

class TestContextInCustomAgentHandlers:
    """Test context accessible in CustomAgent message handlers."""

    @pytest.mark.asyncio
    async def test_context_in_on_peer_request(self):
        """Test context is accessible in on_peer_request handler."""
        from jarviscore.profiles import CustomAgent
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        received_context = None

        class TestAgent(CustomAgent):
            role = "context_handler"
            capabilities = ["handling"]

            async def on_peer_request(self, msg):
                nonlocal received_context
                received_context = msg.context
                return {"received_context": msg.context}

        agent = TestAgent()
        agent._logger = MagicMock()
        agent.peers = MagicMock()
        agent.peers.respond = AsyncMock()

        msg = IncomingMessage(
            sender="sender",
            sender_node="localhost:7946",
            type=MessageType.REQUEST,
            data={"query": "test"},
            correlation_id="corr-123",
            context={"mission_id": "m-handler", "stage": "processing"}
        )

        await agent._dispatch_message(msg)

        assert received_context == {"mission_id": "m-handler", "stage": "processing"}

    @pytest.mark.asyncio
    async def test_context_in_on_peer_notify(self):
        """Test context is accessible in on_peer_notify handler."""
        from jarviscore.profiles import CustomAgent
        from jarviscore.p2p.messages import IncomingMessage, MessageType

        received_context = None

        class TestAgent(CustomAgent):
            role = "context_handler"
            capabilities = ["handling"]

            async def on_peer_notify(self, msg):
                nonlocal received_context
                received_context = msg.context

            async def on_peer_request(self, msg):
                return {}

        agent = TestAgent()
        agent._logger = MagicMock()

        msg = IncomingMessage(
            sender="sender",
            sender_node="localhost:7946",
            type=MessageType.NOTIFY,
            data={"event": "test"},
            context={"notification_source": "event_system"}
        )

        await agent._dispatch_message(msg)

        assert received_context == {"notification_source": "event_system"}


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
