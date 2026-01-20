"""
Test 4: Assistant WITH JarvisCore Framework

Same Assistant, but now connected to the mesh.
CAN talk to other agents using PeerTool.
"""
import asyncio
import sys
sys.path.insert(0, '.')

from jarviscore.core.agent import Agent
from jarviscore.core.mesh import Mesh
from jarviscore.p2p.peer_client import PeerClient
from jarviscore.p2p.peer_tool import PeerTool


class ConnectedAssistant(Agent):
    """
    Assistant agent connected to jarviscore mesh.

    Same capabilities as standalone:
    - Search the web
    - Calculate expressions

    NEW with framework:
    - Can discover other agents
    - Can ask other agents for help (ask_peer)
    - Can broadcast updates to all agents
    - Has self.peers for P2P communication
    """
    role = "assistant"
    capabilities = ["chat", "search", "calculate"]

    def search(self, query: str) -> str:
        """Search the web for information."""
        return f"Search results for '{query}': Found 10 relevant articles."

    def calculate(self, expression: str) -> str:
        """Calculate a math expression."""
        try:
            result = eval(expression)
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {e}"

    def get_tools(self) -> list:
        """
        Return tool definitions for LLM.

        NOW includes peer tools if connected to mesh!
        """
        tools = [
            {"name": "search", "description": "Search the web"},
            {"name": "calculate", "description": "Calculate math"}
        ]

        # NEW: Add peer tools if connected
        if self.peers:
            peer_tool = self.peers.as_tool()
            tools.extend(peer_tool.schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool by name (now supports peer tools!)."""
        # NEW: Peer tools
        if self.peers and tool_name in ["ask_peer", "broadcast_update", "list_peers"]:
            peer_tool = self.peers.as_tool()
            return await peer_tool.execute(tool_name, args)

        # Original local tools
        if tool_name == "search":
            return self.search(args.get("query", ""))
        elif tool_name == "calculate":
            return self.calculate(args.get("expression", ""))

        return f"Unknown tool: {tool_name}"

    async def execute_task(self, task: dict) -> dict:
        """Required by Agent base class."""
        return {"status": "success"}


# Helper: Create an analyst for testing
class TestAnalyst(Agent):
    """Simple analyst for testing communication."""
    role = "analyst"
    capabilities = ["analysis"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.received_queries = []

    async def execute_task(self, task): return {}

    async def run(self):
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=1.0)
            if msg and msg.is_request:
                self.received_queries.append(msg.data.get("query"))
                await self.peers.respond(msg, {
                    "response": f"Analyzed: {msg.data.get('query')}"
                })


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_assistant_inherits_from_agent():
    """Assistant inherits from jarviscore Agent."""
    assert issubclass(ConnectedAssistant, Agent)
    print("✓ Assistant inherits from Agent")


def test_assistant_has_role_and_capabilities():
    """Assistant defines role and capabilities."""
    assert ConnectedAssistant.role == "assistant"
    assert "search" in ConnectedAssistant.capabilities
    assert "calculate" in ConnectedAssistant.capabilities
    print(f"✓ Role: {ConnectedAssistant.role}")
    print(f"✓ Capabilities: {ConnectedAssistant.capabilities}")


def test_assistant_can_be_added_to_mesh():
    """Assistant can be added to mesh."""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)

    assert assistant in mesh.agents
    print(f"✓ Added to mesh: {assistant.agent_id}")


def test_assistant_gets_peers_injected():
    """Assistant gets self.peers after injection."""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)

    # Before
    assert assistant.peers is None

    # Inject
    assistant.peers = PeerClient(
        coordinator=None,
        agent_id=assistant.agent_id,
        agent_role=assistant.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    # After
    assert assistant.peers is not None
    print("✓ self.peers injected")


def test_assistant_original_tools_still_work():
    """Assistant still has original tools."""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)

    result = assistant.search("python tutorials")
    assert "python tutorials" in result
    print(f"✓ Search still works: {result}")

    result = assistant.calculate("5 * 5")
    assert "25" in result
    print(f"✓ Calculate still works: {result}")


def test_assistant_now_has_peer_tools():
    """Assistant NOW has peer tools!"""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)
    mesh.add(TestAnalyst)  # Add analyst so it shows up

    # Inject peers
    assistant.peers = PeerClient(
        coordinator=None,
        agent_id=assistant.agent_id,
        agent_role=assistant.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    tools = assistant.get_tools()
    tool_names = [t["name"] for t in tools]

    # Original tools
    assert "search" in tool_names
    assert "calculate" in tool_names

    # NEW peer tools!
    assert "ask_peer" in tool_names
    assert "broadcast_update" in tool_names
    assert "list_peers" in tool_names

    print(f"✓ Tools: {tool_names}")
    print("  ^ NOW includes peer communication tools!")


def test_peer_tool_schema_shows_available_peers():
    """Tool schema dynamically shows who's online."""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)
    mesh.add(TestAnalyst)

    assistant.peers = PeerClient(
        coordinator=None,
        agent_id=assistant.agent_id,
        agent_role=assistant.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    tools = assistant.get_tools()
    ask_peer = next(t for t in tools if t["name"] == "ask_peer")

    # Shows analyst in description
    assert "analyst" in ask_peer["description"]

    # Enum includes analyst
    role_enum = ask_peer["input_schema"]["properties"]["role"]["enum"]
    assert "analyst" in role_enum

    print(f"✓ ask_peer shows peers: {role_enum}")


async def test_list_peers_tool():
    """Can execute list_peers tool."""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)
    mesh.add(TestAnalyst)

    assistant.peers = PeerClient(
        coordinator=None,
        agent_id=assistant.agent_id,
        agent_role=assistant.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    result = await assistant.execute_tool("list_peers", {})

    assert "analyst" in result
    print(f"✓ list_peers:\n{result}")


async def test_ask_peer_tool():
    """Can execute ask_peer tool - THE KEY FEATURE!"""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)
    analyst = mesh.add(TestAnalyst)

    # Inject peers
    assistant.peers = PeerClient(
        coordinator=None,
        agent_id=assistant.agent_id,
        agent_role=assistant.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )
    analyst.peers = PeerClient(
        coordinator=None,
        agent_id=analyst.agent_id,
        agent_role=analyst.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    # Start analyst
    analyst_task = asyncio.create_task(analyst.run())
    await asyncio.sleep(0.1)

    # Assistant asks analyst!
    result = await assistant.execute_tool("ask_peer", {
        "role": "analyst",
        "question": "Analyze Q4 sales"
    })

    assert "Analyzed" in result
    assert len(analyst.received_queries) == 1
    print(f"✓ ask_peer result: {result}")

    # Cleanup
    analyst.request_shutdown()
    analyst_task.cancel()
    try:
        await analyst_task
    except asyncio.CancelledError:
        pass


async def test_broadcast_tool():
    """Can broadcast to all peers."""
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(ConnectedAssistant)
    analyst = mesh.add(TestAnalyst)

    assistant.peers = PeerClient(
        coordinator=None,
        agent_id=assistant.agent_id,
        agent_role=assistant.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )
    analyst.peers = PeerClient(
        coordinator=None,
        agent_id=analyst.agent_id,
        agent_role=analyst.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    result = await assistant.execute_tool("broadcast_update", {
        "message": "Task complete!"
    })

    assert "1 peer" in result
    print(f"✓ broadcast: {result}")

    # Analyst received it
    msg = await analyst.peers.receive(timeout=1.0)
    assert msg is not None
    print(f"✓ Analyst received: {msg.data}")


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 4: ASSISTANT WITH JARVISCORE FRAMEWORK")
    print("="*60 + "\n")

    # Sync tests
    test_assistant_inherits_from_agent()
    test_assistant_has_role_and_capabilities()
    test_assistant_can_be_added_to_mesh()
    test_assistant_gets_peers_injected()
    test_assistant_original_tools_still_work()
    test_assistant_now_has_peer_tools()
    test_peer_tool_schema_shows_available_peers()

    # Async tests
    print("\n--- Async Tests ---")
    asyncio.run(test_list_peers_tool())
    asyncio.run(test_ask_peer_tool())
    asyncio.run(test_broadcast_tool())

    print("\n" + "-"*60)
    print("Assistant NOW can talk to other agents!")
    print("")
    print("Before: tools = [search, calculate]")
    print("After:  tools = [search, calculate, ask_peer, broadcast_update, list_peers]")
    print("-"*60 + "\n")
