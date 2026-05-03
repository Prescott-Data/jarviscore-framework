"""
JarvisCore Quickstart — your first agent in under 5 minutes.

Demonstrates:
  1. Minimal AutoAgent definition
  2. Mesh() with zero infrastructure config (no Redis needed)
  3. A one-shot workflow task
  4. Multi-tier model routing via complexity=
  5. A short autonomous run() loop

Requirements:
  - One LLM provider configured in .env (Azure, Claude, or Gemini)
  - No Docker, no Redis, no external services required for this example

Usage:
  cp .env.example .env        # fill in your LLM key
  python examples/quickstart.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path so you can run from the examples/ folder
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


# ─────────────────────────────────────────────────────────────────────────────
# 1. Define your agent (5 lines)
# ─────────────────────────────────────────────────────────────────────────────

class SummaryAgent(AutoAgent):
    """
    An agent that summarises text passed to it.

    AutoAgent automatically gets:
    - OODA loop supervision (Observe → Orient → Decide → Act)
    - ValidationLayer (syntax + security checks on generated code)
    - FunctionRegistry (verified functions reused across tasks)
    - Per-task model routing via complexity= hint
    """
    role = "summariser"
    capabilities = ["summarise", "analyse", "explain"]
    system_prompt = """
    You are a concise technical summariser.
    When given text, extract the key points and return a clean bullet-point summary.
    Store your final summary in a variable named 'result'.
    Keep each bullet under 15 words.
    """


class QuickMathAgent(AutoAgent):
    """A simple agent that does calculations — shows coder subagent routing."""
    role = "calculator"
    capabilities = ["math", "compute"]
    system_prompt = """
    You are a precise calculator.
    Write Python code to compute the answer and store it in a variable named 'result'.
    Always show your working as a comment above the final line.
    """


# ─────────────────────────────────────────────────────────────────────────────
# 2. Run workflow tasks
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    print("\n" + "=" * 60)
    print("  JarvisCore Quickstart")
    print("=" * 60)

    # Mesh() with no arguments:
    # - auto-detects available infrastructure at start() time
    # - works without Redis (in-process routing)
    # - works without Athena (no persistent memory)
    # - requires only a configured LLM provider
    mesh = Mesh()
    mesh.add(SummaryAgent)
    mesh.add(QuickMathAgent)

    await mesh.start()

    capabilities = mesh.capabilities
    print(f"\n✓ Mesh started — active capabilities: {', '.join(sorted(capabilities))}")
    redis_note = "distributed" if "redis" in capabilities else "in-process (no Redis needed)"
    print(f"  Routing mode: {redis_note}\n")

    # ── Task 1: Summarise text (researcher subagent, standard complexity) ──
    print("─" * 60)
    print("Task 1: Summarise — standard complexity")
    print("─" * 60)

    results = await mesh.workflow("quickstart-demo", [
        {
            "agent": "summariser",
            "task": (
                "Summarise this in bullet points:\n\n"
                "JarvisCore is an open-source agentic framework built around an OODA loop "
                "(Observe, Orient, Decide, Act). Each agent task is supervised by a Kernel "
                "that selects the right subagent (Coder, Researcher, Communicator, or Browser), "
                "allocates token budgets via ExecutionLeases, manages context isolation through "
                "a ContextManager, and persists state via UnifiedMemory. The FunctionRegistry "
                "caches verified code so agents never rewrite solved problems. The ValidationLayer "
                "enforces syntax, security, and HTTP contract checks before any code runs in sandbox. "
                "Unlike CrewAI or AutoGen, the Mesh auto-detects infrastructure at start() time — "
                "Redis, SWIM, Athena — and activates features without configuration switches."
            ),
            # No complexity= → uses task_model (standard tier)
        }
    ])

    for step_id, output in results.items():
        if output.get("status") == "success":
            print(f"\n✓ Result:\n{output.get('payload', 'No payload')}")
            meta = output.get("metadata", {})
            tokens = meta.get("tokens", {})
            if tokens.get("total"):
                print(f"\n  Tokens used: {tokens['total']:,}")
        else:
            print(f"\n✗ Task failed: {output.get('summary', 'Unknown error')}")

    # ── Task 2: Math calculation (coder subagent, heavy complexity) ──
    print("\n" + "─" * 60)
    print("Task 2: Calculate — heavy complexity tier")
    print("─" * 60)
    print("  (passes complexity='heavy' → routes to TASK_MODEL_HEAVY if configured)")

    results2 = await mesh.workflow("quickstart-math", [
        {
            "agent": "calculator",
            "task": "Calculate the sum of squares of all prime numbers under 50.",
            "complexity": "heavy",  # routes to task_model_heavy if TASK_MODEL_HEAVY is set
        }
    ])

    for step_id, output in results2.items():
        if output.get("status") == "success":
            print(f"\n✓ Result: {output.get('payload', 'No payload')}")
        else:
            print(f"\n✗ Task failed: {output.get('summary', 'Unknown error')}")

    # ── Clean up ──
    await mesh.stop()

    print("\n" + "=" * 60)
    print("  Quickstart complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  • jarviscore init --examples   — copy all example agents")
    print("  • jarviscore check             — validate your full setup")
    print("  • examples/research_agent_example.py — internet search + extraction")
    print("  • examples/multi_agent_workflow.py   — multi-agent pipelines")
    print()


if __name__ == "__main__":
    asyncio.run(main())
