"""
CustomAgent Distributed Mode Example

Demonstrates CustomAgent in distributed mode, which combines:
- P2P network layer (SWIM protocol, ZMQ messaging)
- Workflow orchestration (step execution, dependencies)
- User-controlled execution logic (you write execute_task)

v0.3.2 Features Demonstrated:
- Async Requests (ask_async) - Non-blocking parallel requests to multiple agents
- Load Balancing (strategy="round_robin") - Distribute requests across agent instances

This is ideal for:
- Multi-node deployments with custom logic
- Integrating external frameworks (LangChain, CrewAI, etc.)
- Complex business logic that needs workflow coordination
- Agents that need both peer communication AND workflow support

Usage:
    python examples/customagent_distributed_example.py

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
# LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class LLMClient:
    """LLM client with tool support for CustomAgent."""

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
        """Simple chat."""
        if not self.available:
            return f"[Mock response to: {message[:50]}...]"

        kwargs = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": message}]
        }
        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)
        return response.content[0].text


# ═══════════════════════════════════════════════════════════════════════════════
# CUSTOMAGENT DEFINITIONS FOR DISTRIBUTED MODE
# ═══════════════════════════════════════════════════════════════════════════════

class ContentResearcherAgent(CustomAgent):
    """
    Researcher that finds information using LLM.

    In distributed mode, this agent:
    - Executes tasks via execute_task() (called by workflow engine)
    - Can also communicate with peers via self.peers
    - Benefits from workflow dependencies and orchestration
    """
    role = "content_researcher"
    capabilities = ["research", "information_gathering", "fact_finding"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None

    async def setup(self):
        """Initialize LLM - called automatically by mesh.start()."""
        await super().setup()
        self.llm = LLMClient()
        self._logger.info(f"[{self.role}] Initialized with LLM")

    async def execute_task(self, task):
        """
        REQUIRED: Called by workflow engine for each step.

        Args:
            task: Dict with 'task' key (description) and optional 'context'

        Returns:
            Dict with 'status', 'output', and optionally 'error'
        """
        task_desc = task.get("task", "")
        context = task.get("context", {})

        self._logger.info(f"[{self.role}] Researching: {task_desc[:50]}...")

        # Build prompt with context from previous steps
        prompt = task_desc
        if context:
            prompt = f"Previous context: {context}\n\nTask: {task_desc}"

        # Use LLM for research
        result = self.llm.chat(
            prompt,
            system="You are an expert researcher. Provide thorough, factual information. Be concise but comprehensive."
        )

        return {
            "status": "success",
            "output": result,
            "agent_id": self.agent_id,
            "role": self.role
        }


class ContentWriterAgent(CustomAgent):
    """
    Writer that creates content using LLM.

    Demonstrates:
    - Using context from previous workflow steps
    - Custom execution logic
    - Integration with external LLM
    """
    role = "content_writer"
    capabilities = ["writing", "content_creation", "editing"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None

    async def setup(self):
        await super().setup()
        self.llm = LLMClient()
        self._logger.info(f"[{self.role}] Initialized with LLM")

    async def execute_task(self, task):
        """Write content based on task and context."""
        task_desc = task.get("task", "")
        context = task.get("context", {})

        self._logger.info(f"[{self.role}] Writing: {task_desc[:50]}...")

        # Include research context if available
        prompt = task_desc
        if context:
            prompt = f"Use this research:\n{context}\n\nWriting task: {task_desc}"

        result = self.llm.chat(
            prompt,
            system="You are a professional writer. Create engaging, well-structured content. Use clear language and logical flow."
        )

        return {
            "status": "success",
            "output": result,
            "agent_id": self.agent_id,
            "role": self.role
        }


class ContentReviewerAgent(CustomAgent):
    """
    Reviewer that provides feedback using LLM.

    Demonstrates:
    - Quality control in workflows
    - Peer communication capability (can ask other agents)
    """
    role = "content_reviewer"
    capabilities = ["review", "feedback", "quality_assurance"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None

    async def setup(self):
        await super().setup()
        self.llm = LLMClient()
        self._logger.info(f"[{self.role}] Initialized with LLM")

    async def execute_task(self, task):
        """Review content and provide feedback."""
        task_desc = task.get("task", "")
        context = task.get("context", {})

        self._logger.info(f"[{self.role}] Reviewing: {task_desc[:50]}...")

        prompt = task_desc
        if context:
            prompt = f"Content to review:\n{context}\n\nReview task: {task_desc}"

        result = self.llm.chat(
            prompt,
            system="You are a content reviewer. Provide constructive feedback. Highlight strengths and suggest specific improvements."
        )

        return {
            "status": "success",
            "output": result,
            "agent_id": self.agent_id,
            "role": self.role
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    """Run CustomAgent distributed mode example."""
    print("\n" + "="*70)
    print("JarvisCore: CustomAgent in Distributed Mode")
    print("v0.3.2: Also supports --async and --load-balance demos")
    print("="*70)

    # ─────────────────────────────────────────────────────────────────────────
    # KEY: mode="distributed" gives you BOTH P2P AND workflow orchestration
    # ─────────────────────────────────────────────────────────────────────────
    mesh = Mesh(
        mode="distributed",
        config={
            # P2P Network Configuration
            'bind_host': '127.0.0.1',
            'bind_port': 7965,
            'node_name': 'content-team-node',

            # For multi-node deployment:
            # 'seed_nodes': '192.168.1.10:7965',
        }
    )

    # Add CustomAgents
    mesh.add(ContentResearcherAgent)
    mesh.add(ContentWriterAgent)
    mesh.add(ContentReviewerAgent)

    try:
        await mesh.start()

        print("\n[INFO] Mesh started in DISTRIBUTED mode")
        print(f"  - P2P Coordinator: Active (for cross-node communication)")
        print(f"  - Workflow Engine: Active (for orchestrated execution)")
        print(f"  - Agents: {len(mesh.agents)}")

        # ─────────────────────────────────────────────────────────────────────
        # WORKFLOW EXECUTION with CustomAgents
        # ─────────────────────────────────────────────────────────────────────
        print("\n" + "-"*70)
        print("Content Pipeline: Research → Write → Review")
        print("-"*70)

        results = await mesh.workflow("content-pipeline", [
            {
                "id": "research",
                "agent": "content_researcher",
                "task": "Research the key benefits of microservices architecture for modern applications"
            },
            {
                "id": "write",
                "agent": "content_writer",
                "task": "Write a concise blog post introduction about microservices (2-3 paragraphs)",
                "depends_on": ["research"]
            },
            {
                "id": "review",
                "agent": "content_reviewer",
                "task": "Review the blog post and provide 3 specific improvement suggestions",
                "depends_on": ["write"]
            }
        ])

        # Display results
        print("\n" + "="*70)
        print("PIPELINE RESULTS")
        print("="*70)

        step_names = ["Research", "Writing", "Review"]
        for i, result in enumerate(results):
            print(f"\n{'─'*70}")
            print(f"Step {i+1}: {step_names[i]}")
            print(f"{'─'*70}")
            print(f"Status: {result['status']}")
            if result['status'] == 'success':
                output = result.get('output', '')
                # Truncate long outputs for display
                if len(output) > 500:
                    print(f"Output:\n{output[:500]}...\n[truncated]")
                else:
                    print(f"Output:\n{output}")
            else:
                print(f"Error: {result.get('error')}")

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
# PEER COMMUNICATION IN DISTRIBUTED MODE
# ═══════════════════════════════════════════════════════════════════════════════

async def peer_communication_example():
    """
    Example: Using peer communication in distributed mode.

    CustomAgents in distributed mode can ALSO use peer tools
    for direct agent-to-agent communication:

        class SmartWriterAgent(CustomAgent):
            role = "smart_writer"
            capabilities = ["writing"]

            async def execute_task(self, task):
                # Can ask other agents for help via peers
                if self.peers and "complex" in task.get("task", ""):
                    # Ask researcher for additional info
                    extra_info = await self.peers.as_tool().execute(
                        "ask_peer",
                        {"role": "content_researcher", "question": "Give me more context"}
                    )
                    # Use extra_info in writing...

                return {"status": "success", "output": "..."}

    This gives you the best of both worlds:
    - Workflow orchestration for structured pipelines
    - Peer communication for dynamic collaboration
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# v0.3.2 FEATURES: ASYNC REQUESTS & LOAD BALANCING
# ═══════════════════════════════════════════════════════════════════════════════

async def async_requests_demo():
    """
    Demonstrate v0.3.2 async requests for parallel agent communication.

    ask_async() returns a Future that can be awaited later, enabling:
    - Fire multiple requests in parallel
    - Continue other work while waiting
    - Gather results when needed
    """
    print("\n" + "="*70)
    print("v0.3.2 Feature: Async Requests (ask_async)")
    print("="*70)

    mesh = Mesh(mode="p2p", config={"bind_port": 7966})

    # Add multiple agents
    mesh.add(ContentResearcherAgent)
    mesh.add(ContentWriterAgent)
    mesh.add(ContentReviewerAgent)

    try:
        await mesh.start()

        # Get an agent with peer access
        researcher = next((a for a in mesh.agents if a.role == "content_researcher"), None)
        if not researcher or not researcher.peers:
            print("Peers not available")
            return

        print("\n[Demo] Firing parallel requests to multiple agents...")

        # v0.3.2: ask_async returns a Future - doesn't block!
        future1 = researcher.peers.ask_async(
            "content_writer",
            {"question": "What makes good technical writing?"}
        )
        future2 = researcher.peers.ask_async(
            "content_reviewer",
            {"question": "What are common writing mistakes?"}
        )

        print("[Demo] Requests sent! Doing other work while waiting...")
        await asyncio.sleep(0.1)  # Simulate other work

        # Gather results when ready
        print("[Demo] Gathering results...")
        results = await asyncio.gather(future1, future2, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"  Request {i+1}: Error - {result}")
            else:
                print(f"  Request {i+1}: Got response")

        print("\n[Demo] Async requests complete!")

    finally:
        await mesh.stop()


async def load_balancing_demo():
    """
    Demonstrate v0.3.2 load balancing strategies.

    When multiple agents have the same capability, use strategy parameter:
    - "random" (default): Random selection
    - "round_robin": Distribute evenly across instances
    """
    print("\n" + "="*70)
    print("v0.3.2 Feature: Load Balancing Strategies")
    print("="*70)

    mesh = Mesh(mode="p2p", config={"bind_port": 7967})

    # Add agents
    mesh.add(ContentResearcherAgent)
    mesh.add(ContentWriterAgent)

    try:
        await mesh.start()

        researcher = next((a for a in mesh.agents if a.role == "content_researcher"), None)
        if not researcher or not researcher.peers:
            print("Peers not available")
            return

        print("\n[Demo] Load balancing with strategy='round_robin'")
        print("[Demo] Sending 3 requests to 'writing' capability...")

        # v0.3.2: Use discover_one() with strategy for load balancing
        for i in range(3):
            # round_robin distributes requests evenly across matching peers
            # First, discover which peer to use with the strategy
            target = researcher.peers.discover_one(
                role="content_writer",
                strategy="round_robin"  # v0.3.2: Load balancing
            )

            if target:
                # Then make the request to that specific peer
                response = await researcher.peers.request(
                    target.role,
                    {"question": f"Request #{i+1}"},
                    timeout=10
                )
                print(f"  Request {i+1}: Handled by {target.agent_id[:8]}...")
            else:
                print(f"  Request {i+1}: No peer found")

        print("\n[Demo] Load balancing complete!")
        print("[Demo] In a multi-node setup with multiple writers,")
        print("       round_robin would distribute across all instances.")

    finally:
        await mesh.stop()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--async":
            asyncio.run(async_requests_demo())
        elif sys.argv[1] == "--load-balance":
            asyncio.run(load_balancing_demo())
        else:
            print("Usage:")
            print("  python customagent_distributed_example.py           # Main workflow demo")
            print("  python customagent_distributed_example.py --async   # Async requests demo")
            print("  python customagent_distributed_example.py --load-balance  # Load balancing demo")
    else:
        asyncio.run(main())
