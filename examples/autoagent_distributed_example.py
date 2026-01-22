"""
AutoAgent Distributed Mode Example

Demonstrates AutoAgent in distributed mode, which combines:
- P2P network layer (SWIM protocol, ZMQ messaging)
- Workflow orchestration (step execution, dependencies)

This is ideal for multi-node deployments where agents can:
- Execute on different machines
- Discover each other via SWIM
- Run orchestrated workflows across the network

Usage:
    python examples/autoagent_distributed_example.py

Prerequisites:
    - .env file with LLM API key (CLAUDE_API_KEY, etc.)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


# ═══════════════════════════════════════════════════════════════════════════════
# AUTOAGENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

class DataCollectorAgent(AutoAgent):
    """Collects and generates data."""
    role = "collector"
    capabilities = ["data_collection", "sampling"]
    system_prompt = """
    You are a data collection specialist. Generate sample datasets
    based on specifications. Use Python's standard library only.
    Store results in a variable named 'result' as a dictionary.
    """


class DataProcessorAgent(AutoAgent):
    """Processes and transforms data."""
    role = "processor"
    capabilities = ["data_processing", "transformation"]
    system_prompt = """
    You are a data processing expert. Transform and clean datasets.
    Apply filters, aggregations, and transformations as needed.
    Use Python's standard library only. Store results in 'result'.
    """


class ReportWriterAgent(AutoAgent):
    """Generates reports from processed data."""
    role = "reporter"
    capabilities = ["reporting", "documentation"]
    system_prompt = """
    You are a technical writer. Create clear, well-formatted reports
    from data. Use markdown formatting. Store the report in 'result'.
    """


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    """Run AutoAgent distributed mode example."""
    print("\n" + "="*70)
    print("JarvisCore: AutoAgent in Distributed Mode")
    print("="*70)

    # ─────────────────────────────────────────────────────────────────────────
    # KEY DIFFERENCE: mode="distributed" with P2P configuration
    # ─────────────────────────────────────────────────────────────────────────
    mesh = Mesh(
        mode="distributed",  # Enables P2P + Workflow Engine
        config={
            # P2P Network Configuration
            'bind_host': '127.0.0.1',    # Interface to bind to
            'bind_port': 7950,            # SWIM protocol port (ZMQ uses +1000)
            'node_name': 'autoagent-node',

            # For multi-node: uncomment to join existing cluster
            # 'seed_nodes': '192.168.1.10:7950,192.168.1.11:7950',

            # AutoAgent Configuration
            'execution_timeout': 60,      # Max seconds per task
            'max_repair_attempts': 2,     # Auto-repair on failure
            'log_directory': './logs',    # Result storage
        }
    )

    # Add agents - same as autonomous mode
    mesh.add(DataCollectorAgent)
    mesh.add(DataProcessorAgent)
    mesh.add(ReportWriterAgent)

    try:
        await mesh.start()

        print("\n[INFO] Mesh started in DISTRIBUTED mode")
        print(f"  - P2P Coordinator: Active (port {mesh.config.get('bind_port', 7950)})")
        print(f"  - Workflow Engine: Active")
        print(f"  - Agents: {len(mesh.agents)}")

        # ─────────────────────────────────────────────────────────────────────
        # WORKFLOW EXECUTION - Same API as autonomous mode
        # ─────────────────────────────────────────────────────────────────────
        print("\n" + "-"*70)
        print("Executing Pipeline: Collect → Process → Report")
        print("-"*70)

        results = await mesh.workflow("distributed-pipeline", [
            {
                "id": "collect",
                "agent": "collector",
                "task": "Generate a dataset of 10 products with name, price, and category"
            },
            {
                "id": "process",
                "agent": "processor",
                "task": "Calculate total value, average price, and count by category",
                "depends_on": ["collect"]
            },
            {
                "id": "report",
                "agent": "reporter",
                "task": "Create a summary report with the statistics",
                "depends_on": ["process"]
            }
        ])

        # Display results
        print("\n" + "="*70)
        print("RESULTS")
        print("="*70)

        for i, result in enumerate(results):
            step_names = ["Data Collection", "Data Processing", "Report Generation"]
            print(f"\n{step_names[i]}:")
            print(f"  Status: {result['status']}")
            if result['status'] == 'success':
                output = str(result.get('output', ''))[:200]
                print(f"  Output: {output}...")
            else:
                print(f"  Error: {result.get('error')}")

        # Summary
        successes = sum(1 for r in results if r['status'] == 'success')
        print(f"\n{'='*70}")
        print(f"Pipeline Complete: {successes}/{len(results)} steps successful")
        print(f"{'='*70}")

        await mesh.stop()

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-NODE EXAMPLE (Reference)
# ═══════════════════════════════════════════════════════════════════════════════

async def multi_node_example():
    """
    Example: Running agents across multiple machines.

    Node 1 (seed node):
        mesh = Mesh(mode="distributed", config={
            'bind_host': '0.0.0.0',
            'bind_port': 7950,
            'node_name': 'node-1',
        })
        mesh.add(DataCollectorAgent)
        await mesh.start()
        await mesh.serve_forever()  # Keep running

    Node 2 (joins cluster):
        mesh = Mesh(mode="distributed", config={
            'bind_host': '0.0.0.0',
            'bind_port': 7950,
            'node_name': 'node-2',
            'seed_nodes': '192.168.1.10:7950',  # Node 1's address
        })
        mesh.add(DataProcessorAgent)
        await mesh.start()
        await mesh.serve_forever()

    Node 3 (joins cluster):
        mesh = Mesh(mode="distributed", config={
            'bind_host': '0.0.0.0',
            'bind_port': 7950,
            'node_name': 'node-3',
            'seed_nodes': '192.168.1.10:7950',
        })
        mesh.add(ReportWriterAgent)
        await mesh.start()
        await mesh.serve_forever()

    Any node can now execute workflows that span all three!
    """
    pass


if __name__ == "__main__":
    asyncio.run(main())
