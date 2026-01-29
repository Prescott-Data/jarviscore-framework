"""
ListenerAgent + Cognitive Discovery Example

Demonstrates two v0.3.0 features:

1. ListenerAgent - Handler-based P2P agents (no run() loop needed)
   - on_peer_request() handles incoming requests
   - on_peer_notify() handles broadcast notifications

2. Cognitive Discovery - Dynamic peer awareness for LLMs
   - get_cognitive_context() generates LLM-ready peer descriptions
   - No hardcoded agent names in prompts
   - LLM autonomously decides when to delegate

Usage:
    python examples/listeneragent_cognitive_discovery_example.py

Prerequisites:
    - .env file with CLAUDE_API_KEY (or other LLM provider)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import ListenerAgent


# ═══════════════════════════════════════════════════════════════════════════════
# SPECIALIST AGENT - Responds to requests from other agents
# ═══════════════════════════════════════════════════════════════════════════════

class AnalystAgent(ListenerAgent):
    """
    Specialist agent that handles analysis requests.

    Uses ListenerAgent profile - just implement handlers, no run() loop needed.
    """
    role = "analyst"
    capabilities = ["data_analysis", "statistics", "insights"]
    description = "Analyzes data and provides statistical insights"

    async def on_peer_request(self, msg):
        """Handle incoming analysis requests."""
        query = msg.data.get("question", msg.data.get("query", ""))
        print(f"\n[Analyst] Received request: {query[:50]}...")

        # Simulate analysis (in real usage, this would use an LLM)
        result = {
            "analysis": f"Analysis of '{query}': The data shows positive trends.",
            "confidence": 0.85,
            "insights": ["Trend is upward", "Growth rate: 15%", "Recommendation: Continue"]
        }

        print(f"[Analyst] Sending response with {len(result['insights'])} insights")
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# COORDINATOR AGENT - Uses LLM with cognitive discovery
# ═══════════════════════════════════════════════════════════════════════════════

class CoordinatorAgent(ListenerAgent):
    """
    Coordinator agent that uses LLM with dynamic peer discovery.

    Key pattern:
    1. Uses get_cognitive_context() to learn about available peers
    2. Injects peer context into LLM system prompt
    3. LLM decides when to delegate to specialists
    """
    role = "coordinator"
    capabilities = ["coordination", "delegation", "chat"]
    description = "Coordinates tasks and delegates to specialists"

    async def setup(self):
        await super().setup()
        self.llm = self._create_llm_client()

    def _create_llm_client(self):
        """Create LLM client with fallback to mock."""
        try:
            from anthropic import Anthropic
            from jarviscore.config import settings
            import os

            api_key = settings.claude_api_key or os.environ.get("CLAUDE_API_KEY")
            if not api_key:
                raise RuntimeError("No API key")

            # Check for custom endpoint (e.g., Azure-hosted Claude)
            endpoint = settings.claude_endpoint or os.environ.get("CLAUDE_ENDPOINT")
            model = settings.claude_model or os.environ.get("CLAUDE_MODEL") or "claude-sonnet-4-20250514"

            if endpoint:
                client = Anthropic(api_key=api_key, base_url=endpoint)
            else:
                client = Anthropic(api_key=api_key)

            # Test the API key with a minimal request
            try:
                client.messages.create(
                    model=model,
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hi"}]
                )
            except Exception as e:
                raise RuntimeError(f"API key validation failed: {e}")

            print(f"[Coordinator] LLM initialized: {model}")
            return {"client": client, "model": model, "available": True}
        except Exception as e:
            print(f"[Coordinator] LLM not available ({e}), using mock responses")
            return {"available": False}

    def _build_dynamic_prompt(self, base_prompt: str) -> str:
        """
        Build system prompt with dynamic peer awareness.

        THIS IS THE KEY PATTERN - the LLM learns about peers dynamically!
        """
        if not self.peers:
            return base_prompt

        # Use get_cognitive_context() for dynamic peer discovery
        peer_context = self.peers.get_cognitive_context(
            format="markdown",
            include_capabilities=True,
            include_description=True,
            tool_name="ask_peer"
        )

        return f"{base_prompt}\n\n{peer_context}"

    async def process_query(self, user_query: str) -> str:
        """
        Process a user query using LLM with peer awareness.

        The LLM sees available peers and can decide to delegate.
        """
        base_prompt = """You are a coordinator assistant that delegates tasks to specialists.

IMPORTANT: You MUST use the ask_peer tool to delegate to specialists. You cannot perform analysis yourself.

When a user asks for data analysis, statistics, or insights:
1. Use the ask_peer tool with role="analyst"
2. Pass their question to the analyst
3. Report the analyst's findings

Never try to do analysis yourself - always delegate to the analyst."""

        # Build prompt with dynamic peer discovery
        system_prompt = self._build_dynamic_prompt(base_prompt)

        print(f"\n[Coordinator] System prompt includes peer context:")
        print("-" * 40)
        # Show just the peer context part
        if "AVAILABLE MESH PEERS" in system_prompt:
            peer_section = system_prompt.split("AVAILABLE MESH PEERS")[1][:200]
            print(f"...AVAILABLE MESH PEERS{peer_section}...")
        print("-" * 40)

        # Check if LLM is available
        if not self.llm.get("available"):
            # Mock: simulate LLM deciding to delegate
            if any(word in user_query.lower() for word in ["analyze", "analysis", "statistics", "data"]):
                print("[Coordinator] Mock LLM decides to delegate to analyst")
                response = await self.peers.request(
                    "analyst",
                    {"question": user_query},
                    timeout=30
                )
                return f"Based on the analyst's findings: {response.get('analysis', 'No response')}"
            return f"I can help with: {user_query}"

        # Real LLM call with tools
        tools = self._get_tools()
        messages = [{"role": "user", "content": user_query}]

        print(f"[Coordinator] Calling LLM with {len(tools)} tools: {[t['name'] for t in tools]}")

        response = self.llm["client"].messages.create(
            model=self.llm["model"],
            max_tokens=1024,
            system=system_prompt,
            messages=messages,
            tools=tools
        )

        print(f"[Coordinator] LLM stop_reason: {response.stop_reason}")
        print(f"[Coordinator] Response blocks: {[b.type for b in response.content]}")

        # Handle tool use - check for tool_use FIRST (prioritize over text)
        tool_use_block = None
        text_content = None

        for block in response.content:
            if block.type == "tool_use" and block.name == "ask_peer":
                tool_use_block = block
            elif hasattr(block, 'text'):
                text_content = block.text

        # If there's a tool use, execute it
        if tool_use_block:
            print(f"[Coordinator] LLM decided to use ask_peer tool")
            peer_response = await self._execute_peer_tool(tool_use_block.input)

            # Continue conversation with tool result
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,
                    "content": str(peer_response)
                }]
            })

            final_response = self.llm["client"].messages.create(
                model=self.llm["model"],
                max_tokens=1024,
                system=system_prompt,
                messages=messages
            )

            for final_block in final_response.content:
                if hasattr(final_block, 'text'):
                    return final_block.text

        # No tool use, return text content
        if text_content:
            return text_content

        return "I processed your request."

    def _get_tools(self) -> list:
        """Get tools for LLM, including peer tools."""
        return [{
            "name": "ask_peer",
            "description": "Ask a specialist agent for help. Use this to delegate tasks to experts.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Role of the agent to ask (e.g., 'analyst')"
                    },
                    "question": {
                        "type": "string",
                        "description": "The question or task for the specialist"
                    }
                },
                "required": ["role", "question"]
            }
        }]

    async def _execute_peer_tool(self, args: dict) -> dict:
        """Execute ask_peer tool."""
        role = args.get("role", "")
        question = args.get("question", "")

        print(f"[Coordinator] Asking {role}: {question[:50]}...")

        response = await self.peers.request(
            role,
            {"question": question},
            timeout=30
        )

        return response

    async def on_peer_request(self, msg):
        """Handle incoming peer requests (for workflow compatibility)."""
        query = msg.data.get("query", msg.data.get("question", ""))
        result = await self.process_query(query)
        return {"response": result}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN - Demonstrate cognitive discovery
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("LLM Cognitive Discovery Example")
    print("=" * 60)

    # Create mesh with both agents
    mesh = Mesh(mode="p2p", config={"bind_port": 7960})

    analyst = mesh.add(AnalystAgent())
    coordinator = mesh.add(CoordinatorAgent())

    await mesh.start()

    print(f"\n[Setup] Mesh started with agents:")
    print(f"  - {analyst.role}: {analyst.capabilities}")
    print(f"  - {coordinator.role}: {coordinator.capabilities}")

    # Start analyst listener in background
    analyst_task = asyncio.create_task(analyst.run())

    # Give time for setup
    await asyncio.sleep(0.5)

    # Show cognitive context that LLM will see
    print("\n" + "=" * 60)
    print("COGNITIVE CONTEXT (what LLM sees about peers)")
    print("=" * 60)
    context = coordinator.peers.get_cognitive_context()
    print(context)

    # Test queries - one that should trigger delegation, one that shouldn't
    test_queries = [
        "Please analyze the Q4 sales data and give me insights",
        "What time is it?",
    ]

    print("\n" + "=" * 60)
    print("PROCESSING QUERIES")
    print("=" * 60)

    for query in test_queries:
        print(f"\n>>> User: {query}")
        response = await coordinator.process_query(query)
        print(f"<<< Coordinator: {response}")

    # Cleanup
    analyst.request_shutdown()
    analyst_task.cancel()
    try:
        await analyst_task
    except asyncio.CancelledError:
        pass

    await mesh.stop()
    print("\n[Done] Example completed!")


if __name__ == "__main__":
    asyncio.run(main())
