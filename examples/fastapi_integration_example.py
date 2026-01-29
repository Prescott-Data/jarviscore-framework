"""
FastAPI Integration Example (v0.3.0)

Demonstrates JarvisLifespan for 3-line FastAPI integration with autonomous agents.

Features shown:
    1. JarvisLifespan - Automatic agent lifecycle management
    2. ListenerAgent - API-first agents with on_peer_request handlers
    3. Cognitive Discovery - get_cognitive_context() for LLM awareness
    4. Autonomous Agents - Each agent has MESH as a TOOL, LLM decides when to delegate

Real-World Flow:
    HTTP Request → Agent A (with LLM) → LLM sees peers as tools
    → LLM decides to ask Agent B → Agent B responds → HTTP Response

Usage:
    # Start FastAPI server with all agents
    python examples/fastapi_integration_example.py

    # Test the endpoint
    curl -X POST http://localhost:8000/chat \
        -H "Content-Type: application/json" \
        -d '{"message": "Analyze the Q4 sales trends"}'

    # Optional: Start a standalone agent that joins the mesh (in another terminal)
    python examples/fastapi_integration_example.py --join-as scout

Prerequisites:
    - pip install fastapi uvicorn
    - .env file with CLAUDE_API_KEY
"""
import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    print("FastAPI not installed. Run: pip install fastapi uvicorn")

from jarviscore.profiles import ListenerAgent


# ═══════════════════════════════════════════════════════════════════════════════
# LLM-POWERED AGENT BASE - Each agent can discover and delegate
# ═══════════════════════════════════════════════════════════════════════════════

class LLMAgent(ListenerAgent):
    """
    Base for LLM-powered agents that can discover and delegate to peers.

    KEY PATTERN: The mesh is a TOOL for the LLM.
    - get_cognitive_context() tells LLM who's available
    - ask_peer tool lets LLM delegate to specialists
    - Each agent is autonomous - no central coordinator needed
    """

    async def setup(self):
        await super().setup()
        self.llm = self._create_llm_client()

    def _create_llm_client(self):
        """Create LLM client."""
        try:
            from anthropic import Anthropic
            from jarviscore.config import settings

            api_key = settings.claude_api_key or os.environ.get("CLAUDE_API_KEY")
            if not api_key:
                return None

            endpoint = settings.claude_endpoint or os.environ.get("CLAUDE_ENDPOINT")
            model = settings.claude_model or os.environ.get("CLAUDE_MODEL") or "claude-sonnet-4-20250514"

            client = Anthropic(api_key=api_key, base_url=endpoint) if endpoint else Anthropic(api_key=api_key)

            # Validate
            client.messages.create(model=model, max_tokens=10, messages=[{"role": "user", "content": "Hi"}])
            print(f"[{self.role}] LLM initialized: {model}")
            return {"client": client, "model": model}
        except Exception as e:
            print(f"[{self.role}] LLM not available: {e}")
            return None

    def _get_tools(self):
        """Get tools for LLM - includes ask_peer for mesh communication."""
        return [{
            "name": "ask_peer",
            "description": "Ask another agent in the mesh for help. Use this to delegate tasks to specialists.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "role": {"type": "string", "description": "Role of the agent to ask (e.g., 'analyst', 'researcher')"},
                    "question": {"type": "string", "description": "The question or task for that agent"}
                },
                "required": ["role", "question"]
            }
        }]

    async def _ask_peer(self, role: str, question: str) -> dict:
        """Execute ask_peer tool - send request to another agent."""
        print(f"[{self.role}] Asking {role}: {question[:50]}...")
        response = await self.peers.request(role, {"question": question}, timeout=30)
        print(f"[{self.role}] Got response from {role}")
        return response

    async def chat(self, message: str) -> dict:
        """
        Process a message with LLM that can discover and delegate to peers.

        This is the CORE PATTERN:
        1. Build system prompt with WHO I AM + WHO ELSE IS AVAILABLE
        2. LLM sees available peers as potential helpers
        3. LLM decides whether to handle directly or delegate
        """
        if not self.llm:
            return await self._chat_mock(message)

        # DYNAMIC DISCOVERY: Tell LLM who it is and who else is available
        peer_context = self.peers.get_cognitive_context() if self.peers else ""

        system_prompt = f"""{self.system_prompt}

{peer_context}"""

        print(f"\n[{self.role}] Processing: {message[:50]}...")

        response = self.llm["client"].messages.create(
            model=self.llm["model"],
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": message}],
            tools=self._get_tools()
        )

        # Handle tool use
        tool_use_block = None
        text_content = None

        for block in response.content:
            if block.type == "tool_use" and block.name == "ask_peer":
                tool_use_block = block
            elif hasattr(block, 'text'):
                text_content = block.text

        if tool_use_block:
            role = tool_use_block.input.get("role")
            question = tool_use_block.input.get("question")

            peer_response = await self._ask_peer(role, question)

            # Continue with tool result
            messages = [{"role": "user", "content": message}]
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use_block.id, "content": str(peer_response)}]
            })

            final = self.llm["client"].messages.create(
                model=self.llm["model"],
                max_tokens=1024,
                system=system_prompt,
                messages=messages
            )

            for block in final.content:
                if hasattr(block, 'text'):
                    return {"response": block.text,
                     "delegated_to": role, "peer_data": peer_response}

        return {"response": text_content or "Processed.", "delegated_to": None}

    async def _chat_mock(self, message: str) -> dict:
        """Mock when LLM unavailable - for testing."""
        return {"response": f"[{self.role}] Received: {message}", "delegated_to": None}

    # System prompt - override in subclasses
    system_prompt = "You are a helpful agent."


# ═══════════════════════════════════════════════════════════════════════════════
# AUTONOMOUS AGENTS - Each has LLM + mesh discovery
# ═══════════════════════════════════════════════════════════════════════════════

class AssistantAgent(LLMAgent):
    """
    General assistant that can delegate to specialists.

    When user asks something outside its expertise, it discovers
    and delegates to the appropriate specialist via the mesh.
    """
    role = "assistant"
    capabilities = ["chat", "general_help", "delegation"]
    description = "General assistant that delegates specialized tasks to experts"

    system_prompt = """You are a helpful assistant. You can answer general questions directly.

For specialized tasks, you have access to other agents via the ask_peer tool:
- For data analysis, statistics, or insights → ask the "analyst" agent
- For research or information gathering → ask the "researcher" agent

Use ask_peer when the task requires specialized expertise. Be helpful and concise."""

    async def on_peer_request(self, msg):
        """Handle requests from other agents."""
        return await self.chat(msg.data.get("question", ""))


class AnalystAgent(LLMAgent):
    """
    Data analysis specialist with LLM.

    Can also discover and ask other agents if needed.
    """
    role = "analyst"
    capabilities = ["data_analysis", "statistics", "insights", "reporting"]
    description = "Expert data analyst for statistics and insights"

    system_prompt = """You are an expert data analyst. You specialize in:
- Statistical analysis
- Data insights and trends
- Business metrics and KPIs
- Data visualization recommendations

Provide clear, actionable insights. If you need research data, you can ask the "researcher" agent."""

    async def on_peer_request(self, msg):
        """Handle analysis requests."""
        question = msg.data.get("question", "")
        print(f"\n[Analyst] Received: {question[:50]}...")

        # Analyst can use LLM to generate analysis
        if self.llm:
            response = self.llm["client"].messages.create(
                model=self.llm["model"],
                max_tokens=512,
                system=self.system_prompt,
                messages=[{"role": "user", "content": f"Analyze this request and provide insights: {question}"}]
            )
            for block in response.content:
                if hasattr(block, 'text'):
                    return {"analysis": block.text, "confidence": 0.9}

        # Fallback
        return {
            "analysis": f"Analysis of: {question}",
            "findings": ["Revenue up 15%", "Costs down 8%", "Growth trend positive"],
            "confidence": 0.85
        }


class ResearcherAgent(LLMAgent):
    """
    Research specialist with LLM.

    Can also discover and ask other agents if needed.
    """
    role = "researcher"
    capabilities = ["research", "web_search", "fact_checking", "information_gathering"]
    description = "Research specialist for gathering and verifying information"

    system_prompt = """You are an expert researcher. You specialize in:
- Information gathering
- Fact checking
- Market research
- Competitive analysis

Provide well-sourced, accurate information. If you need data analysis, you can ask the "analyst" agent."""

    async def on_peer_request(self, msg):
        """Handle research requests."""
        question = msg.data.get("question", "")
        print(f"\n[Researcher] Received: {question[:50]}...")

        if self.llm:
            response = self.llm["client"].messages.create(
                model=self.llm["model"],
                max_tokens=512,
                system=self.system_prompt,
                messages=[{"role": "user", "content": f"Research this topic: {question}"}]
            )
            for block in response.content:
                if hasattr(block, 'text'):
                    return {"research": block.text, "sources": ["Internal analysis"]}

        return {
            "research": f"Research on: {question}",
            "sources": ["Industry Report 2024", "Market Analysis"],
            "summary": "Research findings compiled"
        }


# ═══════════════════════════════════════════════════════════════════════════════
# STANDALONE AGENT - Cloud Deployment Pattern 
# ═══════════════════════════════════════════════════════════════════════════════

class ScoutAgent(LLMAgent):
    """
    Standalone agent that can join an existing mesh from anywhere.

    This demonstrates the CLOUD DEPLOYMENT pattern:
    - Agent runs independently (different process, container, or machine)
    - Uses join_mesh() to self-register with an existing mesh
    - Automatically becomes visible to all other agents
    - Can discover and communicate with mesh peers
    """
    role = "scout"
    capabilities = ["scouting", "reconnaissance", "market_intel", "trend_detection"]
    description = "Scout agent that gathers market intelligence and detects trends"

    system_prompt = """You are a scout agent specializing in:
- Market intelligence gathering
- Trend detection and early signals
- Competitive reconnaissance
- Opportunity identification

You can ask the "analyst" for data analysis or "researcher" for deep research."""

    async def on_peer_request(self, msg):
        """Handle scouting requests."""
        question = msg.data.get("question", "")
        print(f"\n[Scout] Received: {question[:50]}...")

        if self.llm:
            response = self.llm["client"].messages.create(
                model=self.llm["model"],
                max_tokens=512,
                system=self.system_prompt,
                messages=[{"role": "user", "content": f"Scout this: {question}"}]
            )
            for block in response.content:
                if hasattr(block, 'text'):
                    return {"intel": block.text, "confidence": 0.85}

        return {
            "intel": f"Scouting report on: {question}",
            "signals": ["Emerging trend detected", "Competitor activity noted"],
            "confidence": 0.8
        }


async def run_standalone_scout(mesh_endpoint: str):
    """
    Run scout as a standalone agent that joins an existing mesh.

    This demonstrates the TRUE CLOUD DEPLOYMENT pattern:
    - Scout runs in a SEPARATE PROCESS from the main mesh
    - Uses join_mesh() to self-register with the existing mesh
    - Automatically discovers all other agents
    - Can communicate with mesh peers via P2P messaging

    Usage:
        Terminal 1: python examples/fastapi_integration_example.py  (starts FastAPI + mesh)
        Terminal 2: python examples/fastapi_integration_example.py --join-as scout
    """
    print("=" * 60)
    print("STANDALONE SCOUT - Cloud Deployment Demo")
    print("=" * 60)
    print(f"\nJoining existing mesh at {mesh_endpoint}...")

    # Create standalone scout agent
    scout = ScoutAgent()

    try:
        # Join the existing mesh 
        await scout.join_mesh(seed_nodes=mesh_endpoint)
        print(f"Successfully joined mesh!")
        print(f"  - is_mesh_connected: {scout.is_mesh_connected}")

        # Wait for capability exchange to complete
        await asyncio.sleep(2)

        # Show what scout can see
        print("\n=== CAPABILITY DISCOVERY ===")
        if scout.peers:
            peers = scout.peers.list_peers()
            print(f"Scout discovered {len(peers)} peer(s):")
            for p in peers:
                print(f"  - {p['role']}: {p['capabilities']}")

            # Show cognitive context (what LLM would see)
            print("\n=== COGNITIVE CONTEXT (for LLM) ===")
            context = scout.peers.get_cognitive_context(format="text")
            print(context)

            # Show capability map from coordinator
            if scout._standalone_p2p:
                print("\n=== FULL CAPABILITY MAP ===")
                cap_map = scout._standalone_p2p._capability_map
                for cap, agents in cap_map.items():
                    print(f"  {cap}: {agents}")

        # Run scout's event loop - handles incoming requests
        print("\n=== SCOUT RUNNING ===")
        print("Scout is now active and can receive requests from other agents.")
        print("Press Ctrl+C to leave mesh and exit.")

        # Start scout's run loop
        scout_task = asyncio.create_task(scout.run())

        try:
            # Keep running until interrupted
            while not scout.shutdown_requested:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\n\nShutdown requested...")
        finally:
            scout.request_shutdown()
            scout_task.cancel()
            try:
                await scout_task
            except asyncio.CancelledError:
                pass

    except Exception as e:
        print(f"Error joining mesh: {e}")
        raise
    finally:
        # Gracefully leave the mesh
        print("\n=== LEAVING MESH ===")
        await scout.leave_mesh()
        print("Scout has left the mesh.")

    print("\n" + "=" * 60)
    print("Standalone scout demo complete!")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI APPLICATION - Minimal code with JarvisLifespan
# ═══════════════════════════════════════════════════════════════════════════════

def create_app():
    """Create FastAPI app - 3 lines of JarvisCore integration."""
    from jarviscore.integrations import JarvisLifespan

    # Create autonomous agents
    agents = [AssistantAgent(), AnalystAgent(), ResearcherAgent()]

    # ONE LINE: JarvisLifespan handles everything
    app = FastAPI(
        title="Autonomous Agents Demo",
        lifespan=JarvisLifespan(agents, mode="p2p", bind_port=7980)
    )

    @app.get("/")
    async def root():
        return {"status": "ok", "agents": ["assistant", "analyst", "researcher"]}

    @app.get("/agents")
    async def list_agents(request: Request):
        """Show what each agent can see about others."""
        result = {}
        for role, agent in request.app.state.jarvis_agents.items():
            if agent.peers:
                result[role] = {
                    "can_see": [p["role"] for p in agent.peers.list_peers()],
                    "cognitive_context": agent.peers.get_cognitive_context(format="text")
                }
        return result

    @app.post("/chat")
    async def chat(request: Request):
        """
        Chat endpoint - assistant uses mesh to discover and delegate.

        The assistant's LLM:
        1. Sees other agents via get_cognitive_context()
        2. Decides if it needs to delegate
        3. Uses ask_peer tool to communicate
        """
        body = await request.json()
        message = body.get("message", "")

        assistant = request.app.state.jarvis_agents.get("assistant")
        if not assistant:
            return JSONResponse(status_code=503, content={"error": "Assistant not available"})

        result = await assistant.chat(message)
        return {"message": message, **result}

    @app.post("/ask/{agent_role}")
    async def ask_agent(agent_role: str, request: Request):
        """Ask a specific agent directly."""
        body = await request.json()
        message = body.get("message", "")

        agent = request.app.state.jarvis_agents.get(agent_role)
        if not agent:
            return JSONResponse(status_code=404, content={"error": f"Agent '{agent_role}' not found"})

        result = await agent.chat(message)
        return {"agent": agent_role, "message": message, **result}

    return app


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN - Supports both FastAPI server and standalone agent modes
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Unified DX Example - Autonomous Agents with Mesh Discovery"
    )
    parser.add_argument(
        "--join-as",
        type=str,
        choices=["scout"],
        help="Run as standalone agent that joins existing mesh (e.g., --join-as scout)"
    )
    parser.add_argument(
        "--mesh-endpoint",
        type=str,
        default="127.0.0.1:7980",
        help="Mesh endpoint to join (default: 127.0.0.1:7980)"
    )

    args = parser.parse_args()

    # MODE 2: Standalone agent joins existing mesh
    if args.join_as:
        print(f"Starting {args.join_as} as standalone agent...")
        asyncio.run(run_standalone_scout(args.mesh_endpoint))
        return

    # MODE 1: FastAPI server with all agents
    if not FASTAPI_AVAILABLE:
        print("Install FastAPI: pip install fastapi uvicorn")
        return

    print("=" * 60)
    print("Autonomous Agents with Mesh Discovery")
    print("=" * 60)
    print("\n - FastAPI Integration:")
    print("  - JarvisLifespan for one-line integration")
    print("  - ListenerAgent with on_peer_request handlers")
    print("  - Cognitive discovery via get_cognitive_context()")
    print("\n - Cloud Deployment:")
    print("  - Each agent has MESH as a TOOL")
    print("  - LLM decides when to delegate autonomously")
    print("  - Standalone agents can join with --join-as flag")
    print("\nEndpoints:")
    print("  GET  /agents      - Show what each agent sees")
    print("  POST /chat        - Chat with assistant (may delegate)")
    print("  POST /ask/{role}  - Ask specific agent directly")
    print("\nTest:")
    print('  curl -X POST http://localhost:8000/chat \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -d \'{"message": "Analyze Q4 sales trends"}\'')
    print("\nCloud Deployment (in another terminal):")
    print("  python examples/fastapi_integration_example.py --join-as scout")
    print("=" * 60)

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
