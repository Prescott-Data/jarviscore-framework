"""
CustomAgent P2P Mode Example

Demonstrates CustomAgent in pure P2P mode where:
- Agents run continuously in their own run() loops
- Agents communicate directly via peer tools (ask_peer, broadcast_update)
- No centralized workflow orchestration
- Agents self-coordinate and make their own decisions

This is ideal for:
- Autonomous agent swarms
- Real-time collaborative systems
- Event-driven architectures
- Agents that need to run indefinitely

Usage:
    python examples/customagent_p2p_example.py

Prerequisites:
    - .env file with LLM API key (CLAUDE_API_KEY, etc.)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import CustomAgent


# ═══════════════════════════════════════════════════════════════════════════════
# LLM CLIENT (for real LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════

class SimpleLLMClient:
    """Simple LLM client wrapper."""

    def __init__(self):
        try:
            from anthropic import Anthropic
            from jarviscore.config import settings

            api_key = settings.claude_api_key
            if not api_key:
                raise RuntimeError("No API key")

            endpoint = settings.claude_endpoint
            if endpoint:
                self.client = Anthropic(api_key=api_key, base_url=endpoint)
            else:
                self.client = Anthropic(api_key=api_key)

            self.model = settings.claude_model or "claude-sonnet-4-20250514"
            self.available = True
        except Exception as e:
            print(f"[LLM] Not available: {e}")
            self.available = False

    def chat(self, message: str, system: str = None) -> str:
        """Simple chat without tools."""
        if not self.available:
            return f"[Mock response to: {message[:50]}...]"

        kwargs = {
            "model": self.model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": message}]
        }
        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)
        return response.content[0].text


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMAGENT DEFINITIONS FOR P2P MODE
# ═══════════════════════════════════════════════════════════════════════════════

class ResearcherAgent(CustomAgent):
    """
    Researcher agent that responds to queries from peers.

    In P2P mode, this agent:
    1. Runs continuously in its run() loop
    2. Listens for incoming peer requests
    3. Processes requests using LLM
    4. Sends responses back to requesters
    """
    role = "researcher"
    capabilities = ["research", "analysis", "fact_checking"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None
        self.queries_handled = 0

    async def setup(self):
        """Initialize LLM client."""
        await super().setup()
        self.llm = SimpleLLMClient()
        self._logger.info(f"[{self.role}] Ready to receive research queries")

    async def run(self):
        """
        REQUIRED FOR P2P MODE: Continuous run loop.

        This is the main difference from autonomous/distributed mode.
        The agent runs indefinitely, processing incoming messages.
        """
        self._logger.info(f"[{self.role}] Starting P2P run loop...")

        while not self.shutdown_requested:
            # Check for incoming peer messages
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)

                if msg and msg.is_request:
                    # Process the research query
                    query = msg.data.get("question", msg.data.get("query", ""))
                    self._logger.info(f"[{self.role}] Received query: {query[:50]}...")

                    # Use LLM to generate response
                    response = self.llm.chat(
                        query,
                        system="You are a research expert. Provide concise, factual answers."
                    )

                    # Send response back to requester
                    await self.peers.respond(msg, {"response": response})
                    self.queries_handled += 1
                    self._logger.info(f"[{self.role}] Responded (total: {self.queries_handled})")
            else:
                await asyncio.sleep(0.1)

    async def execute_task(self, task):
        """
        Required by Agent base class (@abstractmethod).

        Why this exists even in P2P mode:
        1. Agent.execute_task() is declared as @abstractmethod in core/agent.py
        2. Python requires ALL abstract methods to be implemented, or you get:
           TypeError: Can't instantiate abstract class ResearcherAgent
           with abstract method execute_task
        3. This provides a consistent interface - even P2P agents CAN be called
           via execute_task() if needed (e.g., hybrid mode, testing)

        In P2P mode, your main logic lives in run(), not here.
        """
        return {"status": "success", "note": "This agent uses run() for P2P mode"}


class AssistantAgent(CustomAgent):
    """
    Assistant agent that coordinates with other agents.

    In P2P mode, this agent:
    1. Runs in its own loop
    2. Can ask other agents for help via ask_peer
    3. Makes decisions about when to delegate
    """
    role = "assistant"
    capabilities = ["coordination", "chat", "delegation"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None
        self.conversations = []

    async def setup(self):
        """Initialize LLM client."""
        await super().setup()
        self.llm = SimpleLLMClient()
        self._logger.info(f"[{self.role}] Ready to assist and coordinate")

    async def ask_researcher(self, question: str) -> str:
        """Ask the researcher agent for help."""
        if not self.peers:
            return "No peers available"

        result = await self.peers.as_tool().execute(
            "ask_peer",
            {"role": "researcher", "question": question}
        )
        return result

    async def process_user_input(self, user_input: str) -> str:
        """
        Process user input, potentially delegating to researcher.

        This demonstrates the P2P communication pattern.
        """
        self._logger.info(f"[{self.role}] Processing: {user_input[:50]}...")

        # Decide if we need research help
        needs_research = any(word in user_input.lower() for word in
                           ["research", "analyze", "fact", "data", "statistics", "study"])

        if needs_research:
            self._logger.info(f"[{self.role}] Delegating to researcher...")
            research_result = await self.ask_researcher(user_input)

            # Synthesize final response
            final_response = self.llm.chat(
                f"Based on this research: {research_result}\n\nProvide a helpful summary.",
                system="You are a helpful assistant. Summarize research findings clearly."
            )
            return final_response
        else:
            # Handle directly
            return self.llm.chat(
                user_input,
                system="You are a helpful assistant. Be concise and friendly."
            )

    async def run(self):
        """
        REQUIRED FOR P2P MODE: Continuous run loop.

        In a real application, this might listen for:
        - WebSocket connections
        - HTTP requests
        - Message queue events
        - Other peer requests
        """
        self._logger.info(f"[{self.role}] Starting P2P run loop...")

        while not self.shutdown_requested:
            # In P2P mode, the assistant could:
            # 1. Listen for external triggers (API, websocket, etc.)
            # 2. Respond to peer messages
            # 3. Proactively perform tasks

            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("query", "")
                    response = await self.process_user_input(query)
                    await self.peers.respond(msg, {"response": response})
            else:
                await asyncio.sleep(0.1)

    async def execute_task(self, task):
        """
        Required by Agent base class (@abstractmethod).

        Same as ResearcherAgent - must implement to satisfy Python's
        abstract method requirement. See ResearcherAgent.execute_task
        for detailed explanation.
        """
        return {"status": "success", "note": "This agent uses run() for P2P mode"}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    """Run CustomAgent P2P mode example."""
    print("\n" + "="*70)
    print("JarvisCore: CustomAgent in P2P Mode")
    print("="*70)

    # ─────────────────────────────────────────────────────────────────────────
    # KEY DIFFERENCE: mode="p2p" - No workflow engine, agents run continuously
    # ─────────────────────────────────────────────────────────────────────────
    mesh = Mesh(
        mode="p2p",  # P2P only - no workflow orchestration
        config={
            'bind_host': '127.0.0.1',
            'bind_port': 7960,
            'node_name': 'p2p-demo-node',
        }
    )

    researcher = mesh.add(ResearcherAgent)
    assistant = mesh.add(AssistantAgent)

    try:
        await mesh.start()

        print("\n[INFO] Mesh started in P2P mode")
        print(f"  - P2P Coordinator: Active")
        print(f"  - Workflow Engine: NOT available (use run_forever instead)")
        print(f"  - Agents: {len(mesh.agents)}")

        # In P2P mode, agents communicate directly
        # Let's demonstrate by having the assistant ask the researcher

        print("\n" + "-"*70)
        print("Demonstrating P2P Agent Communication")
        print("-"*70)

        # Give agents time to initialize their peer connections
        await asyncio.sleep(0.5)

        # Start researcher's run loop in background
        researcher_task = asyncio.create_task(researcher.run())

        # Give researcher time to start listening
        await asyncio.sleep(0.3)

        # Simulate user queries that the assistant processes
        test_queries = [
            "Research the benefits of renewable energy",
            "Hello, how are you?",  # This won't be delegated
            "Analyze the latest trends in AI development",
        ]

        for query in test_queries:
            print(f"\n[User] {query}")
            response = await assistant.process_user_input(query)
            print(f"[Assistant] {response[:200]}...")

        # Show statistics
        print("\n" + "="*70)
        print("P2P Session Statistics")
        print("="*70)
        print(f"  Researcher queries handled: {researcher.queries_handled}")

        # Cleanup
        researcher.request_shutdown()
        researcher_task.cancel()
        try:
            await researcher_task
        except asyncio.CancelledError:
            pass

        await mesh.stop()
        print("\n[INFO] P2P mesh stopped")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


# ═══════════════════════════════════════════════════════════════════════════════
# LONG-RUNNING P2P EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════════

async def run_forever_example():
    """
    Example: Running P2P agents indefinitely.

    Use mesh.run_forever() to keep all agents running:

        mesh = Mesh(mode="p2p", config={...})
        mesh.add(ResearcherAgent)
        mesh.add(AssistantAgent)

        await mesh.start()
        await mesh.run_forever()  # Blocks until shutdown signal

    Agents will run their run() loops continuously until:
    - SIGINT (Ctrl+C)
    - SIGTERM
    - Programmatic shutdown
    """
    pass


if __name__ == "__main__":
    asyncio.run(main())
