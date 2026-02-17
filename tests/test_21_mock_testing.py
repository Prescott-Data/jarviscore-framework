"""
Test 21: MockMesh and MockPeerClient Testing Utilities (Feature F8)

Tests the testing utilities:
- MockPeerClient discovery
- MockPeerClient.set_mock_response()
- MockPeerClient assertion helpers
- MockPeerClient.inject_message()
- MockMesh.add() and start()
- MockMesh auto-injects peers

Run with: pytest tests/test_21_mock_testing.py -v -s
"""
import asyncio
import sys
import pytest
import logging
from unittest.mock import MagicMock

sys.path.insert(0, '.')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# TEST: MOCK PEER CLIENT DISCOVERY
# =============================================================================

class TestMockPeerClientDiscovery:
    """Test MockPeerClient discovery functionality."""

    def test_get_peer_returns_configured_peer(self):
        """Test get_peer() returns a configured mock peer."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import PeerInfo

        client = MockPeerClient(
            mock_peers=[
                {"role": "analyst", "capabilities": ["analysis", "reporting"]}
            ]
        )

        peer = client.get_peer("analyst")

        assert peer is not None
        assert isinstance(peer, PeerInfo)
        assert peer.role == "analyst"
        assert "analysis" in peer.capabilities

    def test_get_peer_returns_none_for_unknown_role(self):
        """Test get_peer() returns None for unconfigured role."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(mock_peers=[])

        peer = client.get_peer("nonexistent")

        assert peer is None

    def test_discover_filters_by_role(self):
        """Test discover() filters by role."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[
                {"role": "analyst", "capabilities": ["analysis"]},
                {"role": "scout", "capabilities": ["research"]},
                {"role": "analyst", "agent_id": "analyst-2", "capabilities": ["analysis"]}
            ]
        )

        analysts = client.discover(role="analyst")

        assert len(analysts) == 2
        for peer in analysts:
            assert peer.role == "analyst"

    def test_discover_filters_by_capability(self):
        """Test discover() filters by capability."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[
                {"role": "agent1", "capabilities": ["cap_a", "cap_shared"]},
                {"role": "agent2", "capabilities": ["cap_b"]},
                {"role": "agent3", "capabilities": ["cap_c", "cap_shared"]}
            ]
        )

        shared_cap_peers = client.discover(capability="cap_shared")

        assert len(shared_cap_peers) == 2
        for peer in shared_cap_peers:
            assert "cap_shared" in peer.capabilities

    def test_list_roles(self):
        """Test list_roles() returns unique roles."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[
                {"role": "analyst", "capabilities": []},
                {"role": "scout", "capabilities": []},
                {"role": "analyst", "agent_id": "analyst-2", "capabilities": []}
            ]
        )

        roles = client.list_roles()

        assert set(roles) == {"analyst", "scout"}

    def test_list_peers(self):
        """Test list_peers() returns all peers with details."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[
                {"role": "analyst", "capabilities": ["analysis"], "description": "Data analyst"},
                {"role": "scout", "capabilities": ["research"]}
            ]
        )

        peers = client.list_peers()

        assert len(peers) == 2
        assert all("role" in p for p in peers)
        assert all("agent_id" in p for p in peers)
        assert all("capabilities" in p for p in peers)


# =============================================================================
# TEST: MOCK PEER CLIENT SET_MOCK_RESPONSE
# =============================================================================

class TestMockPeerClientSetMockResponse:
    """Test MockPeerClient.set_mock_response() method."""

    @pytest.mark.asyncio
    async def test_set_mock_response_returns_configured_response(self):
        """Test set_mock_response() configures response for specific target."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "analyst", "capabilities": []}]
        )

        expected_response = {"result": "analysis complete", "score": 95}
        client.set_mock_response("analyst", expected_response)

        response = await client.request("analyst", {"query": "analyze"})

        assert response == expected_response

    @pytest.mark.asyncio
    async def test_set_mock_response_per_target(self):
        """Test different responses for different targets."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[
                {"role": "analyst", "capabilities": []},
                {"role": "scout", "capabilities": []}
            ]
        )

        client.set_mock_response("analyst", {"type": "analysis", "data": [1, 2, 3]})
        client.set_mock_response("scout", {"type": "reconnaissance", "findings": "clear"})

        analyst_response = await client.request("analyst", {})
        scout_response = await client.request("scout", {})

        assert analyst_response["type"] == "analysis"
        assert scout_response["type"] == "reconnaissance"

    @pytest.mark.asyncio
    async def test_set_default_response(self):
        """Test set_default_response() for unconfigured targets."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "agent", "capabilities": []}],
            auto_respond=True
        )

        default = {"default": True, "message": "fallback response"}
        client.set_default_response(default)

        response = await client.request("agent", {})

        assert response == default


# =============================================================================
# TEST: MOCK PEER CLIENT ASSERTION HELPERS
# =============================================================================

class TestMockPeerClientAssertionHelpers:
    """Test MockPeerClient assertion helper methods."""

    @pytest.mark.asyncio
    async def test_assert_notified_passes(self):
        """Test assert_notified() passes when notification was sent."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "receiver", "capabilities": []}]
        )

        await client.notify("receiver", {"event": "test_event"})

        # Should not raise
        client.assert_notified("receiver")

    @pytest.mark.asyncio
    async def test_assert_notified_fails_when_not_sent(self):
        """Test assert_notified() fails when notification wasn't sent."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()

        with pytest.raises(AssertionError, match="not found"):
            client.assert_notified("never_notified")

    @pytest.mark.asyncio
    async def test_assert_notified_with_message_contains(self):
        """Test assert_notified() with message_contains filter."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "receiver", "capabilities": []}]
        )

        await client.notify("receiver", {"event": "specific_event", "data": 123})

        # Should pass - message contains this key-value
        client.assert_notified("receiver", message_contains={"event": "specific_event"})

    @pytest.mark.asyncio
    async def test_assert_requested_passes(self):
        """Test assert_requested() passes when request was sent."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[{"role": "analyst", "capabilities": []}]
        )

        await client.request("analyst", {"query": "test"})

        client.assert_requested("analyst")

    @pytest.mark.asyncio
    async def test_assert_requested_fails_when_not_sent(self):
        """Test assert_requested() fails when request wasn't sent."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()

        with pytest.raises(AssertionError, match="not found"):
            client.assert_requested("never_requested")

    @pytest.mark.asyncio
    async def test_assert_broadcasted_passes(self):
        """Test assert_broadcasted() passes when broadcast was sent."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient(
            mock_peers=[
                {"role": "peer1", "capabilities": []},
                {"role": "peer2", "capabilities": []}
            ]
        )

        await client.broadcast({"alert": "test"})

        client.assert_broadcasted()

    @pytest.mark.asyncio
    async def test_assert_broadcasted_fails_when_not_sent(self):
        """Test assert_broadcasted() fails when no broadcast was sent."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()

        with pytest.raises(AssertionError, match="No broadcasts"):
            client.assert_broadcasted()


# =============================================================================
# TEST: MOCK PEER CLIENT INJECT_MESSAGE
# =============================================================================

class TestMockPeerClientInjectMessage:
    """Test MockPeerClient.inject_message() method."""

    @pytest.mark.asyncio
    async def test_inject_message_notify(self):
        """Test inject_message() with NOTIFY type."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import MessageType

        client = MockPeerClient()

        client.inject_message(
            sender="external_agent",
            message_type=MessageType.NOTIFY,
            data={"event": "external_event", "value": 42}
        )

        msg = await client.receive(timeout=1)

        assert msg is not None
        assert msg.sender == "external_agent"
        assert msg.type == MessageType.NOTIFY
        assert msg.data == {"event": "external_event", "value": 42}

    @pytest.mark.asyncio
    async def test_inject_message_request(self):
        """Test inject_message() with REQUEST type."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import MessageType

        client = MockPeerClient()

        client.inject_message(
            sender="requester",
            message_type=MessageType.REQUEST,
            data={"query": "please respond"},
            correlation_id="corr-123"
        )

        msg = await client.receive(timeout=1)

        assert msg is not None
        assert msg.type == MessageType.REQUEST
        assert msg.correlation_id == "corr-123"
        assert msg.is_request is True

    @pytest.mark.asyncio
    async def test_inject_message_with_context(self):
        """Test inject_message() with context."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import MessageType

        client = MockPeerClient()

        context = {"mission_id": "m-inject", "trace_id": "t-inject"}
        client.inject_message(
            sender="sender",
            message_type=MessageType.NOTIFY,
            data={"test": True},
            context=context
        )

        msg = await client.receive(timeout=1)

        assert msg.context == context

    @pytest.mark.asyncio
    async def test_inject_multiple_messages(self):
        """Test injecting multiple messages for receive loop testing."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import MessageType

        client = MockPeerClient()

        # Inject multiple messages
        for i in range(3):
            client.inject_message(
                sender=f"sender-{i}",
                message_type=MessageType.NOTIFY,
                data={"index": i}
            )

        # Receive all
        messages = []
        for _ in range(3):
            msg = await client.receive(timeout=1)
            if msg:
                messages.append(msg)

        assert len(messages) == 3
        indices = [m.data["index"] for m in messages]
        assert set(indices) == {0, 1, 2}


# =============================================================================
# TEST: MOCK PEER CLIENT RESET
# =============================================================================

class TestMockPeerClientReset:
    """Test MockPeerClient.reset() method."""

    @pytest.mark.asyncio
    async def test_reset_clears_tracking(self):
        """Test reset() clears all tracking state."""
        from jarviscore.testing import MockPeerClient
        from jarviscore.p2p.messages import MessageType

        client = MockPeerClient(
            mock_peers=[{"role": "target", "capabilities": []}]
        )

        # Generate some state
        await client.notify("target", {"n": 1})
        await client.request("target", {"r": 1})
        await client.broadcast({"b": 1})
        client.set_mock_response("target", {"custom": True})
        client.inject_message("sender", MessageType.NOTIFY, {"injected": True})

        # Reset
        client.reset()

        # Verify cleared
        assert len(client.get_sent_notifications()) == 0
        assert len(client.get_sent_requests()) == 0
        assert len(client.get_sent_broadcasts()) == 0
        assert client._mock_responses == {}
        assert not client.has_pending_messages()


# =============================================================================
# TEST: MOCK PEER CLIENT ADD_MOCK_PEER
# =============================================================================

class TestMockPeerClientAddMockPeer:
    """Test MockPeerClient.add_mock_peer() method."""

    def test_add_mock_peer_dynamically(self):
        """Test add_mock_peer() adds peers after construction."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()

        assert len(client.list_peers()) == 0

        client.add_mock_peer("analyst", capabilities=["analysis", "charting"])

        peers = client.list_peers()
        assert len(peers) == 1
        assert peers[0]["role"] == "analyst"
        assert "analysis" in peers[0]["capabilities"]

    def test_add_multiple_mock_peers(self):
        """Test adding multiple peers dynamically."""
        from jarviscore.testing import MockPeerClient

        client = MockPeerClient()

        client.add_mock_peer("analyst", capabilities=["analysis"])
        client.add_mock_peer("scout", capabilities=["research"])
        client.add_mock_peer("reporter", capabilities=["reporting"])

        roles = client.list_roles()
        assert set(roles) == {"analyst", "scout", "reporter"}


# =============================================================================
# TEST: MOCK MESH ADD AND START
# =============================================================================

class TestMockMeshAddAndStart:
    """Test MockMesh.add() and start() methods."""

    @pytest.mark.asyncio
    async def test_mock_mesh_add_agent_class(self):
        """Test MockMesh.add() with agent class."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "test_role"
            capabilities = ["test_cap"]

            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        agent = mesh.add(TestAgent)

        assert agent is not None
        assert agent.role == "test_role"
        assert len(mesh.agents) == 1

    @pytest.mark.asyncio
    async def test_mock_mesh_add_agent_instance(self):
        """Test MockMesh.add() with pre-instantiated agent."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "instance_role"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        instance = TestAgent()
        result = mesh.add(instance)

        assert result is instance
        assert len(mesh.agents) == 1

    @pytest.mark.asyncio
    async def test_mock_mesh_start_runs_setup(self):
        """Test MockMesh.start() runs agent setup."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        setup_called = False

        class TestAgent(CustomAgent):
            role = "setup_test"
            capabilities = ["testing"]

            async def setup(self):
                nonlocal setup_called
                setup_called = True
                await super().setup()

            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(TestAgent)
        await mesh.start()

        assert setup_called is True
        await mesh.stop()

    @pytest.mark.asyncio
    async def test_mock_mesh_get_agent(self):
        """Test MockMesh.get_agent() returns agent by role."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class AgentA(CustomAgent):
            role = "agent_a"
            capabilities = ["cap_a"]
            async def on_peer_request(self, msg):
                return {}

        class AgentB(CustomAgent):
            role = "agent_b"
            capabilities = ["cap_b"]
            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(AgentA)
        mesh.add(AgentB)
        await mesh.start()

        agent_a = mesh.get_agent("agent_a")
        agent_b = mesh.get_agent("agent_b")

        assert agent_a is not None
        assert agent_a.role == "agent_a"
        assert agent_b is not None
        assert agent_b.role == "agent_b"

        await mesh.stop()


# =============================================================================
# TEST: MOCK MESH AUTO-INJECTS PEERS
# =============================================================================

class TestMockMeshAutoInjectsPeers:
    """Test MockMesh automatically injects MockPeerClient with peer info."""

    @pytest.mark.asyncio
    async def test_mock_mesh_injects_mock_peer_client(self):
        """Test MockMesh injects MockPeerClient into agents."""
        from jarviscore.testing import MockMesh, MockPeerClient
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "inject_test"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(TestAgent)
        await mesh.start()

        agent = mesh.get_agent("inject_test")

        assert agent.peers is not None
        assert isinstance(agent.peers, MockPeerClient)

        await mesh.stop()

    @pytest.mark.asyncio
    async def test_mock_mesh_peers_see_each_other(self):
        """Test agents in MockMesh can discover each other."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class AgentA(CustomAgent):
            role = "discoverer"
            capabilities = ["discovery"]
            async def on_peer_request(self, msg):
                return {}

        class AgentB(CustomAgent):
            role = "discoverable"
            capabilities = ["being_found"]
            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(AgentA)
        mesh.add(AgentB)
        await mesh.start()

        discoverer = mesh.get_agent("discoverer")

        # Should see AgentB
        peers = discoverer.peers.discover(role="discoverable")

        assert len(peers) == 1
        assert peers[0].role == "discoverable"

        await mesh.stop()

    @pytest.mark.asyncio
    async def test_mock_mesh_agent_excludes_self(self):
        """Test agent's peer list excludes itself."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class AgentA(CustomAgent):
            role = "self_check"
            capabilities = ["checking"]
            async def on_peer_request(self, msg):
                return {}

        class AgentB(CustomAgent):
            role = "other"
            capabilities = ["other"]
            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(AgentA)
        mesh.add(AgentB)
        await mesh.start()

        agent_a = mesh.get_agent("self_check")
        peers = agent_a.peers.list_peers()

        # Should only see AgentB, not itself
        assert len(peers) == 1
        assert peers[0]["role"] == "other"

        await mesh.stop()


# =============================================================================
# TEST: MOCK PEER CLIENT SET_REQUEST_HANDLER
# =============================================================================

class TestMockPeerClientSetRequestHandler:
    """Test MockPeerClient.set_request_handler() for custom responses."""

    @pytest.mark.asyncio
    async def test_set_request_handler_custom_logic(self):
        """Test set_request_handler() with custom response logic."""
        from jarviscore.testing import MockPeerClient

        async def custom_handler(target, message, context):
            # Echo the query back with modification
            return {
                "echo": message.get("query", ""),
                "processed": True,
                "target_was": target
            }

        client = MockPeerClient(
            mock_peers=[{"role": "echo", "capabilities": []}]
        )
        client.set_request_handler(custom_handler)

        response = await client.request("echo", {"query": "hello world"})

        assert response["echo"] == "hello world"
        assert response["processed"] is True
        assert response["target_was"] == "echo"

    @pytest.mark.asyncio
    async def test_set_request_handler_overrides_mock_response(self):
        """Test set_request_handler() takes precedence over set_mock_response()."""
        from jarviscore.testing import MockPeerClient

        async def handler(target, message, context):
            return {"from": "handler"}

        client = MockPeerClient(
            mock_peers=[{"role": "target", "capabilities": []}]
        )
        client.set_mock_response("target", {"from": "mock_response"})
        client.set_request_handler(handler)

        response = await client.request("target", {})

        # Handler should take precedence
        assert response["from"] == "handler"


# =============================================================================
# TEST: INTEGRATION - MOCK TESTING WORKFLOW
# =============================================================================

class TestMockTestingWorkflow:
    """Integration test for complete mock testing workflow."""

    @pytest.mark.asyncio
    async def test_complete_testing_workflow(self):
        """Test complete workflow: setup, configure, test, verify."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class Coordinator(CustomAgent):
            role = "coordinator"
            capabilities = ["coordination"]

            async def on_peer_request(self, msg):
                # Coordinator asks analyst for help
                response = await self.peers.request("analyst", {
                    "task": "analyze",
                    "data": msg.data.get("data")
                })
                return {"coordinated": True, "analysis": response}

        class Analyst(CustomAgent):
            role = "analyst"
            capabilities = ["analysis"]

            async def on_peer_request(self, msg):
                return {"analyzed": msg.data.get("data", ""), "confidence": 0.95}

        # Setup
        mesh = MockMesh()
        mesh.add(Coordinator)
        mesh.add(Analyst)
        await mesh.start()

        # Get coordinator and configure mock response for analyst
        coordinator = mesh.get_agent("coordinator")
        coordinator.peers.set_mock_response("analyst", {
            "analyzed": "test_data",
            "confidence": 0.99
        })

        # Test
        response = await coordinator.peers.request("analyst", {"data": "test_data"})

        # Verify
        assert response["analyzed"] == "test_data"
        assert response["confidence"] == 0.99
        coordinator.peers.assert_requested("analyst")

        await mesh.stop()


# =============================================================================
# TEST: MOCK LLM CLIENT (Phase 6)
# =============================================================================

class TestMockLLMClient:
    """Test MockLLMClient for kernel and subagent tests."""

    @pytest.mark.asyncio
    async def test_returns_queued_responses_in_order(self):
        """Test responses are returned in FIFO order."""
        from jarviscore.testing import MockLLMClient

        llm = MockLLMClient(responses=[
            {"content": "response 1"},
            {"content": "response 2"},
        ])
        r1 = await llm.generate(prompt="q1")
        r2 = await llm.generate(prompt="q2")
        assert r1["content"] == "response 1"
        assert r2["content"] == "response 2"

    @pytest.mark.asyncio
    async def test_default_response_when_queue_exhausted(self):
        """Test fallback to default when no more queued responses."""
        from jarviscore.testing import MockLLMClient

        llm = MockLLMClient(responses=[{"content": "only one"}])
        await llm.generate(prompt="first")
        r = await llm.generate(prompt="second")
        assert "DONE" in r["content"]

    @pytest.mark.asyncio
    async def test_tracks_all_calls_with_params(self):
        """Test all calls are recorded with their parameters."""
        from jarviscore.testing import MockLLMClient

        llm = MockLLMClient()
        await llm.generate(prompt="hello", temperature=0.5)
        await llm.generate(messages=[{"role": "user", "content": "hi"}])
        assert len(llm.calls) == 2
        assert llm.calls[0]["prompt"] == "hello"
        assert llm.calls[0]["temperature"] == 0.5
        assert llm.calls[1]["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_model_kwarg_passed_through(self):
        """Test model kwarg is tracked and reflected in response."""
        from jarviscore.testing import MockLLMClient

        llm = MockLLMClient(responses=[{"content": "ok"}])
        r = await llm.generate(prompt="test", model="claude-opus-4-5")
        assert r["model"] == "claude-opus-4-5"
        assert llm.calls[0]["model"] == "claude-opus-4-5"

    @pytest.mark.asyncio
    async def test_response_has_required_shape(self):
        """Test every response includes content, provider, tokens, cost_usd, model."""
        from jarviscore.testing import MockLLMClient

        llm = MockLLMClient(responses=[{"content": "minimal"}])
        r = await llm.generate(prompt="test")
        assert "content" in r
        assert "provider" in r
        assert "tokens" in r
        assert "cost_usd" in r
        assert "model" in r

    @pytest.mark.asyncio
    async def test_reset_clears_calls_and_rewinds_queue(self):
        """Test reset() clears tracking and resets response index."""
        from jarviscore.testing import MockLLMClient

        llm = MockLLMClient(responses=[{"content": "a"}, {"content": "b"}])
        await llm.generate(prompt="1")
        llm.reset()
        assert len(llm.calls) == 0
        r = await llm.generate(prompt="2")
        assert r["content"] == "a"  # Back to start of queue


# =============================================================================
# TEST: MOCK SANDBOX EXECUTOR (Phase 6)
# =============================================================================

class TestMockSandboxExecutor:
    """Test MockSandboxExecutor for kernel and subagent tests."""

    @pytest.mark.asyncio
    async def test_returns_queued_results_in_order(self):
        """Test results are returned in FIFO order."""
        from jarviscore.testing import MockSandboxExecutor

        sandbox = MockSandboxExecutor(responses=[
            {"status": "success", "output": 42},
            {"status": "failure", "error": "bad code"},
        ])
        r1 = await sandbox.execute("result = 42")
        r2 = await sandbox.execute("bad code")
        assert r1["status"] == "success"
        assert r1["output"] == 42
        assert r2["status"] == "failure"
        assert r2["error"] == "bad code"

    @pytest.mark.asyncio
    async def test_default_success_when_queue_exhausted(self):
        """Test fallback to success when no more queued responses."""
        from jarviscore.testing import MockSandboxExecutor

        sandbox = MockSandboxExecutor()
        r = await sandbox.execute("anything")
        assert r["status"] == "success"

    @pytest.mark.asyncio
    async def test_tracks_all_executions(self):
        """Test all executions are recorded with parameters."""
        from jarviscore.testing import MockSandboxExecutor

        sandbox = MockSandboxExecutor()
        await sandbox.execute("code1", timeout=30)
        await sandbox.execute("code2", context={"key": "val"})
        assert len(sandbox.calls) == 2
        assert sandbox.calls[0]["code"] == "code1"
        assert sandbox.calls[0]["timeout"] == 30
        assert sandbox.calls[1]["context"] == {"key": "val"}

    @pytest.mark.asyncio
    async def test_result_has_required_shape(self):
        """Test every result includes status, output, error, execution_time."""
        from jarviscore.testing import MockSandboxExecutor

        sandbox = MockSandboxExecutor()
        r = await sandbox.execute("pass")
        assert "status" in r
        assert "output" in r
        assert "error" in r
        assert "execution_time" in r

    @pytest.mark.asyncio
    async def test_reset_clears_calls_and_rewinds_queue(self):
        """Test reset() clears tracking and resets response index."""
        from jarviscore.testing import MockSandboxExecutor

        sandbox = MockSandboxExecutor(responses=[{"status": "failure", "error": "e"}])
        await sandbox.execute("x")
        sandbox.reset()
        assert len(sandbox.calls) == 0
        r = await sandbox.execute("y")
        assert r["status"] == "failure"  # Back to start of queue


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
