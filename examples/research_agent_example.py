"""
Research Agent Example - Internet Search & Data Extraction

Demonstrates AutoAgent with internet search capabilities.
Agent automatically gets access to web search tools (DuckDuckGo).

Usage:
    python examples/research_agent_example.py
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


class ResearchAgent(AutoAgent):
    """Research assistant with internet access."""
    role = "researcher"
    capabilities = ["research", "web_search", "information_gathering"]
    system_prompt = """
    You are a research assistant with internet access.
    Search the web for information and provide concise summaries.
    Use the 'search' object available in your code:
    - await search.search(query, max_results=5)
    - await search.extract_content(url)
    - await search.search_and_extract(query, num_results=3)
    Store your findings in a variable named 'result'.
    """


async def main():
    """Run research agent example."""
    print("\n" + "="*60)
    print("JarvisCore: Research Agent Example")
    print("="*60)

    # Zero-config: Reads from .env automatically
    # Framework auto-detects: Claude → Azure → Gemini → vLLM
    mesh = Mesh(mode="autonomous")
    mesh.add(ResearchAgent)

    try:
        await mesh.start()
        print("✓ Mesh started with internet search enabled\n")

        print("Example: Research Python asyncio")
        print("-" * 60)

        results = await mesh.workflow("research-asyncio", [
            {
                "agent": "researcher",
                "task": "Search for 'Python asyncio tutorial' and summarize the top 2 results"
            }
        ])

        result = results[0]
        print(f"Status: {result['status']}")
        print(f"Summary:\n{result.get('output')}")
        print(f"\nRepairs needed: {result.get('repairs', 0)}")

        await mesh.stop()
        print("\n✓ Research completed\n")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
