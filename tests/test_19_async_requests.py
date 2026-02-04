"""
Test 19: Async Request Pattern (Feature F2)

Tests the async request methods:
- ask_async() returns request_id immediately
- check_inbox() returns None when not ready
- check_inbox() returns response when available
- check_inbox() with timeout
- get_pending_async_requests()
- clear_inbox()

Run with: pytest tests/test_19_async_requests.py -v -s
"""
import asyncio
import sys
import pytest
import logging
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, '.')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# TEST: ASK_ASYNC BASICS
# =============================================================================

class TestAskAsync:
    """Test ask_async() method."""

    @pytest.mark.asyncio
    async def test_ask_async_returns_request_id(self):
        """Test ask_async() returns a request ID string."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}]
        )

        request_id = await client.ask_async("analyst", {"query": "test"})

        assert request_id is not None
        assert isinstance(request_id, str)
        assert len(request_id) > 0

    @pytest.mark.asyncio
    async def test_ask_async_request_id_format(self):
        """Test ask_async() returns properly formatted request ID."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}]
        )

        request_id = await client.ask_async("analyst", {"query": "test"})

        # MockPeerClient uses "mock-" prefix
        assert request_id.startswith("mock-")

    @pytest.mark.asyncio
    async def test_ask_async_tracks_request(self):
        """Test ask_async() tracks the request in sent_requests."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}]
        )

        request_id = await client.ask_async("analyst", {"query": "important"})

        requests = client.get_sent_requests()
        assert len(requests) == 1
        assert requests[0]["target"] == "analyst"
        assert requests[0]["message"] == {"query": "important"}
        assert requests[0].get("async") is True

    @pytest.mark.asyncio
    async def test_ask_async_with_context(self):
        """Test ask_async() accepts context parameter."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}]
        )

        context = {"mission_id": "m-123", "priority": "high"}
        request_id = await client.ask_async("analyst", {"query": "test"}, context=context)

        requests = client.get_sent_requests()
        assert requests[0]["context"] == context


# =============================================================================
# TEST: CHECK_INBOX
# =============================================================================

class TestCheckInbox:
    """Test check_inbox() method."""

    @pytest.mark.asyncio
    async def test_check_inbox_returns_response(self):
        """Test check_inbox() returns response when auto_respond is True."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}],
            auto_respond=True
        )

        request_id = await client.ask_async("analyst", {"query": "test"})
        response = await client.check_inbox(request_id)

        # MockPeerClient with auto_respond returns default response
        assert response is not None
        assert "mock" in response or "status" in response

    @pytest.mark.asyncio
    async def test_check_inbox_returns_none_when_no_auto_respond(self):
        """Test check_inbox() returns None when auto_respond is False."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}],
            auto_respond=False
        )

        request_id = await client.ask_async("analyst", {"query": "test"})
        response = await client.check_inbox(request_id, timeout=0)

        assert response is None

    @pytest.mark.asyncio
    async def test_check_inbox_with_timeout(self):
        """Test check_inbox() with timeout parameter."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[{"role": "analyst", "capabilities": ["analysis"]}],
            auto_respond=True
        )

        request_id = await client.ask_async("analyst", {"query": "test"})

        # With timeout, should return response immediately (mock)
        response = await client.check_inbox(request_id, timeout=5)

        assert response is not None


# =============================================================================
# TEST: REAL PEER CLIENT ASYNC REQUESTS
# =============================================================================

class TestRealPeerClientAsyncRequests:
    """Test async requests with real PeerClient."""

    @pytest.mark.asyncio
    async def test_ask_async_sends_request(self):
        """Test ask_async() sends request to target."""
        from jarviscore.p2p.peer_client import PeerClient
        from jarviscore.p2p.messages import MessageType

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}

        # Create target agent with PeerClient
        class MockTargetAgent:
            def __init__(self):
                self.agent_id = "analyst-1"
                self.role = "analyst"
                self.capabilities = ["analysis"]
                self.peers = None

        target = MockTargetAgent()
        target_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="analyst-1",
            agent_role="analyst",
            agent_registry={},
            node_id="localhost:7946"
        )
        target.peers = target_client

        # Create requester with target in registry
        agent_registry = {"analyst": [target]}
        requester_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="requester-1",
            agent_role="requester",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Send async request
        request_id = await requester_client.ask_async("analyst", {"query": "analyze this"})

        assert request_id is not None
        assert request_id.startswith("async-")

        # Verify message was delivered to target
        msg = await target_client.receive(timeout=1)
        assert msg is not None
        assert msg.type == MessageType.REQUEST
        assert msg.data == {"query": "analyze this"}

    @pytest.mark.asyncio
    async def test_ask_async_raises_on_invalid_target(self):
        """Test ask_async() raises ValueError for invalid target."""
        from jarviscore.p2p.peer_client import PeerClient

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}
        mock_coordinator.get_remote_agent = MagicMock(return_value=None)

        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="requester-1",
            agent_role="requester",
            agent_registry={},
            node_id="localhost:7946"
        )

        with pytest.raises(ValueError, match="No peer found"):
            await client.ask_async("nonexistent", {"query": "test"})


# =============================================================================
# TEST: GET_PENDING_ASYNC_REQUESTS
# =============================================================================

class TestGetPendingAsyncRequests:
    """Test get_pending_async_requests() method."""

    @pytest.mark.asyncio
    async def test_pending_requests_initially_empty(self):
        """Test pending requests list is empty initially."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()
        pending = client.get_pending_async_requests()

        assert pending == []

    @pytest.mark.asyncio
    async def test_real_client_tracks_pending_requests(self):
        """Test real PeerClient tracks pending async requests."""
        from jarviscore.p2p.peer_client import PeerClient

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}

        # Create target agent
        class MockTargetAgent:
            def __init__(self):
                self.agent_id = "target-1"
                self.role = "target"
                self.capabilities = []
                self.peers = None

        target = MockTargetAgent()
        target_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="target-1",
            agent_role="target",
            agent_registry={},
            node_id="localhost:7946"
        )
        target.peers = target_client

        agent_registry = {"target": [target]}
        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="requester-1",
            agent_role="requester",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Send async request
        request_id = await client.ask_async("target", {"query": "test"})

        pending = client.get_pending_async_requests()

        assert len(pending) == 1
        assert pending[0]["request_id"] == request_id
        assert pending[0]["target"] == "target"


# =============================================================================
# TEST: CLEAR_INBOX
# =============================================================================

class TestClearInbox:
    """Test clear_inbox() method."""

    @pytest.mark.asyncio
    async def test_clear_inbox_all(self):
        """Test clear_inbox() with no argument clears all."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "target", "capabilities": []}]
        )

        # Create some async requests
        await client.ask_async("target", {"q": 1})
        await client.ask_async("target", {"q": 2})

        # Clear all
        client.clear_inbox()

        # Verify cleared (no error)
        # MockPeerClient.clear_inbox is a no-op but should not raise

    @pytest.mark.asyncio
    async def test_clear_inbox_specific(self):
        """Test clear_inbox() with specific request_id."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "target", "capabilities": []}]
        )

        req_id = await client.ask_async("target", {"q": 1})

        # Clear specific request
        client.clear_inbox(req_id)

        # Should not raise

    @pytest.mark.asyncio
    async def test_real_client_clear_inbox(self):
        """Test real PeerClient clear_inbox removes entries."""
        from jarviscore.p2p.peer_client import PeerClient

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}

        # Create target
        class MockTargetAgent:
            def __init__(self):
                self.agent_id = "target-1"
                self.role = "target"
                self.capabilities = []
                self.peers = None

        target = MockTargetAgent()
        target_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="target-1",
            agent_role="target",
            agent_registry={},
            node_id="localhost:7946"
        )
        target.peers = target_client

        agent_registry = {"target": [target]}
        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="requester-1",
            agent_role="requester",
            agent_registry=agent_registry,
            node_id="localhost:7946"
        )

        # Send async requests
        req1 = await client.ask_async("target", {"q": 1})
        req2 = await client.ask_async("target", {"q": 2})

        assert len(client.get_pending_async_requests()) == 2

        # Clear specific
        client.clear_inbox(req1)
        assert len(client.get_pending_async_requests()) == 1

        # Clear all
        client.clear_inbox()
        assert len(client.get_pending_async_requests()) == 0


# =============================================================================
# TEST: ASYNC REQUEST WITH RESPONSE
# =============================================================================

class TestAsyncRequestResponse:
    """Test complete async request-response flow."""

    @pytest.mark.asyncio
    async def test_async_request_receives_response(self):
        """Test async request receives response via check_inbox."""
        from jarviscore.p2p.peer_client import PeerClient
        from jarviscore.p2p.messages import MessageType

        mock_coordinator = MagicMock()
        mock_coordinator._remote_agent_registry = {}

        # Create responder
        class MockResponder:
            def __init__(self):
                self.agent_id = "responder-1"
                self.role = "responder"
                self.capabilities = []
                self.peers = None

        responder = MockResponder()
        responder_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="responder-1",
            agent_role="responder",
            agent_registry={},
            node_id="localhost:7946"
        )
        responder.peers = responder_client

        # Create requester
        class MockRequester:
            def __init__(self):
                self.agent_id = "requester-1"
                self.role = "requester"
                self.capabilities = []
                self.peers = None

        requester = MockRequester()
        requester_client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="requester-1",
            agent_role="requester",
            agent_registry={"responder": [responder], "requester": [requester]},
            node_id="localhost:7946"
        )
        requester.peers = requester_client

        # Also add requester to responder's registry for response routing
        responder_client._agent_registry = {"requester": [requester], "responder": [responder]}

        # Send async request
        request_id = await requester_client.ask_async("responder", {"query": "what is 2+2?"})

        # Responder receives and responds
        msg = await responder_client.receive(timeout=1)
        assert msg is not None
        assert msg.is_request

        await responder_client.respond(msg, {"answer": "4"})

        # Give time for async handler to process response
        await asyncio.sleep(0.2)

        # Requester checks inbox
        response = await requester_client.check_inbox(request_id, timeout=1)

        assert response is not None
        assert response == {"answer": "4"}


# =============================================================================
# TEST: MULTIPLE ASYNC REQUESTS
# =============================================================================

class TestMultipleAsyncRequests:
    """Test handling multiple concurrent async requests."""

    @pytest.mark.asyncio
    async def test_multiple_async_requests_tracked(self):
        """Test multiple async requests are tracked independently."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            agent_id="requester-1",
            agent_role="requester",
            mock_peers=[
                {"role": "analyst1", "capabilities": ["analysis"]},
                {"role": "analyst2", "capabilities": ["analysis"]},
                {"role": "analyst3", "capabilities": ["analysis"]}
            ]
        )

        # Send multiple async requests
        req1 = await client.ask_async("analyst1", {"query": "q1"})
        req2 = await client.ask_async("analyst2", {"query": "q2"})
        req3 = await client.ask_async("analyst3", {"query": "q3"})

        # All should have unique IDs
        assert req1 != req2 != req3

        requests = client.get_sent_requests()
        assert len(requests) == 3

        # Targets should be correct
        targets = {r["target"] for r in requests}
        assert targets == {"analyst1", "analyst2", "analyst3"}


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
