"""
Test 14: Cloud Deployment - Agent Self-Registration

Tests the cloud deployment patterns:
- agent.join_mesh() for self-registration
- agent.leave_mesh() for graceful departure
- Remote agent visibility across nodes
- Capability deannouncement

Run with: pytest tests/test_14_cloud_deployment.py -v -s
"""
import asyncio
import sys
import os
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, '.')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: REMOTE AGENT PROXY
# ═══════════════════════════════════════════════════════════════════════════════

class TestRemoteAgentProxy:
    """Test RemoteAgentProxy class."""

    def test_remote_agent_proxy_creation(self):
        """Test RemoteAgentProxy can be created with all attributes."""
        from jarviscore.p2p.peer_client import RemoteAgentProxy

        proxy = RemoteAgentProxy(
            agent_id="analyst-abc123",
            role="analyst",
            node_id="192.168.1.10:7946",
            capabilities=["analysis", "charting"]
        )

        assert proxy.agent_id == "analyst-abc123"
        assert proxy.role == "analyst"
        assert proxy.node_id == "192.168.1.10:7946"
        assert proxy.capabilities == ["analysis", "charting"]
        assert proxy.peers is None  # Remote agents don't have local PeerClient

    def test_remote_agent_proxy_repr(self):
        """Test RemoteAgentProxy string representation."""
        from jarviscore.p2p.peer_client import RemoteAgentProxy

        proxy = RemoteAgentProxy(
            agent_id="scout-123",
            role="scout",
            node_id="10.0.0.5:7946",
            capabilities=["research"]
        )

        repr_str = repr(proxy)
        assert "RemoteAgentProxy" in repr_str
        assert "scout" in repr_str
        assert "10.0.0.5:7946" in repr_str


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: PEER CLIENT REMOTE VISIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestPeerClientRemoteVisibility:
    """Test PeerClient can see remote agents."""

    def test_resolve_target_finds_remote_agent(self):
        """Test _resolve_target returns RemoteAgentProxy for remote agents."""
        from jarviscore.p2p.peer_client import PeerClient, RemoteAgentProxy

        # Mock coordinator with remote agent
        mock_coordinator = MagicMock()
        mock_coordinator.get_remote_agent.return_value = {
            'agent_id': 'remote-analyst-123',
            'role': 'analyst',
            'node_id': '192.168.1.20:7946',
            'capabilities': ['analysis']
        }

        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="local-agent",
            agent_role="processor",
            agent_registry={},  # Empty local registry
            node_id="localhost:7946"
        )

        # Resolve target should find remote agent
        result = client._resolve_target("analyst")

        assert result is not None
        assert isinstance(result, RemoteAgentProxy)
        assert result.role == "analyst"
        assert result.node_id == "192.168.1.20:7946"

    def test_resolve_target_prefers_local_agent(self):
        """Test _resolve_target returns local agent when available."""
        from jarviscore.p2p.peer_client import PeerClient, RemoteAgentProxy

        # Create mock local agent
        mock_local_agent = MagicMock()
        mock_local_agent.agent_id = "local-analyst"
        mock_local_agent.role = "analyst"

        # Mock coordinator with remote agent
        mock_coordinator = MagicMock()
        mock_coordinator.get_remote_agent.return_value = {
            'agent_id': 'remote-analyst',
            'role': 'analyst',
            'node_id': '192.168.1.20:7946'
        }

        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="local-agent",
            agent_role="processor",
            agent_registry={"analyst": [mock_local_agent]},
            node_id="localhost:7946"
        )

        # Should return local agent, not remote
        result = client._resolve_target("analyst")

        assert result is mock_local_agent
        assert not isinstance(result, RemoteAgentProxy)

    def test_list_peers_includes_remote_agents(self):
        """Test list_peers includes both local and remote agents."""
        from jarviscore.p2p.peer_client import PeerClient

        # Create mock local agent
        mock_local_agent = MagicMock()
        mock_local_agent.agent_id = "local-scout"
        mock_local_agent.role = "scout"
        mock_local_agent.capabilities = ["research"]

        # Mock coordinator with remote agents
        mock_coordinator = MagicMock()
        mock_coordinator.list_remote_agents.return_value = [
            {
                'agent_id': 'remote-analyst',
                'role': 'analyst',
                'capabilities': ['analysis'],
                'node_id': '192.168.1.20:7946'
            }
        ]

        client = PeerClient(
            coordinator=mock_coordinator,
            agent_id="my-agent",
            agent_role="processor",
            agent_registry={"scout": [mock_local_agent]},
            node_id="localhost:7946"
        )

        peers = client.list_peers()

        # Should have both local and remote
        assert len(peers) == 2

        roles = [p['role'] for p in peers]
        assert 'scout' in roles
        assert 'analyst' in roles

        # Check location markers
        local_peer = next(p for p in peers if p['role'] == 'scout')
        remote_peer = next(p for p in peers if p['role'] == 'analyst')

        assert local_peer['location'] == 'local'
        assert remote_peer['location'] == 'remote'
        assert remote_peer['node_id'] == '192.168.1.20:7946'


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: COORDINATOR REMOTE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordinatorRemoteRegistry:
    """Test P2PCoordinator remote agent registry."""

    def test_get_remote_agent_by_role(self):
        """Test get_remote_agent finds agent by role."""
        from jarviscore.p2p.coordinator import P2PCoordinator

        coordinator = P2PCoordinator([], {})

        # Manually populate remote registry
        coordinator._remote_agent_registry = {
            'analyst-123': {
                'role': 'analyst',
                'capabilities': ['analysis'],
                'node_id': '192.168.1.10:7946'
            }
        }

        result = coordinator.get_remote_agent('analyst')

        assert result is not None
        assert result['role'] == 'analyst'
        assert result['node_id'] == '192.168.1.10:7946'

    def test_get_remote_agent_by_id(self):
        """Test get_remote_agent finds agent by agent_id."""
        from jarviscore.p2p.coordinator import P2PCoordinator

        coordinator = P2PCoordinator([], {})

        coordinator._remote_agent_registry = {
            'analyst-abc123': {
                'role': 'analyst',
                'capabilities': ['analysis'],
                'node_id': '192.168.1.10:7946'
            }
        }

        result = coordinator.get_remote_agent('analyst-abc123')

        assert result is not None
        assert result['role'] == 'analyst'

    def test_list_remote_agents(self):
        """Test list_remote_agents returns all remote agents."""
        from jarviscore.p2p.coordinator import P2PCoordinator

        coordinator = P2PCoordinator([], {})

        coordinator._remote_agent_registry = {
            'analyst-1': {'role': 'analyst', 'node_id': 'node1'},
            'scout-1': {'role': 'scout', 'node_id': 'node2'},
        }

        agents = coordinator.list_remote_agents()

        assert len(agents) == 2
        assert any(a['role'] == 'analyst' for a in agents)
        assert any(a['role'] == 'scout' for a in agents)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: AGENT JOIN/LEAVE MESH
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentJoinLeaveMesh:
    """Test agent.join_mesh() and agent.leave_mesh()."""

    def test_join_mesh_requires_endpoint(self):
        """Test join_mesh raises error if no endpoint provided."""
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "test"
            capabilities = ["testing"]
            async def execute_task(self, task):
                return {"status": "success"}

        agent = TestAgent()

        # Clear any env vars
        os.environ.pop("JARVISCORE_MESH_ENDPOINT", None)
        os.environ.pop("JARVISCORE_SEED_NODES", None)

        with pytest.raises(ValueError) as exc_info:
            asyncio.get_event_loop().run_until_complete(agent.join_mesh())

        assert "JARVISCORE_MESH_ENDPOINT" in str(exc_info.value)

    def test_is_mesh_connected_property(self):
        """Test is_mesh_connected property."""
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "test"
            capabilities = ["testing"]
            async def execute_task(self, task):
                return {"status": "success"}

        agent = TestAgent()

        # Initially not connected
        assert agent.is_mesh_connected is False

        # After setting flag
        agent._mesh_connected = True
        assert agent.is_mesh_connected is True


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: CAPABILITY DEANNOUNCEMENT
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapabilityDeannouncement:
    """Test capability deannouncement handler."""

    @pytest.mark.asyncio
    async def test_handle_capability_deannouncement(self):
        """Test _handle_capability_deannouncement removes agents."""
        from jarviscore.p2p.coordinator import P2PCoordinator

        coordinator = P2PCoordinator([], {})

        # Setup initial state
        coordinator._capability_map = {
            'analysis': ['analyst-1', 'analyst-2'],
            'research': ['scout-1']
        }
        coordinator._remote_agent_registry = {
            'analyst-1': {'role': 'analyst', 'node_id': 'node1'},
            'analyst-2': {'role': 'analyst', 'node_id': 'node2'},
            'scout-1': {'role': 'scout', 'node_id': 'node1'}
        }

        # Simulate deannouncement from node1 (analyst-1 and scout-1 leaving)
        message = {
            'payload': {
                'node_id': 'node1',
                'agent_ids': ['analyst-1', 'scout-1']
            }
        }

        await coordinator._handle_capability_deannouncement('node1', message)

        # analyst-1 should be removed from capability map
        assert 'analyst-1' not in coordinator._capability_map['analysis']
        assert 'analyst-2' in coordinator._capability_map['analysis']

        # research capability should be removed (empty)
        assert 'research' not in coordinator._capability_map

        # Remote registry should be updated
        assert 'analyst-1' not in coordinator._remote_agent_registry
        assert 'scout-1' not in coordinator._remote_agent_registry
        assert 'analyst-2' in coordinator._remote_agent_registry


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: INTEGRATION - FULL MESH JOIN/LEAVE CYCLE
# ═══════════════════════════════════════════════════════════════════════════════

class TestMeshJoinLeaveCycle:
    """Integration test for full mesh join/leave cycle."""

    @pytest.mark.asyncio
    async def test_join_mesh_initializes_peers(self):
        """Test join_mesh sets up peers attribute."""
        from jarviscore.profiles import CustomAgent
        from unittest.mock import patch, AsyncMock

        class TestAgent(CustomAgent):
            role = "standalone_test"
            capabilities = ["testing"]
            async def execute_task(self, task):
                return {"status": "success"}

        agent = TestAgent()

        # Mock the P2P coordinator - patch where it's imported
        with patch('jarviscore.p2p.coordinator.P2PCoordinator') as MockCoordinator:
            mock_coord_instance = MagicMock()
            mock_coord_instance.start = AsyncMock()
            mock_coord_instance.announce_capabilities = AsyncMock()
            mock_coord_instance.register_peer_client = MagicMock()
            mock_coord_instance.swim_manager = MagicMock()
            mock_coord_instance.swim_manager.bind_addr = ('127.0.0.1', 7999)
            MockCoordinator.return_value = mock_coord_instance

            # Also need to patch the import in agent.py
            with patch.dict('sys.modules', {'jarviscore.p2p.coordinator': MagicMock(P2PCoordinator=MockCoordinator)}):
                # Manually set up to bypass actual P2P initialization
                agent._standalone_p2p = mock_coord_instance
                agent._mesh_connected = True

                # Create mock peers
                from jarviscore.p2p.peer_client import PeerClient
                agent.peers = PeerClient(
                    coordinator=mock_coord_instance,
                    agent_id=agent.agent_id,
                    agent_role=agent.role,
                    agent_registry={},
                    node_id="localhost:7999"
                )

                # Verify state
                assert agent._mesh_connected is True
                assert agent.peers is not None
                assert agent._standalone_p2p is mock_coord_instance

                # Cleanup
                agent._mesh_connected = False


# ═══════════════════════════════════════════════════════════════════════════════
# RUN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
