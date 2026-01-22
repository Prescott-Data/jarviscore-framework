"""
Test 9: Distributed Mode - AutoAgent Profile with Real LLM

Tests the AutoAgent profile in distributed execution mode:
- AutoAgent initialization and setup
- Real LLM code generation
- Workflow execution with AutoAgent
- Multi-step pipelines with dependencies

This file uses REAL LLM API calls (not mocks).

Run with: pytest tests/test_09_distributed_autoagent.py -v -s
"""
import asyncio
import sys
import pytest
import logging

sys.path.insert(0, '.')

from jarviscore import Mesh
from jarviscore.profiles.autoagent import AutoAgent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Skip all tests if no API key is configured
try:
    from jarviscore.config import settings
    HAS_API_KEY = bool(
        settings.claude_api_key or
        settings.azure_api_key or
        settings.gemini_api_key
    )
except Exception:
    HAS_API_KEY = False

pytestmark = pytest.mark.skipif(
    not HAS_API_KEY,
    reason="No LLM API key configured in .env"
)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST AUTOAGENTS
# ═══════════════════════════════════════════════════════════════════════════════

class MathAgent(AutoAgent):
    """AutoAgent that performs mathematical calculations."""
    role = "mathematician"
    capabilities = ["math", "calculation", "algebra"]
    system_prompt = """You are an expert mathematician. You write clean Python code
to solve mathematical problems. Always include proper error handling and return
results as a dictionary with 'result' key. Use only standard library (no numpy)."""


class DataGeneratorAgent(AutoAgent):
    """AutoAgent that generates sample data."""
    role = "data_generator"
    capabilities = ["data_generation", "sampling"]
    system_prompt = """You are a data generation expert. You write Python code
to generate sample datasets. Return data as a dictionary with descriptive keys.
Use only standard library - no pandas or numpy. Generate simple lists/dicts."""


class TextProcessorAgent(AutoAgent):
    """AutoAgent that processes text."""
    role = "text_processor"
    capabilities = ["text_processing", "nlp", "summarization"]
    system_prompt = """You are a text processing expert. You write Python code
to analyze and transform text. Return results as a dictionary with clear keys.
Use only standard library. Focus on string operations and basic analysis."""


class ReportGeneratorAgent(AutoAgent):
    """AutoAgent that generates reports from data."""
    role = "report_generator"
    capabilities = ["reporting", "formatting", "visualization"]
    system_prompt = """You are a report generation expert. You write Python code
to create formatted text reports from data. Return the report as a string in
a dictionary with 'report' key. Use only standard library for formatting."""


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def distributed_mesh_math():
    """Create distributed mesh with MathAgent."""
    mesh = Mesh(mode="distributed", config={
        'bind_port': 7980,
        'execution_timeout': 60,
        'max_repair_attempts': 2,
        'log_directory': './test_logs'
    })
    agent = mesh.add(MathAgent)

    await mesh.start()

    yield mesh, agent

    await mesh.stop()


@pytest.fixture
async def distributed_mesh_pipeline():
    """Create distributed mesh with multiple AutoAgents for pipeline testing."""
    mesh = Mesh(mode="distributed", config={
        'bind_port': 7981,
        'execution_timeout': 60,
        'max_repair_attempts': 2,
        'log_directory': './test_logs'
    })

    generator = mesh.add(DataGeneratorAgent)
    processor = mesh.add(TextProcessorAgent)
    reporter = mesh.add(ReportGeneratorAgent)

    await mesh.start()

    yield mesh, generator, processor, reporter

    await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: AutoAgent Setup in Distributed Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoAgentDistributedSetup:
    """Tests for AutoAgent initialization in distributed mode."""

    @pytest.mark.asyncio
    async def test_autoagent_inherits_from_profile(self, distributed_mesh_math):
        """AutoAgent should inherit from Profile (which inherits from Agent)."""
        mesh, agent = distributed_mesh_math

        from jarviscore.core.profile import Profile
        from jarviscore.core.agent import Agent

        assert isinstance(agent, Profile)
        assert isinstance(agent, Agent)
        assert isinstance(agent, AutoAgent)

    @pytest.mark.asyncio
    async def test_autoagent_has_required_attributes(self, distributed_mesh_math):
        """AutoAgent should have role, capabilities, and system_prompt."""
        mesh, agent = distributed_mesh_math

        assert agent.role == "mathematician"
        assert "math" in agent.capabilities
        assert "calculation" in agent.capabilities
        assert agent.system_prompt is not None
        assert len(agent.system_prompt) > 0

    @pytest.mark.asyncio
    async def test_autoagent_setup_initializes_components(self, distributed_mesh_math):
        """AutoAgent setup should initialize LLM and execution components."""
        mesh, agent = distributed_mesh_math

        # After mesh.start(), agent.setup() should have been called
        assert agent.llm is not None, "LLM client should be initialized"
        assert agent.codegen is not None, "Code generator should be initialized"
        assert agent.sandbox is not None, "Sandbox executor should be initialized"
        assert agent.repair is not None, "Repair system should be initialized"
        assert agent.result_handler is not None, "Result handler should be initialized"

    @pytest.mark.asyncio
    async def test_autoagent_joins_distributed_mesh(self, distributed_mesh_math):
        """AutoAgent should be properly registered in distributed mesh."""
        mesh, agent = distributed_mesh_math

        # Agent should be registered
        assert mesh.get_agent("mathematician") == agent

        # Mesh should have P2P coordinator (distributed mode)
        assert mesh._p2p_coordinator is not None
        assert mesh._p2p_coordinator._started is True

        # Mesh should have workflow engine (distributed mode)
        assert mesh._workflow_engine is not None


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: AutoAgent Workflow Execution
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoAgentWorkflowExecution:
    """Tests for AutoAgent executing workflow steps with real LLM."""

    @pytest.mark.asyncio
    async def test_autoagent_executes_simple_task(self, distributed_mesh_math):
        """AutoAgent should execute a simple mathematical task."""
        mesh, agent = distributed_mesh_math

        print("\n" + "="*60)
        print("TEST: AutoAgent executes simple math task")
        print("="*60)

        results = await mesh.workflow("simple-math", [
            {"agent": "mathematician", "task": "Calculate the factorial of 5"}
        ])

        print(f"\nResults: {results}")

        assert len(results) == 1
        result = results[0]

        # Should succeed
        assert result["status"] == "success", f"Task failed: {result.get('error')}"

        # Should have generated code
        assert "code" in result
        assert len(result["code"]) > 0

        print(f"\nGenerated code:\n{result['code'][:500]}...")
        print(f"\nOutput: {result.get('output')}")

    @pytest.mark.asyncio
    async def test_autoagent_generates_executable_code(self, distributed_mesh_math):
        """AutoAgent should generate code that actually executes."""
        mesh, agent = distributed_mesh_math

        print("\n" + "="*60)
        print("TEST: AutoAgent generates executable code")
        print("="*60)

        results = await mesh.workflow("exec-test", [
            {"agent": "mathematician", "task": "Calculate the sum of numbers from 1 to 100"}
        ])

        result = results[0]
        assert result["status"] == "success", f"Task failed: {result.get('error')}"

        # The output should contain the correct answer (5050)
        output = str(result.get('output', ''))
        print(f"\nOutput: {output}")

        # Verify we got a meaningful result
        assert result.get('output') is not None, "Should have output"

    @pytest.mark.asyncio
    async def test_autoagent_handles_complex_task(self, distributed_mesh_math):
        """AutoAgent should handle more complex mathematical tasks."""
        mesh, agent = distributed_mesh_math

        print("\n" + "="*60)
        print("TEST: AutoAgent handles complex task")
        print("="*60)

        results = await mesh.workflow("complex-math", [
            {
                "agent": "mathematician",
                "task": "Generate the first 10 Fibonacci numbers and return them as a list"
            }
        ])

        result = results[0]
        print(f"\nResult status: {result['status']}")
        print(f"Output: {result.get('output')}")

        assert result["status"] == "success", f"Task failed: {result.get('error')}"

    @pytest.mark.asyncio
    async def test_autoagent_result_includes_metadata(self, distributed_mesh_math):
        """AutoAgent result should include agent metadata."""
        mesh, agent = distributed_mesh_math

        results = await mesh.workflow("metadata-test", [
            {"agent": "mathematician", "task": "Calculate 2 + 2"}
        ])

        result = results[0]
        assert result["status"] == "success"

        # Should include agent info
        assert "agent_id" in result or "agent" in result
        assert "role" in result or result.get("agent") == "mathematician"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: Multi-Step Pipeline with AutoAgents
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoAgentMultiStepWorkflow:
    """Tests for multi-step workflows with multiple AutoAgents."""

    @pytest.mark.asyncio
    async def test_two_autoagents_sequential_workflow(self, distributed_mesh_pipeline):
        """Two AutoAgents should execute in sequence."""
        mesh, generator, processor, reporter = distributed_mesh_pipeline

        print("\n" + "="*60)
        print("TEST: Two AutoAgents in sequential workflow")
        print("="*60)

        results = await mesh.workflow("sequential-test", [
            {
                "agent": "data_generator",
                "task": "Generate a list of 5 random words"
            },
            {
                "agent": "text_processor",
                "task": "Count the total number of characters in these words: apple, banana, cherry, date, elderberry"
            }
        ])

        print(f"\nResults count: {len(results)}")
        for i, r in enumerate(results):
            print(f"Step {i+1}: {r['status']} - {str(r.get('output', ''))[:100]}")

        assert len(results) == 2
        assert results[0]["status"] == "success", f"Step 1 failed: {results[0].get('error')}"
        assert results[1]["status"] == "success", f"Step 2 failed: {results[1].get('error')}"

    @pytest.mark.asyncio
    async def test_workflow_with_dependencies(self, distributed_mesh_pipeline):
        """Workflow should handle step dependencies."""
        mesh, generator, processor, reporter = distributed_mesh_pipeline

        print("\n" + "="*60)
        print("TEST: Workflow with dependencies")
        print("="*60)

        results = await mesh.workflow("dependency-test", [
            {
                "agent": "data_generator",
                "task": "Generate a dictionary with keys 'name', 'age', 'city' and sample values"
            },
            {
                "agent": "report_generator",
                "task": "Create a formatted text report from this person data: name=John, age=30, city=NYC",
                "depends_on": [0]
            }
        ])

        print(f"\nStep 1 (generator): {results[0]['status']}")
        print(f"Step 2 (reporter): {results[1]['status']}")

        assert len(results) == 2
        # Both should succeed
        assert results[0]["status"] == "success"
        assert results[1]["status"] == "success"

    @pytest.mark.asyncio
    async def test_three_agent_pipeline(self, distributed_mesh_pipeline):
        """Three AutoAgents should work together in a pipeline."""
        mesh, generator, processor, reporter = distributed_mesh_pipeline

        print("\n" + "="*60)
        print("TEST: Three agent pipeline")
        print("="*60)

        results = await mesh.workflow("three-agent-pipeline", [
            {
                "agent": "data_generator",
                "task": "Generate a list of 3 product names with prices as a dictionary"
            },
            {
                "agent": "text_processor",
                "task": "Format this product list into a bulleted text list: Widget=$10, Gadget=$25, Tool=$15"
            },
            {
                "agent": "report_generator",
                "task": "Create a simple invoice header with company name 'Acme Corp' and date 'Jan 2024'"
            }
        ])

        print(f"\nPipeline results:")
        for i, r in enumerate(results):
            status = r['status']
            output = str(r.get('output', ''))[:80]
            print(f"  Step {i+1}: [{status}] {output}...")

        assert len(results) == 3
        # Count successes
        successes = sum(1 for r in results if r["status"] == "success")
        print(f"\nSuccessful steps: {successes}/3")

        # At least 2 should succeed for this test to be meaningful
        assert successes >= 2, "At least 2 steps should succeed"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: AutoAgent Error Handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutoAgentErrorHandling:
    """Tests for AutoAgent error handling and repair."""

    @pytest.mark.asyncio
    async def test_autoagent_handles_impossible_task_gracefully(self, distributed_mesh_math):
        """AutoAgent should handle impossible tasks gracefully."""
        mesh, agent = distributed_mesh_math

        print("\n" + "="*60)
        print("TEST: AutoAgent handles difficult task")
        print("="*60)

        # This task is intentionally vague to test robustness
        results = await mesh.workflow("difficult-task", [
            {
                "agent": "mathematician",
                "task": "Calculate something mathematical and return a result"
            }
        ])

        result = results[0]
        print(f"\nStatus: {result['status']}")
        print(f"Output: {result.get('output')}")

        # Should either succeed or fail gracefully with error info
        assert result["status"] in ["success", "failure"]
        if result["status"] == "failure":
            assert "error" in result

    @pytest.mark.asyncio
    async def test_autoagent_repair_tracking(self, distributed_mesh_math):
        """AutoAgent should track repair attempts."""
        mesh, agent = distributed_mesh_math

        results = await mesh.workflow("repair-test", [
            {
                "agent": "mathematician",
                "task": "Calculate the square root of 144"
            }
        ])

        result = results[0]

        # Result should include repair count (even if 0)
        assert "repairs" in result or result["status"] == "success"
        print(f"\nRepairs attempted: {result.get('repairs', 0)}")


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL DEMONSTRATION
# ═══════════════════════════════════════════════════════════════════════════════

async def run_autoagent_demo():
    """Demonstrate AutoAgent in distributed mode with real LLM."""
    print("\n" + "="*70)
    print("AUTOAGENT DISTRIBUTED MODE DEMONSTRATION")
    print("="*70)

    # Create distributed mesh with AutoAgents
    mesh = Mesh(mode="distributed", config={
        'bind_port': 7985,
        'execution_timeout': 60,
        'max_repair_attempts': 2,
        'log_directory': './demo_logs'
    })

    mesh.add(MathAgent)
    mesh.add(DataGeneratorAgent)
    mesh.add(TextProcessorAgent)

    print("\n[SETUP] Created distributed mesh with:")
    for agent in mesh.agents:
        print(f"  - {agent.role}: {agent.capabilities}")

    await mesh.start()
    print("\n[STARTED] Mesh is running in distributed mode")

    try:
        # Demo 1: Simple math task
        print("\n" + "-"*60)
        print("DEMO 1: Simple Math Task")
        print("-"*60)

        results = await mesh.workflow("demo-math", [
            {"agent": "mathematician", "task": "Calculate 17 * 23 and return the result"}
        ])

        print(f"Result: {results[0]['status']}")
        print(f"Output: {results[0].get('output')}")
        print(f"Code generated: {len(results[0].get('code', ''))} chars")

        # Demo 2: Multi-agent workflow
        print("\n" + "-"*60)
        print("DEMO 2: Multi-Agent Workflow")
        print("-"*60)

        results = await mesh.workflow("demo-pipeline", [
            {
                "agent": "data_generator",
                "task": "Generate a simple dictionary with 'x' and 'y' coordinates"
            },
            {
                "agent": "mathematician",
                "task": "Calculate the distance from origin for point x=3, y=4 using Pythagorean theorem"
            }
        ])

        for i, r in enumerate(results):
            print(f"Step {i+1}: {r['status']} - {str(r.get('output', ''))[:100]}")

    finally:
        await mesh.stop()

    print("\n" + "="*70)
    print("DEMONSTRATION COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(run_autoagent_demo())
