"""
Test 18: Mesh Diagnostics (Feature F5)

Tests the mesh.get_diagnostics() method:
- Diagnostics before mesh.start()
- Diagnostics in autonomous mode
- Diagnostics in P2P mode
- Connectivity status values
- Local agents structure

Run with: pytest tests/test_18_mesh_diagnostics.py -v -s
"""
import asyncio
import sys
import pytest
import logging
from unittest.mock import MagicMock, patch

sys.path.insert(0, '.')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# TEST: DIAGNOSTICS STRUCTURE
# =============================================================================

class TestDiagnosticsStructure:
    """Test diagnostics returns expected structure."""

    @pytest.mark.asyncio
    async def test_diagnostics_has_required_keys(self):
        """Test diagnostics contains all required top-level keys."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "test_agent"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()

            assert "local_node" in diag
            assert "known_peers" in diag
            assert "local_agents" in diag
            assert "connectivity_status" in diag
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_local_node_structure(self):
        """Test local_node contains expected fields."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "node_test"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            local_node = diag["local_node"]

            assert "mode" in local_node
            assert "started" in local_node
            assert "agent_count" in local_node
            assert local_node["mode"] == "autonomous"
            assert local_node["started"] is True
            assert local_node["agent_count"] == 1
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_local_agents_structure(self):
        """Test local_agents contains proper agent info."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class AgentA(CustomAgent):
            role = "agent_a"
            capabilities = ["cap_a", "shared"]

            async def on_peer_request(self, msg):
                return {}

        class AgentB(CustomAgent):
            role = "agent_b"
            capabilities = ["cap_b", "shared"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(AgentA)
        mesh.add(AgentB)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            agents = diag["local_agents"]

            assert len(agents) == 2

            roles = {a["role"] for a in agents}
            assert "agent_a" in roles
            assert "agent_b" in roles

            for agent in agents:
                assert "role" in agent
                assert "agent_id" in agent
                assert "capabilities" in agent
        finally:
            await mesh.stop()


# =============================================================================
# TEST: DIAGNOSTICS BEFORE START
# =============================================================================

class TestDiagnosticsBeforeStart:
    """Test diagnostics behavior before mesh.start()."""

    def test_diagnostics_before_start_returns_not_started(self):
        """Test connectivity_status is 'not_started' before start()."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "pre_start"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent)

        diag = mesh.get_diagnostics()

        assert diag["connectivity_status"] == "not_started"
        assert diag["local_node"]["started"] is False

    def test_diagnostics_before_start_shows_registered_agents(self):
        """Test local_agents shows registered agents even before start."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "registered"
            capabilities = ["cap1", "cap2"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent)

        diag = mesh.get_diagnostics()

        assert len(diag["local_agents"]) == 1
        assert diag["local_agents"][0]["role"] == "registered"


# =============================================================================
# TEST: CONNECTIVITY STATUS VALUES
# =============================================================================

class TestConnectivityStatus:
    """Test connectivity_status values."""

    @pytest.mark.asyncio
    async def test_autonomous_mode_local_only(self):
        """Test autonomous mode reports 'local_only' status."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "local_agent"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            # Autonomous mode without P2P coordinator should be local_only
            assert diag["connectivity_status"] in ["local_only", "healthy"]
        finally:
            await mesh.stop()

    def test_not_started_status(self):
        """Test 'not_started' status before mesh.start()."""
        from jarviscore import Mesh

        mesh = Mesh(mode="autonomous")
        diag = mesh.get_diagnostics()

        assert diag["connectivity_status"] == "not_started"


# =============================================================================
# TEST: MOCK MESH DIAGNOSTICS
# =============================================================================

class TestMockMeshDiagnostics:
    """Test MockMesh.get_diagnostics() compatibility."""

    @pytest.mark.asyncio
    async def test_mock_mesh_diagnostics_structure(self):
        """Test MockMesh returns compatible diagnostics structure."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "mock_agent"
            capabilities = ["mock_cap"]

            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()

            assert "local_node" in diag
            assert "known_peers" in diag
            assert "local_agents" in diag
            assert "connectivity_status" in diag
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_mock_mesh_diagnostics_status(self):
        """Test MockMesh returns 'mock' connectivity status."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "mock_agent"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            assert diag["connectivity_status"] == "mock"
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_mock_mesh_local_agents_info(self):
        """Test MockMesh diagnostics includes agent capabilities."""
        from jarviscore.testing import MockMesh
        from jarviscore.profiles import CustomAgent

        class AgentWithCaps(CustomAgent):
            role = "capable"
            capabilities = ["analysis", "reporting", "storage"]

            async def on_peer_request(self, msg):
                return {}

        mesh = MockMesh()
        mesh.add(AgentWithCaps)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            agents = diag["local_agents"]

            assert len(agents) == 1
            assert agents[0]["role"] == "capable"
            assert set(agents[0]["capabilities"]) == {"analysis", "reporting", "storage"}
        finally:
            await mesh.stop()


# =============================================================================
# TEST: DIAGNOSTICS WITH MULTIPLE MODES
# =============================================================================

class TestDiagnosticsWithModes:
    """Test diagnostics in different mesh modes."""

    @pytest.mark.asyncio
    async def test_diagnostics_autonomous_mode(self):
        """Test diagnostics in autonomous mode."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "auto_agent"
            capabilities = ["auto"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            assert diag["local_node"]["mode"] == "autonomous"
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_diagnostics_distributed_mode(self):
        """Test diagnostics in distributed mode."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "dist_agent"
            capabilities = ["distributed"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="distributed", config={
            "bind_host": "127.0.0.1",
            "bind_port": 7950
        })
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            assert diag["local_node"]["mode"] == "distributed"
            # P2P mode should include additional diagnostics
            # Note: keepalive_status may not be present depending on config
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_diagnostics_p2p_mode(self):
        """Test diagnostics in p2p mode."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "p2p_agent"
            capabilities = ["p2p"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="p2p", config={
            "bind_host": "127.0.0.1",
            "bind_port": 7951
        })
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            assert diag["local_node"]["mode"] == "p2p"
        finally:
            await mesh.stop()


# =============================================================================
# TEST: DIAGNOSTICS AGENT COUNT
# =============================================================================

class TestDiagnosticsAgentCount:
    """Test agent count accuracy in diagnostics."""

    @pytest.mark.asyncio
    async def test_agent_count_single(self):
        """Test agent_count with single agent."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class TestAgent(CustomAgent):
            role = "single"
            capabilities = ["testing"]

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            assert diag["local_node"]["agent_count"] == 1
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_agent_count_multiple(self):
        """Test agent_count with multiple agents."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class Agent1(CustomAgent):
            role = "agent1"
            capabilities = ["cap1"]
            async def on_peer_request(self, msg):
                return {}

        class Agent2(CustomAgent):
            role = "agent2"
            capabilities = ["cap2"]
            async def on_peer_request(self, msg):
                return {}

        class Agent3(CustomAgent):
            role = "agent3"
            capabilities = ["cap3"]
            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="autonomous")
        mesh.add(Agent1)
        mesh.add(Agent2)
        mesh.add(Agent3)
        await mesh.start()

        try:
            diag = mesh.get_diagnostics()
            assert diag["local_node"]["agent_count"] == 3
            assert len(diag["local_agents"]) == 3
        finally:
            await mesh.stop()


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
