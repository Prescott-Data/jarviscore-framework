"""
Test 7: Distributed Mode - Single Node Tests

Tests the core distributed mode functionality on a single node:
- P2P coordinator + Workflow engine working together
- Workflow execution with dependency resolution
- Step result broadcasting
- Status tracking and memory management

This file uses MOCKED agents (no real LLM) to test the infrastructure.
Real LLM tests are in test_09 and test_10.

Run with: pytest tests/test_07_distributed_single_node.py -v
"""
import asyncio
import sys
import pytest

sys.path.insert(0, '.')

from jarviscore import Mesh, MeshMode, Agent


# ═══════════════════════════════════════════════════════════════════════════════
# TEST AGENTS (Mocked - No LLM)
# ═══════════════════════════════════════════════════════════════════════════════

class DataGeneratorAgent(Agent):
    """Generates sample data."""
    role = "generator"
    capabilities = ["data_generation", "sampling"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.tasks_executed = []

    async def execute_task(self, task):
        self.tasks_executed.append(task)
        return {
            "status": "success",
            "output": {
                "data": [
                    {"id": 1, "name": "Alice", "score": 85},
                    {"id": 2, "name": "Bob", "score": 92},
                    {"id": 3, "name": "Charlie", "score": 78}
                ],
                "count": 3
            },
            "agent": self.agent_id
        }


class DataAnalyzerAgent(Agent):
    """Analyzes data and produces insights."""
    role = "analyzer"
    capabilities = ["analysis", "statistics"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.tasks_executed = []
        self.context_received = []

    async def execute_task(self, task):
        self.tasks_executed.append(task)

        # Capture context from dependencies
        context = task.get("context", {})
        self.context_received.append(context)

        # Use previous step results if available
        previous_results = context.get("previous_step_results", {})

        return {
            "status": "success",
            "output": {
                "analysis": "Positive trend detected",
                "mean_score": 85.0,
                "received_context": bool(previous_results)
            },
            "agent": self.agent_id
        }


class DataStorageAgent(Agent):
    """Stores data to a destination."""
    role = "storage"
    capabilities = ["storage", "persistence"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.tasks_executed = []

    async def execute_task(self, task):
        self.tasks_executed.append(task)
        return {
            "status": "success",
            "output": {"saved": True, "records": 3},
            "agent": self.agent_id
        }


class FailingAgent(Agent):
    """Agent that always fails (for error testing)."""
    role = "failing"
    capabilities = ["failure"]

    async def execute_task(self, task):
        raise RuntimeError("Intentional failure for testing")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: Distributed Mode Initialization
# ═══════════════════════════════════════════════════════════════════════════════

class TestDistributedModeInitialization:
    """Tests for distributed mode setup and initialization."""

    def test_mesh_creates_in_distributed_mode(self):
        """Mesh should initialize with distributed mode."""
        mesh = Mesh(mode="distributed")

        assert mesh.mode == MeshMode.DISTRIBUTED
        assert mesh._started is False
        assert mesh._p2p_coordinator is None  # Not started yet
        assert mesh._workflow_engine is None  # Not started yet

    @pytest.mark.asyncio
    async def test_p2p_coordinator_initialized(self):
        """P2P coordinator should be initialized on start."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7950})
        mesh.add(DataGeneratorAgent)

        await mesh.start()

        try:
            assert mesh._p2p_coordinator is not None
            assert mesh._p2p_coordinator._started is True
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_workflow_engine_initialized(self):
        """Workflow engine should be initialized on start."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7951})
        mesh.add(DataGeneratorAgent)

        await mesh.start()

        try:
            assert mesh._workflow_engine is not None
            assert mesh._workflow_engine._started is True
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_both_components_initialized(self):
        """Both P2P coordinator AND workflow engine should be present."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7952})
        mesh.add(DataGeneratorAgent)

        await mesh.start()

        try:
            # This is the KEY difference from other modes
            assert mesh._p2p_coordinator is not None, "Distributed needs P2P"
            assert mesh._workflow_engine is not None, "Distributed needs Workflow"
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_capabilities_announced(self):
        """Agent capabilities should be announced to P2P mesh."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7953})
        mesh.add(DataGeneratorAgent)
        mesh.add(DataAnalyzerAgent)

        await mesh.start()

        try:
            # Check capability map was populated
            cap_map = mesh._p2p_coordinator._capability_map
            assert "data_generation" in cap_map or len(cap_map) > 0
        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: Workflow Execution in Distributed Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestDistributedWorkflowExecution:
    """Tests for workflow execution in distributed mode."""

    @pytest.fixture
    async def distributed_mesh(self):
        """Create a distributed mesh with multiple agents."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7954})
        generator = mesh.add(DataGeneratorAgent)
        analyzer = mesh.add(DataAnalyzerAgent)
        storage = mesh.add(DataStorageAgent)

        await mesh.start()

        yield mesh, generator, analyzer, storage

        await mesh.stop()

    @pytest.mark.asyncio
    async def test_single_step_workflow(self, distributed_mesh):
        """Execute a single-step workflow."""
        mesh, generator, analyzer, storage = distributed_mesh

        results = await mesh.workflow("test-single", [
            {"agent": "generator", "task": "Generate sample data"}
        ])

        assert len(results) == 1
        assert results[0]["status"] == "success"
        assert "data" in results[0]["output"]
        assert len(generator.tasks_executed) == 1

    @pytest.mark.asyncio
    async def test_multi_step_workflow(self, distributed_mesh):
        """Execute a multi-step workflow without dependencies."""
        mesh, generator, analyzer, storage = distributed_mesh

        results = await mesh.workflow("test-multi", [
            {"agent": "generator", "task": "Generate data"},
            {"agent": "analyzer", "task": "Analyze data"},
            {"agent": "storage", "task": "Store results"}
        ])

        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)
        assert len(generator.tasks_executed) == 1
        assert len(analyzer.tasks_executed) == 1
        assert len(storage.tasks_executed) == 1

    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self, distributed_mesh):
        """Execute workflow where steps depend on previous steps."""
        mesh, generator, analyzer, storage = distributed_mesh

        results = await mesh.workflow("test-deps", [
            {"agent": "generator", "task": "Generate user data"},
            {"agent": "analyzer", "task": "Analyze the data", "depends_on": [0]},
            {"agent": "storage", "task": "Store analysis", "depends_on": [1]}
        ])

        assert len(results) == 3
        assert all(r["status"] == "success" for r in results)

        # Verify analyzer received context from generator
        assert len(analyzer.context_received) == 1
        context = analyzer.context_received[0]
        assert "previous_step_results" in context
        assert "step0" in context["previous_step_results"]

    @pytest.mark.asyncio
    async def test_workflow_with_missing_agent(self, distributed_mesh):
        """Workflow should fail gracefully when agent not found."""
        mesh, generator, analyzer, storage = distributed_mesh

        results = await mesh.workflow("test-missing", [
            {"agent": "nonexistent_agent", "task": "Should fail"}
        ])

        assert len(results) == 1
        assert results[0]["status"] == "failure"
        assert "No agent found" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_workflow_routes_by_capability(self, distributed_mesh):
        """Workflow should route by capability when role not found."""
        mesh, generator, analyzer, storage = distributed_mesh

        results = await mesh.workflow("test-capability", [
            {"agent": "data_generation", "task": "Use capability routing"}
        ])

        assert len(results) == 1
        assert results[0]["status"] == "success"
        # Should have been routed to generator agent
        assert len(generator.tasks_executed) == 1

    @pytest.mark.asyncio
    async def test_step_results_stored_in_memory(self, distributed_mesh):
        """Step results should be stored in workflow memory."""
        mesh, generator, analyzer, storage = distributed_mesh

        await mesh.workflow("test-memory", [
            {"id": "gen-step", "agent": "generator", "task": "Generate"},
            {"id": "analyze-step", "agent": "analyzer", "task": "Analyze", "depends_on": ["gen-step"]}
        ])

        # Check workflow engine memory
        memory = mesh._workflow_engine.get_memory()
        assert "gen-step" in memory
        assert "analyze-step" in memory


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: Step Broadcasting
# ═══════════════════════════════════════════════════════════════════════════════

class TestDistributedStepBroadcasting:
    """Tests for P2P step result broadcasting."""

    @pytest.mark.asyncio
    async def test_broadcaster_initialized(self):
        """Broadcaster should be initialized with P2P coordinator."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7955})
        mesh.add(DataGeneratorAgent)

        await mesh.start()

        try:
            assert mesh._p2p_coordinator.broadcaster is not None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_status_manager_tracks_steps(self):
        """Status manager should track step states."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7956})
        mesh.add(DataGeneratorAgent)

        await mesh.start()

        try:
            await mesh.workflow("test-status", [
                {"id": "tracked-step", "agent": "generator", "task": "Track me"}
            ])

            # Check status was tracked
            status = mesh._workflow_engine.get_status("tracked-step")
            assert status is not None
            assert status["status"] == "completed"
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_failed_step_status_tracked(self):
        """Failed steps should have failure status."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7957})
        mesh.add(FailingAgent)

        await mesh.start()

        try:
            await mesh.workflow("test-fail-status", [
                {"id": "failing-step", "agent": "failing", "task": "Will fail"}
            ])

            status = mesh._workflow_engine.get_status("failing-step")
            assert status is not None
            assert status["status"] == "failed"
        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: Distributed Mode Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestDistributedModeLifecycle:
    """Tests for distributed mode start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self):
        """Mesh should shutdown gracefully."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7958})
        mesh.add(DataGeneratorAgent)

        await mesh.start()
        assert mesh._started is True

        await mesh.stop()
        assert mesh._started is False

    @pytest.mark.asyncio
    async def test_workflow_fails_before_start(self):
        """Workflow should fail if mesh not started."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7959})
        mesh.add(DataGeneratorAgent)

        # Don't start the mesh
        with pytest.raises(RuntimeError) as exc_info:
            await mesh.workflow("test", [{"agent": "generator", "task": "fail"}])

        assert "not started" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_agent_setup_called(self):
        """Agent setup should be called on mesh start."""
        setup_called = []

        class TrackingAgent(Agent):
            role = "tracker"
            capabilities = ["tracking"]

            async def setup(self):
                await super().setup()
                setup_called.append(self.agent_id)

            async def execute_task(self, task):
                return {"status": "success"}

        mesh = Mesh(mode="distributed", config={'bind_port': 7960})
        agent = mesh.add(TrackingAgent)

        await mesh.start()

        try:
            assert agent.agent_id in setup_called
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_agent_teardown_called(self):
        """Agent teardown should be called on mesh stop."""
        teardown_called = []

        class TrackingAgent(Agent):
            role = "tracker"
            capabilities = ["tracking"]

            async def teardown(self):
                await super().teardown()
                teardown_called.append(self.agent_id)

            async def execute_task(self, task):
                return {"status": "success"}

        mesh = Mesh(mode="distributed", config={'bind_port': 7961})
        agent = mesh.add(TrackingAgent)

        await mesh.start()
        await mesh.stop()

        assert agent.agent_id in teardown_called


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: Comparison with Other Modes
# ═══════════════════════════════════════════════════════════════════════════════

class TestDistributedVsOtherModes:
    """Tests that verify distributed mode differs from other modes."""

    def test_autonomous_mode_has_no_p2p(self):
        """Autonomous mode should NOT have P2P coordinator."""
        mesh = Mesh(mode="autonomous")
        mesh.add(DataGeneratorAgent)

        # Before start - no P2P
        assert mesh._p2p_coordinator is None

    @pytest.mark.asyncio
    async def test_autonomous_starts_without_p2p(self):
        """Autonomous mode should start without P2P."""
        mesh = Mesh(mode="autonomous")
        mesh.add(DataGeneratorAgent)

        await mesh.start()

        try:
            # Autonomous has workflow engine but NOT P2P
            assert mesh._workflow_engine is not None
            assert mesh._p2p_coordinator is None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_p2p_mode_has_no_workflow_engine(self):
        """P2P mode should NOT have workflow engine."""
        mesh = Mesh(mode="p2p", config={'bind_port': 7962})

        class P2PAgent(Agent):
            role = "p2p_agent"
            capabilities = ["p2p"]

            async def execute_task(self, task):
                return {"status": "success"}

            async def run(self):
                while not self.shutdown_requested:
                    await asyncio.sleep(0.1)

        mesh.add(P2PAgent)

        await mesh.start()

        try:
            # P2P has P2P coordinator but NOT workflow engine
            assert mesh._p2p_coordinator is not None
            assert mesh._workflow_engine is None
        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_distributed_has_both(self):
        """Distributed mode should have BOTH P2P and workflow engine."""
        mesh = Mesh(mode="distributed", config={'bind_port': 7963})
        mesh.add(DataGeneratorAgent)

        await mesh.start()

        try:
            # Distributed has BOTH
            assert mesh._p2p_coordinator is not None, "Missing P2P coordinator"
            assert mesh._workflow_engine is not None, "Missing workflow engine"
        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL RUN
# ═══════════════════════════════════════════════════════════════════════════════

async def run_manual_test():
    """Run a manual demonstration of distributed mode."""
    print("\n" + "="*70)
    print("DISTRIBUTED MODE - SINGLE NODE DEMONSTRATION")
    print("="*70)

    # Create mesh
    mesh = Mesh(mode="distributed", config={'bind_port': 7964})

    generator = mesh.add(DataGeneratorAgent)
    analyzer = mesh.add(DataAnalyzerAgent)
    storage = mesh.add(DataStorageAgent)

    print(f"\n[SETUP] Created mesh with {len(mesh.agents)} agents")
    print(f"  - Generator: {generator.role} ({generator.capabilities})")
    print(f"  - Analyzer: {analyzer.role} ({analyzer.capabilities})")
    print(f"  - Storage: {storage.role} ({storage.capabilities})")

    # Start mesh
    await mesh.start()
    print(f"\n[START] Mesh started")
    print(f"  - P2P Coordinator: {mesh._p2p_coordinator is not None}")
    print(f"  - Workflow Engine: {mesh._workflow_engine is not None}")

    # Execute workflow
    print(f"\n[WORKFLOW] Executing pipeline with dependencies...")

    results = await mesh.workflow("demo-pipeline", [
        {"id": "generate", "agent": "generator", "task": "Generate user data"},
        {"id": "analyze", "agent": "analyzer", "task": "Analyze patterns", "depends_on": ["generate"]},
        {"id": "store", "agent": "storage", "task": "Save results", "depends_on": ["analyze"]}
    ])

    print(f"\n[RESULTS]")
    for i, result in enumerate(results):
        status = result.get("status", "unknown")
        agent = result.get("agent", "unknown")
        print(f"  Step {i+1}: {status} (executed by {agent})")

    # Show memory
    print(f"\n[MEMORY] Workflow memory contains:")
    for step_id, data in mesh._workflow_engine.get_memory().items():
        print(f"  - {step_id}: {type(data).__name__}")

    # Show context injection
    print(f"\n[CONTEXT] Analyzer received context: {analyzer.context_received[0].get('previous_step_results', {}).keys()}")

    # Stop mesh
    await mesh.stop()
    print(f"\n[STOP] Mesh stopped gracefully")

    print("\n" + "="*70)
    print("DEMONSTRATION COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(run_manual_test())
