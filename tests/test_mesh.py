"""
Tests for Mesh orchestrator.
"""
import pytest
from jarviscore import Mesh, MeshMode, Agent


# Test agents
class TestAgent1(Agent):
    """Test agent with role 'agent1'."""
    role = "agent1"
    capabilities = ["capability1", "shared_capability"]

    async def execute_task(self, task):
        return {"status": "success", "output": f"Result from {self.role}"}


class TestAgent2(Agent):
    """Test agent with role 'agent2'."""
    role = "agent2"
    capabilities = ["capability2", "shared_capability"]

    async def execute_task(self, task):
        return {"status": "success", "output": f"Result from {self.role}"}


class TestMeshInitialization:
    """Test mesh initialization."""

    def test_mesh_creation_default_mode(self):
        """Test creating mesh with default mode."""
        mesh = Mesh()

        assert mesh.mode == MeshMode.AUTONOMOUS
        assert mesh.config == {}
        assert mesh.agents == []
        assert mesh._started is False

    def test_mesh_creation_autonomous_mode(self):
        """Test creating mesh in autonomous mode."""
        mesh = Mesh(mode="autonomous")

        assert mesh.mode == MeshMode.AUTONOMOUS

    def test_mesh_creation_distributed_mode(self):
        """Test creating mesh in distributed mode."""
        mesh = Mesh(mode="distributed")

        assert mesh.mode == MeshMode.DISTRIBUTED

    def test_mesh_creation_invalid_mode(self):
        """Test that invalid mode raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            Mesh(mode="invalid_mode")

        assert "Invalid mode" in str(exc_info.value)

    def test_mesh_creation_with_config(self):
        """Test creating mesh with configuration."""
        config = {
            "p2p_enabled": True,
            "state_backend": "redis",
            "max_parallel": 10
        }
        mesh = Mesh(config=config)

        assert mesh.config == config


class TestMeshAgentRegistration:
    """Test agent registration with mesh."""

    def test_add_single_agent(self):
        """Test adding a single agent to mesh."""
        mesh = Mesh()
        agent = mesh.add(TestAgent1)

        assert len(mesh.agents) == 1
        assert agent.role == "agent1"
        assert agent._mesh is mesh
        assert mesh.get_agent("agent1") == agent

    def test_add_multiple_agents(self):
        """Test adding multiple agents to mesh."""
        mesh = Mesh()
        agent1 = mesh.add(TestAgent1)
        agent2 = mesh.add(TestAgent2)

        assert len(mesh.agents) == 2
        assert mesh.get_agent("agent1") == agent1
        assert mesh.get_agent("agent2") == agent2

    def test_add_agent_with_custom_id(self):
        """Test adding agent with custom ID."""
        mesh = Mesh()
        agent = mesh.add(TestAgent1, agent_id="custom-123")

        assert agent.agent_id == "custom-123"
        assert mesh.get_agent("agent1") == agent

    def test_add_duplicate_role_fails(self):
        """Test that adding agent with duplicate role raises ValueError."""
        mesh = Mesh()
        mesh.add(TestAgent1)

        with pytest.raises(ValueError) as exc_info:
            mesh.add(TestAgent1)

        assert "already registered" in str(exc_info.value)

    def test_add_invalid_agent_class_fails(self):
        """Test that adding non-Agent class raises TypeError."""
        mesh = Mesh()

        class NotAnAgent:
            pass

        with pytest.raises(TypeError) as exc_info:
            mesh.add(NotAnAgent)

        assert "must inherit from Agent" in str(exc_info.value)


class TestMeshCapabilityIndex:
    """Test mesh capability indexing."""

    def test_get_agents_by_capability_single(self):
        """Test getting agents by capability (single match)."""
        mesh = Mesh()
        agent1 = mesh.add(TestAgent1)

        agents = mesh.get_agents_by_capability("capability1")

        assert len(agents) == 1
        assert agents[0] == agent1

    def test_get_agents_by_capability_multiple(self):
        """Test getting agents by capability (multiple matches)."""
        mesh = Mesh()
        agent1 = mesh.add(TestAgent1)
        agent2 = mesh.add(TestAgent2)

        agents = mesh.get_agents_by_capability("shared_capability")

        assert len(agents) == 2
        assert agent1 in agents
        assert agent2 in agents

    def test_get_agents_by_capability_none(self):
        """Test getting agents by capability (no matches)."""
        mesh = Mesh()
        mesh.add(TestAgent1)

        agents = mesh.get_agents_by_capability("nonexistent")

        assert agents == []


class TestMeshLifecycle:
    """Test mesh start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_mesh_calls_agent_setup(self):
        """Test that start() calls setup() on all agents."""
        mesh = Mesh()

        # Track setup calls
        setup_called = []

        class TrackingAgent(Agent):
            role = "tracker"
            capabilities = ["tracking"]

            async def execute_task(self, task):
                return {"status": "success"}

            async def setup(self):
                await super().setup()
                setup_called.append(self.agent_id)

        agent1 = mesh.add(TrackingAgent, agent_id="tracker-1")
        agent2 = mesh.add(TrackingAgent, agent_id="tracker-2")

        await mesh.start()

        assert agent1.agent_id in setup_called
        assert agent2.agent_id in setup_called
        assert mesh._started is True

    @pytest.mark.asyncio
    async def test_start_mesh_without_agents_fails(self):
        """Test that start() fails if no agents registered."""
        mesh = Mesh()

        with pytest.raises(RuntimeError) as exc_info:
            await mesh.start()

        assert "No agents registered" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_start_mesh_twice_fails(self):
        """Test that start() fails if mesh already started."""
        mesh = Mesh()
        mesh.add(TestAgent1)

        await mesh.start()

        with pytest.raises(RuntimeError) as exc_info:
            await mesh.start()

        assert "already started" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_stop_mesh_calls_agent_teardown(self):
        """Test that stop() calls teardown() on all agents."""
        mesh = Mesh()

        # Track teardown calls
        teardown_called = []

        class TrackingAgent(Agent):
            role = "tracker"
            capabilities = ["tracking"]

            async def execute_task(self, task):
                return {"status": "success"}

            async def teardown(self):
                await super().teardown()
                teardown_called.append(self.agent_id)

        agent1 = mesh.add(TrackingAgent, agent_id="tracker-1")
        agent2 = mesh.add(TrackingAgent, agent_id="tracker-2")

        await mesh.start()
        await mesh.stop()

        assert agent1.agent_id in teardown_called
        assert agent2.agent_id in teardown_called
        assert mesh._started is False


class TestMeshWorkflow:
    """Test mesh workflow execution (autonomous mode)."""

    @pytest.mark.asyncio
    async def test_workflow_execution_single_step(self):
        """Test executing single-step workflow."""
        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent1)

        await mesh.start()

        results = await mesh.workflow("test-workflow", [
            {"agent": "agent1", "task": "Do something"}
        ])

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert "agent1" in results[0]["agent"]

    @pytest.mark.asyncio
    async def test_workflow_execution_multiple_steps(self):
        """Test executing multi-step workflow."""
        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent1)
        mesh.add(TestAgent2)

        await mesh.start()

        results = await mesh.workflow("test-workflow", [
            {"agent": "agent1", "task": "Step 1"},
            {"agent": "agent2", "task": "Step 2"}
        ])

        assert len(results) == 2
        assert all(r["status"] == "success" for r in results)

    @pytest.mark.asyncio
    async def test_workflow_with_capability_routing(self):
        """Test workflow routing by capability."""
        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent1)

        await mesh.start()

        results = await mesh.workflow("test-workflow", [
            {"agent": "capability1", "task": "Use capability"}
        ])

        assert len(results) == 1
        assert results[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_workflow_agent_not_found(self):
        """Test workflow with missing agent."""
        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent1)

        await mesh.start()

        results = await mesh.workflow("test-workflow", [
            {"agent": "nonexistent", "task": "Should fail"}
        ])

        assert len(results) == 1
        assert results[0]["status"] == "failure"
        assert "No agent found" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_workflow_not_started_fails(self):
        """Test that workflow() fails if mesh not started."""
        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent1)

        with pytest.raises(RuntimeError) as exc_info:
            await mesh.workflow("test-workflow", [
                {"agent": "agent1", "task": "Should fail"}
            ])

        assert "not started" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_workflow_distributed_mode_fails(self):
        """Test that workflow() fails in distributed mode."""
        # Use unique port to avoid conflicts with P2P tests
        mesh = Mesh(mode="distributed", config={'bind_port': 7999})
        mesh.add(TestAgent1)

        await mesh.start()

        with pytest.raises(RuntimeError) as exc_info:
            await mesh.workflow("test-workflow", [
                {"agent": "agent1", "task": "Should fail"}
            ])

        assert "only available in autonomous mode" in str(exc_info.value)

        await mesh.stop()


class TestMeshRepresentation:
    """Test mesh string representation."""

    def test_mesh_repr(self):
        """Test mesh __repr__."""
        mesh = Mesh(mode="autonomous")
        mesh.add(TestAgent1)
        mesh.add(TestAgent2)

        repr_str = repr(mesh)

        assert "Mesh" in repr_str
        assert "autonomous" in repr_str
        assert "agents=2" in repr_str
        assert "started=False" in repr_str
