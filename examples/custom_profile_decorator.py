"""
Custom Profile Example: Using @jarvis_agent Decorator

This example shows how to use the @jarvis_agent decorator to convert
any Python class into a JarvisCore agent without modifying the class.

Use Case: You have existing Python classes/agents and want JarvisCore
to handle orchestration (data handoff, dependencies, shared memory).
"""
import asyncio
from jarviscore import Mesh, jarvis_agent, JarvisContext


# Example 1: Simple decorator (no context needed)
@jarvis_agent(role="processor", capabilities=["data_processing"])
class DataProcessor:
    """Simple data processor - doubles input values."""

    def run(self, data):
        """Process data by doubling values."""
        if isinstance(data, list):
            return {"processed": [x * 2 for x in data]}
        return {"processed": data * 2}


# Example 2: Decorator with context access
@jarvis_agent(role="aggregator", capabilities=["aggregation"])
class Aggregator:
    """Aggregates results from previous steps using JarvisContext."""

    def run(self, task, ctx: JarvisContext):
        """
        Access previous step results via ctx.previous().

        Args:
            task: The task description
            ctx: JarvisContext with memory and dependency access
        """
        # Get output from a specific previous step
        processed = ctx.previous("step1")

        if processed:
            data = processed.get("processed", [])
            return {
                "sum": sum(data) if isinstance(data, list) else data,
                "count": len(data) if isinstance(data, list) else 1,
                "source_step": "step1"
            }

        return {"error": "No previous data found"}


# Example 3: Decorator with custom execute method
@jarvis_agent(role="validator", capabilities=["validation"], execute_method="validate")
class DataValidator:
    """Validates data using a custom method name."""

    def validate(self, data):
        """Custom execute method - validates input data."""
        if isinstance(data, list):
            return {
                "valid": all(isinstance(x, (int, float)) for x in data),
                "count": len(data),
                "type": "list"
            }
        return {
            "valid": isinstance(data, (int, float)),
            "type": type(data).__name__
        }


async def main():
    """Run a multi-step workflow with custom profile agents."""
    print("=" * 60)
    print("  Custom Profile Example: @jarvis_agent Decorator")
    print("=" * 60)

    # Create mesh in autonomous mode
    mesh = Mesh(mode="autonomous")

    # Add our decorated agents
    mesh.add(DataProcessor)
    mesh.add(Aggregator)
    mesh.add(DataValidator)

    # Start the mesh
    await mesh.start()

    try:
        # Execute a multi-step workflow
        print("\nExecuting workflow with 3 steps...\n")

        results = await mesh.workflow("custom-profile-demo", [
            {
                "id": "step1",
                "agent": "processor",
                "task": "Process input data",
                "params": {"data": [1, 2, 3, 4, 5]}
            },
            {
                "id": "step2",
                "agent": "aggregator",
                "task": "Aggregate processed results",
                "depends_on": ["step1"]  # Wait for step1
            },
            {
                "id": "step3",
                "agent": "validator",
                "task": "Validate original data",
                "params": {"data": [1, 2, 3, 4, 5]}
            }
        ])

        # Print results
        print("Results:")
        print("-" * 40)

        for i, result in enumerate(results):
            step_name = ["Processor", "Aggregator", "Validator"][i]
            print(f"\n{step_name} (step{i+1}):")
            print(f"  Status: {result.get('status')}")
            print(f"  Output: {result.get('output')}")

        print("\n" + "=" * 60)
        print("  Workflow completed successfully!")
        print("=" * 60)

    finally:
        # Stop the mesh
        await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
