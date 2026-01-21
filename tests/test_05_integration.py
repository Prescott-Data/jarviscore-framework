"""
Test 5: Integration Test - Multiple LLM-Powered Agents in Mesh

Demonstrates the COMPLETE developer experience with MULTIPLE agents,
all being FULL MESH PARTICIPANTS that can both SEND and RECEIVE.

KEY CONCEPTS:
    1. Every agent is LLM-powered
    2. Every agent can SEND requests (via ask_peer)
    3. Every agent can RECEIVE requests (via run() loop)
    4. Every agent has get_tools() with peer tools
    5. The role defines what they're GOOD at, not communication direction

REAL-WORLD SCENARIO:
    - Analyst: Good at analysis, but might ask researcher for data
    - Researcher: Good at research, but might ask analyst to interpret
    - Assistant: Good at chat/search, coordinates between specialists

    All three can talk to each other in any direction!

FILE STRUCTURE:
    project/
    ├── main.py              # Entry file (mesh setup)
    ├── agents/
    │   ├── analyst.py       # LLM agent - good at analysis
    │   ├── researcher.py    # LLM agent - good at research
    │   └── assistant.py     # LLM agent - good at chat/search
    └── ...
"""
import asyncio
import sys
import pytest
sys.path.insert(0, '.')

from jarviscore.core.agent import Agent
from jarviscore.core.mesh import Mesh
from jarviscore.p2p.peer_client import PeerClient


# ═══════════════════════════════════════════════════════════════════════════════
# AGENTS - All follow the SAME pattern, different capabilities
# ═══════════════════════════════════════════════════════════════════════════════

class Analyst(Agent):
    """
    Analyst - Good at analysis, can also ask other peers.

    This agent might receive an analysis request, realize it needs
    more data, and ask the researcher for help.
    """
    role = "analyst"
    capabilities = ["analysis", "synthesis", "reporting"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.analyses_count = 0
        self.requests_received = []
        self.requests_sent = []

    def analyze(self, data: str) -> dict:
        """Core capability - analyze data."""
        self.analyses_count += 1
        return {
            "response": f"Analysis #{self.analyses_count}: '{data}' shows positive trends",
            "confidence": 0.87
        }

    def get_tools(self) -> list:
        """Return tools for LLM - includes peer tools."""
        tools = [
            {
                "name": "analyze",
                "description": "Analyze data and return insights",
                "input_schema": {
                    "type": "object",
                    "properties": {"data": {"type": "string"}},
                    "required": ["data"]
                }
            }
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool - routes to local or peer tools."""
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            self.requests_sent.append({"tool": tool_name, "args": args})
            return await self.peers.as_tool().execute(tool_name, args)
        if tool_name == "analyze":
            return str(self.analyze(args.get("data", "")))
        return f"Unknown: {tool_name}"

    async def run(self):
        """Listen and respond to requests."""
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue
            if msg.is_request:
                self.requests_received.append(msg.data)
                result = self.analyze(msg.data.get("query", ""))
                await self.peers.respond(msg, result)

    async def execute_task(self, task): return {}


class Researcher(Agent):
    """
    Researcher - Good at research, can also ask other peers.

    This agent might receive a research request, get results,
    and ask the analyst to interpret them.
    """
    role = "researcher"
    capabilities = ["research", "data_collection", "summarization"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.research_count = 0
        self.requests_received = []
        self.requests_sent = []

    def research(self, topic: str) -> dict:
        """Core capability - research a topic."""
        self.research_count += 1
        return {
            "response": f"Research #{self.research_count}: Found 5 papers on '{topic}'",
            "sources": ["paper1.pdf", "paper2.pdf"]
        }

    def get_tools(self) -> list:
        """Return tools for LLM - includes peer tools."""
        tools = [
            {
                "name": "research",
                "description": "Research a topic and find relevant sources",
                "input_schema": {
                    "type": "object",
                    "properties": {"topic": {"type": "string"}},
                    "required": ["topic"]
                }
            }
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool - routes to local or peer tools."""
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            self.requests_sent.append({"tool": tool_name, "args": args})
            return await self.peers.as_tool().execute(tool_name, args)
        if tool_name == "research":
            return str(self.research(args.get("topic", "")))
        return f"Unknown: {tool_name}"

    async def run(self):
        """Listen and respond to requests."""
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue
            if msg.is_request:
                self.requests_received.append(msg.data)
                result = self.research(msg.data.get("query", ""))
                await self.peers.respond(msg, result)

    async def execute_task(self, task): return {}


class Assistant(Agent):
    """
    Assistant - Good at chat/search, coordinates between specialists.

    This agent might receive a complex request and delegate parts
    to analyst and researcher, then combine the results.
    """
    role = "assistant"
    capabilities = ["chat", "search", "coordination"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.search_count = 0
        self.requests_received = []
        self.requests_sent = []

    def search(self, query: str) -> str:
        """Core capability - search the web."""
        self.search_count += 1
        return f"Search #{self.search_count}: Results for '{query}'"

    def get_tools(self) -> list:
        """Return tools for LLM - includes peer tools."""
        tools = [
            {
                "name": "search",
                "description": "Search the web for information",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]
                }
            }
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool - routes to local or peer tools."""
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            self.requests_sent.append({"tool": tool_name, "args": args})
            return await self.peers.as_tool().execute(tool_name, args)
        if tool_name == "search":
            return self.search(args.get("query", ""))
        return f"Unknown: {tool_name}"

    async def run(self):
        """Listen and respond to requests."""
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue
            if msg.is_request:
                self.requests_received.append(msg.data)
                result = {"response": self.search(msg.data.get("query", ""))}
                await self.peers.respond(msg, result)

    async def execute_task(self, task): return {}


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mesh():
    """Create a fresh mesh."""
    return Mesh(mode="p2p")


@pytest.fixture
def wired_mesh(mesh):
    """Create mesh with all three agents wired up."""
    analyst = mesh.add(Analyst)
    researcher = mesh.add(Researcher)
    assistant = mesh.add(Assistant)

    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    return mesh, analyst, researcher, assistant


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMeshSetup:
    """Tests for basic mesh setup with multiple agents."""

    def test_all_agents_registered(self, wired_mesh):
        """All agents should be registered in the mesh."""
        mesh, analyst, researcher, assistant = wired_mesh
        assert len(mesh.agents) == 3

    def test_all_agents_have_peers(self, wired_mesh):
        """All agents should have peer client injected."""
        mesh, analyst, researcher, assistant = wired_mesh
        for agent in [analyst, researcher, assistant]:
            assert agent.peers is not None

    def test_all_agents_see_each_other(self, wired_mesh):
        """Each agent should see the other two in their peer list."""
        mesh, analyst, researcher, assistant = wired_mesh

        analyst_peers = [p["role"] for p in analyst.peers.list_peers()]
        assert "researcher" in analyst_peers
        assert "assistant" in analyst_peers

        researcher_peers = [p["role"] for p in researcher.peers.list_peers()]
        assert "analyst" in researcher_peers
        assert "assistant" in researcher_peers

        assistant_peers = [p["role"] for p in assistant.peers.list_peers()]
        assert "analyst" in assistant_peers
        assert "researcher" in assistant_peers


class TestAllAgentsHavePeerTools:
    """Tests that ALL agents have peer tools in their toolset."""

    def test_analyst_has_peer_tools(self, wired_mesh):
        """Analyst should have ask_peer, broadcast_update, list_peers."""
        mesh, analyst, researcher, assistant = wired_mesh
        tools = analyst.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "analyze" in tool_names  # Local
        assert "ask_peer" in tool_names  # Peer
        assert "broadcast_update" in tool_names
        assert "list_peers" in tool_names

    def test_researcher_has_peer_tools(self, wired_mesh):
        """Researcher should have ask_peer, broadcast_update, list_peers."""
        mesh, analyst, researcher, assistant = wired_mesh
        tools = researcher.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "research" in tool_names  # Local
        assert "ask_peer" in tool_names  # Peer
        assert "broadcast_update" in tool_names
        assert "list_peers" in tool_names

    def test_assistant_has_peer_tools(self, wired_mesh):
        """Assistant should have ask_peer, broadcast_update, list_peers."""
        mesh, analyst, researcher, assistant = wired_mesh
        tools = assistant.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "search" in tool_names  # Local
        assert "ask_peer" in tool_names  # Peer
        assert "broadcast_update" in tool_names
        assert "list_peers" in tool_names


class TestBidirectionalCommunication:
    """Tests that prove ANY agent can talk to ANY other agent."""

    @pytest.mark.asyncio
    async def test_analyst_asks_researcher(self, wired_mesh):
        """Analyst can ask researcher for data."""
        mesh, analyst, researcher, assistant = wired_mesh

        researcher_task = asyncio.create_task(researcher.run())
        await asyncio.sleep(0.1)

        try:
            result = await analyst.execute_tool("ask_peer", {
                "role": "researcher",
                "question": "Find papers on market trends"
            })
            assert "Research" in result
            assert len(analyst.requests_sent) == 1

        finally:
            researcher.request_shutdown()
            researcher_task.cancel()
            try: await researcher_task
            except asyncio.CancelledError: pass

    @pytest.mark.asyncio
    async def test_researcher_asks_analyst(self, wired_mesh):
        """Researcher can ask analyst to interpret data."""
        mesh, analyst, researcher, assistant = wired_mesh

        analyst_task = asyncio.create_task(analyst.run())
        await asyncio.sleep(0.1)

        try:
            result = await researcher.execute_tool("ask_peer", {
                "role": "analyst",
                "question": "Interpret these research findings"
            })
            assert "Analysis" in result
            assert len(researcher.requests_sent) == 1

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try: await analyst_task
            except asyncio.CancelledError: pass

    @pytest.mark.asyncio
    async def test_assistant_coordinates_both(self, wired_mesh):
        """Assistant can ask both analyst and researcher."""
        mesh, analyst, researcher, assistant = wired_mesh

        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())
        await asyncio.sleep(0.1)

        try:
            # Ask researcher
            r1 = await assistant.execute_tool("ask_peer", {
                "role": "researcher",
                "question": "Research AI trends"
            })
            assert "Research" in r1

            # Ask analyst
            r2 = await assistant.execute_tool("ask_peer", {
                "role": "analyst",
                "question": "Analyze the findings"
            })
            assert "Analysis" in r2

            assert len(assistant.requests_sent) == 2

        finally:
            analyst.request_shutdown()
            researcher.request_shutdown()
            analyst_task.cancel()
            researcher_task.cancel()
            for t in [analyst_task, researcher_task]:
                try: await t
                except asyncio.CancelledError: pass


class TestMultiAgentScenario:
    """Tests for realistic multi-agent scenarios."""

    @pytest.mark.asyncio
    async def test_chain_of_requests(self, wired_mesh):
        """
        Test a chain: Assistant → Researcher → (gets data) → Assistant asks Analyst

        This proves complex multi-agent workflows work.
        """
        mesh, analyst, researcher, assistant = wired_mesh

        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())
        await asyncio.sleep(0.1)

        try:
            # Step 1: Assistant asks researcher
            research_result = await assistant.execute_tool("ask_peer", {
                "role": "researcher",
                "question": "Find data on Q4 sales"
            })
            assert "Research" in research_result

            # Step 2: Assistant asks analyst to interpret
            analysis_result = await assistant.execute_tool("ask_peer", {
                "role": "analyst",
                "question": f"Interpret: {research_result}"
            })
            assert "Analysis" in analysis_result

            # Step 3: Assistant broadcasts completion
            broadcast_result = await assistant.execute_tool("broadcast_update", {
                "message": "Research and analysis complete!"
            })
            assert "Broadcast" in broadcast_result

        finally:
            analyst.request_shutdown()
            researcher.request_shutdown()
            for t in [analyst_task, researcher_task]:
                t.cancel()
                try: await t
                except asyncio.CancelledError: pass

    @pytest.mark.asyncio
    async def test_all_agents_can_receive_while_sending(self, wired_mesh):
        """
        All agents running their run() loops while also sending.

        This proves true bidirectional communication.
        """
        mesh, analyst, researcher, assistant = wired_mesh

        # Start all run loops
        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())
        assistant_task = asyncio.create_task(assistant.run())
        await asyncio.sleep(0.1)

        try:
            # Analyst sends to researcher
            r1 = await analyst.execute_tool("ask_peer", {
                "role": "researcher", "question": "Get data"
            })
            assert "Research" in r1

            # Researcher sends to assistant
            r2 = await researcher.execute_tool("ask_peer", {
                "role": "assistant", "question": "Search for more"
            })
            assert "Search" in r2

            # Assistant sends to analyst
            r3 = await assistant.execute_tool("ask_peer", {
                "role": "analyst", "question": "Analyze this"
            })
            assert "Analysis" in r3

            # Verify all received requests
            assert len(researcher.requests_received) >= 1  # From analyst
            assert len(assistant.requests_received) >= 1   # From researcher
            assert len(analyst.requests_received) >= 1     # From assistant

        finally:
            for agent in [analyst, researcher, assistant]:
                agent.request_shutdown()
            for t in [analyst_task, researcher_task, assistant_task]:
                t.cancel()
                try: await t
                except asyncio.CancelledError: pass


class TestLLMToolDispatch:
    """Tests simulating LLM tool dispatch patterns."""

    @pytest.mark.asyncio
    async def test_llm_decides_to_ask_peer(self, wired_mesh):
        """
        Simulate LLM deciding to use ask_peer tool.

        This is what happens in real code:
        1. LLM receives request
        2. LLM sees tools including ask_peer
        3. LLM decides to delegate to specialist
        4. Tool is executed
        5. Result returned to LLM
        """
        mesh, analyst, researcher, assistant = wired_mesh

        analyst_task = asyncio.create_task(analyst.run())
        await asyncio.sleep(0.1)

        try:
            # Step 1: Get tools (what LLM sees)
            tools = assistant.get_tools()
            tool_names = [t["name"] for t in tools]
            assert "ask_peer" in tool_names

            # Step 2: Simulate LLM decision
            llm_decision = {
                "tool": "ask_peer",
                "args": {"role": "analyst", "question": "Analyze data"}
            }

            # Step 3: Execute
            result = await assistant.execute_tool(
                llm_decision["tool"],
                llm_decision["args"]
            )

            # Step 4: Result is string for LLM
            assert isinstance(result, str)

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try: await analyst_task
            except asyncio.CancelledError: pass


# ═══════════════════════════════════════════════════════════════════════════════
# FULL INTEGRATION - Complete scenario
# ═══════════════════════════════════════════════════════════════════════════════

async def test_full_integration():
    """Complete integration test with all agents."""
    print("\n" + "="*70)
    print("FULL INTEGRATION: All Agents as Equal Mesh Participants")
    print("="*70)

    mesh = Mesh(mode="p2p")

    analyst = mesh.add(Analyst)
    researcher = mesh.add(Researcher)
    assistant = mesh.add(Assistant)

    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    # Start all listeners
    tasks = [
        asyncio.create_task(analyst.run()),
        asyncio.create_task(researcher.run()),
        asyncio.create_task(assistant.run())
    ]
    await asyncio.sleep(0.1)

    print("\n[1] All agents see each other")
    for agent in [analyst, researcher, assistant]:
        peers = [p["role"] for p in agent.peers.list_peers()]
        print(f"    {agent.role} sees: {peers}")

    print("\n[2] All agents have peer tools")
    for agent in [analyst, researcher, assistant]:
        tools = [t["name"] for t in agent.get_tools()]
        has_peer_tools = "ask_peer" in tools
        print(f"    {agent.role}: {tools} (peer tools: {has_peer_tools})")

    print("\n[3] Bidirectional communication")

    # Analyst → Researcher
    r = await analyst.execute_tool("ask_peer", {"role": "researcher", "question": "Get data"})
    print(f"    Analyst → Researcher: {r[:40]}...")

    # Researcher → Analyst
    r = await researcher.execute_tool("ask_peer", {"role": "analyst", "question": "Interpret"})
    print(f"    Researcher → Analyst: {r[:40]}...")

    # Assistant → Both
    r = await assistant.execute_tool("ask_peer", {"role": "analyst", "question": "Analyze"})
    print(f"    Assistant → Analyst: {r[:40]}...")
    r = await assistant.execute_tool("ask_peer", {"role": "researcher", "question": "Research"})
    print(f"    Assistant → Researcher: {r[:40]}...")

    print("\n[4] Request counts")
    print(f"    Analyst received: {len(analyst.requests_received)}, sent: {len(analyst.requests_sent)}")
    print(f"    Researcher received: {len(researcher.requests_received)}, sent: {len(researcher.requests_sent)}")
    print(f"    Assistant received: {len(assistant.requests_received)}, sent: {len(assistant.requests_sent)}")

    # Cleanup
    for agent in [analyst, researcher, assistant]:
        agent.request_shutdown()
    for t in tasks:
        t.cancel()
        try: await t
        except asyncio.CancelledError: pass

    print("\n" + "="*70)
    print("INTEGRATION TEST PASSED!")
    print("="*70)


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(test_full_integration())

    print("""
═══════════════════════════════════════════════════════════════════════════════
KEY INSIGHT: ALL agents are EQUAL mesh participants
═══════════════════════════════════════════════════════════════════════════════

  Every agent (Analyst, Researcher, Assistant):
  ├── Has an LLM for reasoning
  ├── Has get_tools() with LOCAL + PEER tools
  ├── Can SEND via ask_peer, broadcast_update
  ├── Can RECEIVE via run() loop
  └── The role just defines what they're GOOD at

  Communication is bidirectional:
  ├── Analyst ←→ Researcher
  ├── Researcher ←→ Assistant
  └── Assistant ←→ Analyst

  This is the power of the mesh:
  - No hierarchies
  - No "sender" vs "receiver" types
  - Every agent is a full participant
═══════════════════════════════════════════════════════════════════════════════
""")
