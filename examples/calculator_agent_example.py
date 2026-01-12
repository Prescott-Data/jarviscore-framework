"""
Calculator Agent Example - Simple Math Operations

Demonstrates AutoAgent with code generation for mathematical tasks.
Zero configuration required - just define the agent and run.

Usage:
    python examples/calculator_agent_example.py
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


class CalculatorAgent(AutoAgent):
    """Math expert agent that generates code to solve problems."""
    role = "calculator"
    capabilities = ["math", "calculation", "arithmetic"]
    system_prompt = """
    You are a math expert. Generate Python code to solve mathematical problems.
    Store the final answer in a variable named 'result'.
    Use standard math operations and the math module when needed.
    """


async def main():
    """Run calculator agent examples."""
    print("\n" + "="*60)
    print("JarvisCore: Calculator Agent Example")
    print("="*60)

    # Zero-config: Framework auto-detects LLM from .env
    # Tries: Claude → Azure → Gemini → vLLM (based on .env)
    # Or pass custom config dict to override

    # Create mesh and add agent (reads from .env automatically)
    mesh = Mesh(mode="autonomous")
    mesh.add(CalculatorAgent)

    try:
        await mesh.start()
        print("✓ Mesh started successfully\n")

        # Example 1: Simple calculation
        print("Example 1: Calculate factorial of 10")
        print("-" * 60)

        results = await mesh.workflow("factorial", [
            {
                "agent": "calculator",
                "task": "Calculate the factorial of 10"
            }
        ])

        result = results[0]
        print(f"Status: {result['status']}")
        print(f"Result: {result.get('output')}")
        print(f"Repairs needed: {result.get('repairs', 0)}")
        print(f"Generated code:\n{result.get('code', 'N/A')}\n")

        await mesh.stop()
        print("✓ Mesh stopped\n")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
