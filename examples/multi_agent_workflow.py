"""
Multi-Agent Workflow Example

Demonstrates multiple AutoAgents collaborating on a workflow with dependencies.
Shows how agents can pass data between steps automatically.

Usage:
    python examples/multi_agent_workflow.py
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


class DataGeneratorAgent(AutoAgent):
    """Generates sample data."""
    role = "generator"
    capabilities = ["data_generation", "random_data"]
    system_prompt = """
    You are a data generator. Create sample datasets based on specifications.
    Use Python's random module or create structured data.
    Store the generated data in a variable named 'result'.
    """


class DataAnalyzerAgent(AutoAgent):
    """Analyzes data and computes statistics."""
    role = "analyzer"
    capabilities = ["data_analysis", "statistics"]
    system_prompt = """
    You are a data analyst. Analyze datasets and compute statistics.
    Calculate mean, median, standard deviation, and find patterns.
    Store your analysis results in a variable named 'result'.
    """


class ReportGeneratorAgent(AutoAgent):
    """Creates formatted reports."""
    role = "reporter"
    capabilities = ["report_generation", "formatting"]
    system_prompt = """
    You are a report generator. Create well-formatted reports from data.
    Generate markdown or plain text reports with clear sections.
    Store the formatted report in a variable named 'result'.
    """


async def main():
    """Run multi-agent workflow."""
    print("\n" + "="*60)
    print("JarvisCore: Multi-Agent Workflow Example")
    print("="*60)

    # Zero-config: Reads from .env automatically
    # Framework tries: Claude → Azure → Gemini → vLLM

    # Create mesh with all agents
    mesh = Mesh(mode="autonomous")
    mesh.add(DataGeneratorAgent)
    mesh.add(DataAnalyzerAgent)
    mesh.add(ReportGeneratorAgent)

    try:
        await mesh.start()
        print(f"✓ Mesh started with {len(mesh.agents)} agents\n")

        print("Workflow: Generate → Analyze → Report")
        print("-" * 60)

        # Execute 3-step workflow with dependencies
        results = await mesh.workflow("data-pipeline", [
            {
                "id": "generate",
                "agent": "generator",
                "task": "Generate a list of 20 random numbers between 1 and 100"
            },
            {
                "id": "analyze",
                "agent": "analyzer",
                "task": "Calculate mean, median, min, max, and standard deviation of the data",
                "depends_on": ["generate"]  # Waits for generator to complete
            },
            {
                "id": "report",
                "agent": "reporter",
                "task": "Create a formatted report with the statistics",
                "depends_on": ["analyze"]  # Waits for analyzer to complete
            }
        ])

        # Display results
        print("\n" + "="*60)
        print("RESULTS")
        print("="*60)

        print(f"\nStep 1 - Data Generation:")
        print(f"  Status: {results[0]['status']}")
        print(f"  Output: {results[0].get('output')}")

        print(f"\nStep 2 - Data Analysis:")
        print(f"  Status: {results[1]['status']}")
        print(f"  Output: {results[1].get('output')}")

        print(f"\nStep 3 - Report Generation:")
        print(f"  Status: {results[2]['status']}")
        print(f"  Report:\n{results[2].get('output')}")

        print(f"\n" + "="*60)
        print("WORKFLOW SUMMARY")
        print("="*60)
        total_repairs = sum(r.get('repairs', 0) for r in results)
        print(f"Total steps: {len(results)}")
        print(f"Successful: {sum(1 for r in results if r['status'] == 'success')}")
        print(f"Total repairs: {total_repairs}")

        await mesh.stop()
        print("\n✓ Workflow completed\n")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
