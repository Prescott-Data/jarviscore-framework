"""
Test 4: Assistant WITH JarvisCore Framework

Demonstrates an LLM-POWERED AGENT that can BOTH send AND receive.

KEY CONCEPT - All agents are equal participants:
    - Every agent has an LLM for reasoning
    - Every agent can SEND requests to peers (via ask_peer tool)
    - Every agent can RECEIVE requests from peers (via run() loop)
    - The "role" defines what they're GOOD at, not communication direction

This test shows the ASSISTANT role - good at search, calculate, chat.
But it's the SAME PATTERN as the analyst - full bidirectional communication.

BEFORE (Standalone):
    - Assistant has search(), calculate() capabilities
    - Assistant has get_tools() for its LLM
    - Cannot communicate with other agents

AFTER (With Framework):
    - Same search(), calculate() capabilities
    - get_tools() NOW includes peer tools
    - Can RECEIVE requests and process them with LLM
    - Can SEND requests to other peers
    - Full mesh participant

DEVELOPER CHANGES REQUIRED (same for ALL agents):
    1. Inherit from Agent
    2. Add `role` and `capabilities` class attributes
    3. Modify get_tools() to include self.peers.as_tool().schema
    4. Modify execute_tool() to dispatch peer tools
    5. Add async def run() loop for incoming requests
    6. Add async def execute_task() (required by base class)
"""
import asyncio
import sys
import pytest
sys.path.insert(0, '.')

from jarviscore.core.agent import Agent
from jarviscore.core.mesh import Mesh
from jarviscore.p2p.peer_client import PeerClient


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mesh():
    """Create a fresh mesh for each test."""
    return Mesh(mode="p2p")


@pytest.fixture
def assistant(mesh):
    """Create an assistant added to mesh."""
    return mesh.add(ConnectedAssistant)


@pytest.fixture
def assistant_with_peers(mesh, assistant):
    """Create assistant with peer client injected."""
    assistant.peers = PeerClient(
        coordinator=None,
        agent_id=assistant.agent_id,
        agent_role=assistant.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )
    return assistant


# ═══════════════════════════════════════════════════════════════════════════════
# THE AGENT - LLM-powered agent that can BOTH send AND receive
# ═══════════════════════════════════════════════════════════════════════════════

class ConnectedAssistant(Agent):
    """
    Assistant agent - AFTER installing jarviscore.

    This is a FULL LLM-POWERED AGENT that can:
    - Use its own tools (search, calculate)
    - Ask other peers for help (ask_peer)
    - Receive and process requests from other agents
    - Broadcast updates to all peers

    Same pattern as Analyst - the only difference is what it's GOOD at.
    """
    # Identity for mesh registration
    role = "assistant"
    capabilities = ["chat", "search", "calculate"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.requests_processed = []
        self.received_broadcasts = []

    # ─────────────────────────────────────────────────────────────────
    # CORE CAPABILITIES - What this agent is good at
    # ─────────────────────────────────────────────────────────────────

    def search(self, query: str) -> str:
        """Search the web for information. (Core capability)"""
        return f"Search results for '{query}': Found 10 relevant articles."

    def calculate(self, expression: str) -> str:
        """Calculate a math expression. (Core capability)"""
        try:
            result = eval(expression)
            return f"Result: {result}"
        except Exception as e:
            return f"Error: {e}"

    # ─────────────────────────────────────────────────────────────────
    # LLM TOOL INTERFACE - What LLM can use
    # ─────────────────────────────────────────────────────────────────

    def get_tools(self) -> list:
        """
        Return tool definitions for THIS AGENT'S LLM.

        Includes:
        - Local tools (search, calculate)
        - Peer tools (ask_peer, broadcast_update, list_peers)

        The LLM decides which tools to use based on the task.
        """
        tools = [
            {
                "name": "search",
                "description": "Search the web for information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "calculate",
                "description": "Calculate a math expression",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "Math expression"}
                    },
                    "required": ["expression"]
                }
            }
        ]

        # Add peer tools if connected to mesh
        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """
        Execute a tool by name.

        This is called when the LLM decides to use a tool.
        Routes to local tools or peer tools as appropriate.
        """
        # Peer tools
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)

        # Local tools
        if tool_name == "search":
            return self.search(args.get("query", ""))
        elif tool_name == "calculate":
            return self.calculate(args.get("expression", ""))

        return f"Unknown tool: {tool_name}"

    # ─────────────────────────────────────────────────────────────────
    # MESSAGE HANDLING - Process incoming requests with LLM
    # ─────────────────────────────────────────────────────────────────

    async def run(self):
        """
        Main loop - receive and process requests.

        When a request comes in, the LLM decides how to handle it.
        The LLM might:
        - Use local tools (search, calculate)
        - Ask other peers for help (ask_peer)
        - Combine multiple tool calls
        """
        self._logger.info(f"Assistant {self.agent_id} listening...")

        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue

            if msg.is_request:
                # Process request with LLM
                query = msg.data.get("query", "")
                self._logger.info(f"Request from {msg.sender}: {query}")

                # Simulate LLM deciding how to respond
                # In real code: response = await self.llm.chat(query, tools=self.get_tools())
                # For testing, we'll use search as default action
                result = {"response": self.search(query)}
                self.requests_processed.append({"from": msg.sender, "query": query})

                await self.peers.respond(msg, result)

            elif msg.is_notify:
                self._logger.info(f"Broadcast: {msg.data}")
                self.received_broadcasts.append(msg.data)

    async def execute_task(self, task: dict) -> dict:
        """Required by Agent base class."""
        return {"status": "success"}


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS - Organized by what they verify
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrameworkIntegration:
    """Tests that verify the agent integrates correctly with jarviscore."""

    def test_inherits_from_agent(self):
        """Agent must inherit from jarviscore.Agent."""
        assert issubclass(ConnectedAssistant, Agent)

    def test_has_required_attributes(self):
        """Agent must declare role and capabilities."""
        assert ConnectedAssistant.role == "assistant"
        assert len(ConnectedAssistant.capabilities) > 0

    def test_can_be_added_to_mesh(self, mesh):
        """Agent can be registered with the mesh."""
        assistant = mesh.add(ConnectedAssistant)
        assert assistant in mesh.agents
        assert assistant.agent_id is not None


class TestLocalTools:
    """Tests for the agent's local tools."""

    def test_search_works(self, assistant):
        """Core search capability should work."""
        result = assistant.search("python tutorials")
        assert "python tutorials" in result
        assert "Found" in result

    def test_calculate_works(self, assistant):
        """Core calculate capability should work."""
        result = assistant.calculate("2 + 2")
        assert "4" in result

    def test_get_tools_returns_local_tools(self, assistant):
        """get_tools() should return local tools (before peers injected)."""
        tools = assistant.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "search" in tool_names
        assert "calculate" in tool_names


class TestPeerToolsIntegration:
    """Tests for peer tools being added to the agent's toolset."""

    def test_get_tools_includes_peer_tools_when_connected(self, assistant_with_peers, mesh):
        """After peer injection, get_tools() should include peer tools."""
        # Add another agent
        class Analyst(Agent):
            role = "analyst"
            capabilities = ["analysis"]
            async def execute_task(self, task): return {}

        analyst = mesh.add(Analyst)
        analyst.peers = PeerClient(
            coordinator=None,
            agent_id=analyst.agent_id,
            agent_role=analyst.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        tools = assistant_with_peers.get_tools()
        tool_names = [t["name"] for t in tools]

        # Local tools
        assert "search" in tool_names
        assert "calculate" in tool_names

        # Peer tools
        assert "ask_peer" in tool_names
        assert "broadcast_update" in tool_names
        assert "list_peers" in tool_names

    def test_ask_peer_schema_shows_available_peers(self, assistant_with_peers, mesh):
        """ask_peer tool should show other agents in the enum."""
        class Analyst(Agent):
            role = "analyst"
            capabilities = ["analysis"]
            async def execute_task(self, task): return {}

        analyst = mesh.add(Analyst)
        analyst.peers = PeerClient(
            coordinator=None,
            agent_id=analyst.agent_id,
            agent_role=analyst.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        tools = assistant_with_peers.get_tools()
        ask_peer = next(t for t in tools if t["name"] == "ask_peer")

        role_enum = ask_peer["input_schema"]["properties"]["role"]["enum"]
        assert "analyst" in role_enum

    @pytest.mark.asyncio
    async def test_assistant_can_ask_analyst(self, assistant_with_peers, mesh):
        """Assistant should be able to ask analyst for help."""
        class Analyst(Agent):
            role = "analyst"
            capabilities = ["analysis"]
            async def execute_task(self, task): return {}
            async def run(self):
                while not self.shutdown_requested:
                    msg = await self.peers.receive(timeout=0.5)
                    if msg and msg.is_request:
                        await self.peers.respond(msg, {
                            "response": f"Analysis of: {msg.data.get('query')}"
                        })

        analyst = mesh.add(Analyst)
        analyst.peers = PeerClient(
            coordinator=None,
            agent_id=analyst.agent_id,
            agent_role=analyst.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        analyst_task = asyncio.create_task(analyst.run())
        await asyncio.sleep(0.1)

        try:
            result = await assistant_with_peers.execute_tool("ask_peer", {
                "role": "analyst",
                "question": "Analyze Q4 sales"
            })

            assert "Analysis" in result

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass


class TestReceivingRequests:
    """Tests for the agent receiving and processing requests."""

    @pytest.fixture
    def requester(self, mesh):
        """Create another agent to send requests."""
        class Requester(Agent):
            role = "requester"
            capabilities = ["requesting"]
            async def execute_task(self, task): return {}

        req = mesh.add(Requester)
        req.peers = PeerClient(
            coordinator=None,
            agent_id=req.agent_id,
            agent_role=req.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )
        return req

    @pytest.mark.asyncio
    async def test_assistant_receives_and_responds(self, assistant_with_peers, requester):
        """Assistant should receive request, process with LLM, and respond."""
        assistant_task = asyncio.create_task(assistant_with_peers.run())
        await asyncio.sleep(0.1)

        try:
            response = await requester.peers.request("assistant", {
                "query": "Find information about AI"
            }, timeout=5.0)

            assert response is not None
            assert "response" in response
            assert len(assistant_with_peers.requests_processed) == 1

        finally:
            assistant_with_peers.request_shutdown()
            assistant_task.cancel()
            try:
                await assistant_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_assistant_receives_broadcasts(self, assistant_with_peers, requester):
        """Assistant should receive broadcast notifications."""
        assistant_task = asyncio.create_task(assistant_with_peers.run())
        await asyncio.sleep(0.1)

        try:
            await requester.peers.broadcast({"message": "System update!"})
            await asyncio.sleep(0.2)

            assert len(assistant_with_peers.received_broadcasts) == 1

        finally:
            assistant_with_peers.request_shutdown()
            assistant_task.cancel()
            try:
                await assistant_task
            except asyncio.CancelledError:
                pass


class TestBidirectionalCommunication:
    """Tests proving the agent can BOTH send AND receive."""

    @pytest.mark.asyncio
    async def test_assistant_full_mesh_participant(self, mesh):
        """
        Assistant can SEND to analyst AND RECEIVE from others.

        This proves the agent is a full mesh participant.
        """
        # Create assistant
        assistant = mesh.add(ConnectedAssistant)
        assistant.peers = PeerClient(
            coordinator=None,
            agent_id=assistant.agent_id,
            agent_role=assistant.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        # Create analyst that assistant can ask
        class Analyst(Agent):
            role = "analyst"
            capabilities = ["analysis"]
            async def execute_task(self, task): return {}
            async def run(self):
                while not self.shutdown_requested:
                    msg = await self.peers.receive(timeout=0.5)
                    if msg and msg.is_request:
                        await self.peers.respond(msg, {"response": "Analysis data"})

        analyst = mesh.add(Analyst)
        analyst.peers = PeerClient(
            coordinator=None,
            agent_id=analyst.agent_id,
            agent_role=analyst.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        # Create requester
        class Requester(Agent):
            role = "requester"
            capabilities = ["requesting"]
            async def execute_task(self, task): return {}

        requester = mesh.add(Requester)
        requester.peers = PeerClient(
            coordinator=None,
            agent_id=requester.agent_id,
            agent_role=requester.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        # Start agents
        analyst_task = asyncio.create_task(analyst.run())
        assistant_task = asyncio.create_task(assistant.run())
        await asyncio.sleep(0.1)

        try:
            # Assistant SENDS to analyst
            result = await assistant.execute_tool("ask_peer", {
                "role": "analyst",
                "question": "Get analysis"
            })
            assert "Analysis data" in result

            # Assistant RECEIVES from requester
            response = await requester.peers.request("assistant", {
                "query": "Search for AI"
            }, timeout=5.0)
            assert response is not None

        finally:
            assistant.request_shutdown()
            analyst.request_shutdown()
            assistant_task.cancel()
            analyst_task.cancel()
            for t in [assistant_task, analyst_task]:
                try:
                    await t
                except asyncio.CancelledError:
                    pass


class TestToolSchemaFormat:
    """Tests that tool schemas are valid for LLM consumption."""

    def test_schema_has_required_fields(self, assistant_with_peers, mesh):
        """All tools should have proper Anthropic schema format."""
        class Analyst(Agent):
            role = "analyst"
            capabilities = ["analysis"]
            async def execute_task(self, task): return {}

        mesh.add(Analyst)

        tools = assistant_with_peers.get_tools()

        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            if tool["name"] in ["search", "calculate", "ask_peer", "broadcast_update"]:
                assert "input_schema" in tool
                assert tool["input_schema"]["type"] == "object"
                assert "properties" in tool["input_schema"]


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL RUN
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_integration_test():
    """Full integration showing assistant as a complete mesh participant."""
    print("\n[Integration: Assistant as full participant]")

    mesh = Mesh(mode="p2p")

    # Create assistant
    assistant = mesh.add(ConnectedAssistant)

    # Create analyst for assistant to talk to
    class Analyst(Agent):
        role = "analyst"
        capabilities = ["analysis"]
        async def execute_task(self, task): return {}
        async def run(self):
            while not self.shutdown_requested:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    await self.peers.respond(msg, {
                        "response": f"Analysis: {msg.data.get('query')}"
                    })

    analyst = mesh.add(Analyst)

    # Create requester that will ask assistant
    class Requester(Agent):
        role = "requester"
        capabilities = ["requesting"]
        async def execute_task(self, task): return {}

    requester = mesh.add(Requester)

    # Inject peers
    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    # Start agents
    assistant_task = asyncio.create_task(assistant.run())
    analyst_task = asyncio.create_task(analyst.run())
    await asyncio.sleep(0.1)

    try:
        # Show assistant's tools (includes peer tools)
        tools = assistant.get_tools()
        print(f"  Assistant tools: {[t['name'] for t in tools]}")
        assert "ask_peer" in [t['name'] for t in tools]
        print("  ✓ Assistant has peer tools")

        # Assistant SENDS to analyst
        result = await assistant.execute_tool("ask_peer", {
            "role": "analyst",
            "question": "Analyze market data"
        })
        print(f"  ✓ Assistant asked analyst: {result}")

        # Assistant RECEIVES from requester
        response = await requester.peers.request("assistant", {
            "query": "Search for trends"
        }, timeout=5.0)
        print(f"  ✓ Assistant received and responded: {response['response'][:40]}...")

        # Assistant broadcasts
        result = await assistant.execute_tool("broadcast_update", {
            "message": "Task complete!"
        })
        print(f"  ✓ Assistant broadcast: {result}")

        print("\n  PROVED: Assistant can SEND, RECEIVE, and BROADCAST")

    finally:
        assistant.request_shutdown()
        analyst.request_shutdown()
        assistant_task.cancel()
        analyst_task.cancel()
        for t in [assistant_task, analyst_task]:
            try:
                await t
            except asyncio.CancelledError:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# LLM TOOL-USE DEMO - Shows how Assistant's LLM decides to use tools
# ═══════════════════════════════════════════════════════════════════════════════

class AssistantMockLLM:
    """
    Simulates Assistant's LLM decision-making.

    The Assistant's LLM might decide to:
    - Use LOCAL tool (search) for web searches
    - Use LOCAL tool (calculate) for math
    - Use PEER tool (ask_peer → analyst) for analysis
    - Respond directly for simple queries
    """

    def __init__(self):
        self.calls = []

    def chat(self, messages: list, tools: list) -> dict:
        """Simulate LLM deciding what tool to use."""
        self.calls.append({"messages": messages, "tools": tools})

        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "").lower()
                break

        tool_names = [t["name"] for t in tools]

        # Assistant's decision logic
        if "search" in user_msg and "search" in tool_names:
            # Use LOCAL search tool
            return {
                "type": "tool_use",
                "tool": "search",
                "args": {"query": user_msg}
            }
        elif "calculate" in user_msg or any(c in user_msg for c in ['+', '-', '*', '/']):
            if "calculate" in tool_names:
                # Extract expression or use placeholder
                expr = user_msg.split("calculate")[-1].strip() if "calculate" in user_msg else "2+2"
                return {
                    "type": "tool_use",
                    "tool": "calculate",
                    "args": {"expression": expr or "2+2"}
                }
        elif "analyze" in user_msg or "analysis" in user_msg:
            if "ask_peer" in tool_names:
                # Need analysis - ask analyst
                return {
                    "type": "tool_use",
                    "tool": "ask_peer",
                    "args": {"role": "analyst", "question": user_msg}
                }

        # Default: respond directly
        return {
            "type": "text",
            "content": f"[assistant] I can help with that: {user_msg}"
        }

    def incorporate_tool_result(self, tool_name: str, result: str) -> str:
        return f"Based on {tool_name}: {result}"


class LLMPoweredAssistant(ConnectedAssistant):
    """Assistant with full LLM simulation for demo."""

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = AssistantMockLLM()
        self.conversation_history = []
        self.tool_calls_made = []

    async def chat(self, user_message: str) -> str:
        """Complete LLM chat loop."""
        self.conversation_history.append({"role": "user", "content": user_message})

        tools = self.get_tools()
        llm_response = self.llm.chat(self.conversation_history, tools)

        if llm_response["type"] == "tool_use":
            tool_name = llm_response["tool"]
            tool_args = llm_response["args"]
            self.tool_calls_made.append({"tool": tool_name, "args": tool_args})

            tool_result = await self.execute_tool(tool_name, tool_args)

            self.conversation_history.append({"role": "assistant", "content": f"[Tool: {tool_name}]"})
            self.conversation_history.append({"role": "tool", "content": tool_result})

            final = self.llm.incorporate_tool_result(tool_name, tool_result)
        else:
            final = llm_response["content"]

        self.conversation_history.append({"role": "assistant", "content": final})
        return final


async def demo_assistant_llm_flow():
    """Demo showing how Assistant's LLM decides to use tools."""
    print("\n" + "="*70)
    print("ASSISTANT LLM TOOL-USE FLOW")
    print("="*70)

    print("""
    This shows how the ASSISTANT's LLM decides which tools to use:

    ┌─────────────────────────────────────────────────────────────────┐
    │  "search for X"     → LLM uses LOCAL tool (search)              │
    │  "calculate X"      → LLM uses LOCAL tool (calculate)           │
    │  "analyze X"        → LLM uses PEER tool (ask_peer→analyst)     │
    │  "hello"            → LLM responds DIRECTLY                     │
    └─────────────────────────────────────────────────────────────────┘
    """)

    mesh = Mesh(mode="p2p")

    assistant = LLMPoweredAssistant()
    mesh._agent_registry["assistant"] = [assistant]

    # Add analyst for assistant to delegate to
    class Analyst(Agent):
        role = "analyst"
        capabilities = ["analysis"]
        async def execute_task(self, task): return {}
        async def run(self):
            while not self.shutdown_requested:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    await self.peers.respond(msg, {
                        "response": f"[analyst] Analysis complete: {msg.data.get('query')} shows positive trends"
                    })

    analyst = Analyst()
    mesh._agent_registry["analyst"] = [analyst]
    mesh.agents = [assistant, analyst]

    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    analyst_task = asyncio.create_task(analyst.run())
    await asyncio.sleep(0.1)

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 1: Assistant uses LOCAL search tool
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 1: Request to SEARCH (Assistant uses LOCAL tool)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Please search for Python tutorials\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    tools = assistant.get_tools()
    print(f"    │")
    print(f"    ├─→ [LLM RECEIVES] Message: \"Please search for Python tutorials\"")
    print(f"    │   Tools available: {[t['name'] for t in tools]}")

    response = await assistant.chat("Please search for Python tutorials")

    print(f"    │")
    print(f"    ├─→ [LLM DECIDES] Use LOCAL tool: search")
    print(f"    │   Args: {assistant.tool_calls_made[-1]['args']}")
    print(f"    │")
    print(f"    ├─→ [EXECUTE LOCAL TOOL] search")
    print(f"    │")
    print(f"    └─→ [LLM RESPONDS] \"{response[:60]}...\"")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ Assistant's LLM used LOCAL tool (search)")

    assistant.tool_calls_made = []
    assistant.conversation_history = []

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 2: Assistant uses LOCAL calculate tool
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 2: Math request (Assistant uses LOCAL calculate tool)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Please calculate 15% of 200\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    print(f"    │")
    print(f"    ├─→ [LLM RECEIVES] Message: \"Please calculate 15% of 200\"")
    print(f"    │   Tools available: {[t['name'] for t in tools]}")

    response = await assistant.chat("Please calculate 200 * 0.15")

    print(f"    │")
    print(f"    ├─→ [LLM DECIDES] Use LOCAL tool: calculate")
    print(f"    │   Args: {assistant.tool_calls_made[-1]['args']}")
    print(f"    │")
    print(f"    ├─→ [EXECUTE LOCAL TOOL] calculate")
    print(f"    │")
    print(f"    └─→ [LLM RESPONDS] \"{response}\"")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ Assistant's LLM used LOCAL tool (calculate)")

    assistant.tool_calls_made = []
    assistant.conversation_history = []

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 3: Assistant delegates to analyst
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 3: Analysis request (Assistant delegates to ANALYST)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Please analyze the sales data\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    print(f"    │")
    print(f"    ├─→ [LLM RECEIVES] Message: \"Please analyze the sales data\"")
    print(f"    │   Tools available: {[t['name'] for t in tools]}")

    response = await assistant.chat("Please analyze the sales data")

    print(f"    │")
    print(f"    ├─→ [LLM DECIDES] Use PEER tool: ask_peer → analyst")
    print(f"    │   Args: {assistant.tool_calls_made[-1]['args']}")
    print(f"    │")
    print(f"    ├─→ [EXECUTE PEER TOOL] ask_peer")
    print(f"    │   Sending to: analyst")
    print(f"    │   Analyst responds: \"Analysis complete...\"")
    print(f"    │")
    print(f"    └─→ [LLM RESPONDS] \"{response[:60]}...\"")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ Assistant's LLM delegated to PEER (analyst)")

    assistant.tool_calls_made = []
    assistant.conversation_history = []

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 4: Assistant responds directly
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 4: Simple greeting (Assistant responds DIRECTLY)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Hello, how are you?\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    print(f"    │")
    print(f"    ├─→ [LLM RECEIVES] Message: \"Hello, how are you?\"")
    print(f"    │   Tools available: {[t['name'] for t in tools]}")

    response = await assistant.chat("Hello, how are you?")

    print(f"    │")
    print(f"    └─→ [LLM DECIDES] Respond directly (no tool needed)")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ Assistant's LLM responded DIRECTLY (no tools)")

    # Cleanup
    analyst.request_shutdown()
    analyst_task.cancel()
    try: await analyst_task
    except asyncio.CancelledError: pass

    print("\n" + "="*70)
    print("ASSISTANT LLM DEMO COMPLETE!")
    print("="*70)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 4: ASSISTANT AS FULL LLM-POWERED MESH PARTICIPANT")
    print("="*60)

    print("\n[Framework Integration]")
    t = TestFrameworkIntegration()
    t.test_inherits_from_agent()
    print("✓ Inherits from Agent")
    t.test_has_required_attributes()
    print("✓ Has role and capabilities")

    mesh1 = Mesh(mode="p2p")
    t.test_can_be_added_to_mesh(mesh1)
    print("✓ Can be added to mesh")

    print("\n[Local Tools]")
    mesh2 = Mesh(mode="p2p")
    assistant = mesh2.add(ConnectedAssistant)
    t2 = TestLocalTools()
    t2.test_search_works(assistant)
    print("✓ search() works")
    t2.test_calculate_works(assistant)
    print("✓ calculate() works")
    t2.test_get_tools_returns_local_tools(assistant)
    print("✓ get_tools() returns local tools")

    print("\n[Peer Tools Integration]")
    mesh3 = Mesh(mode="p2p")
    assistant3 = mesh3.add(ConnectedAssistant)
    assistant3.peers = PeerClient(
        coordinator=None,
        agent_id=assistant3.agent_id,
        agent_role=assistant3.role,
        agent_registry=mesh3._agent_registry,
        node_id="local"
    )

    class TempAnalyst(Agent):
        role = "analyst"
        capabilities = ["analysis"]
        async def execute_task(self, task): return {}

    other = mesh3.add(TempAnalyst)
    other.peers = PeerClient(
        coordinator=None,
        agent_id=other.agent_id,
        agent_role=other.role,
        agent_registry=mesh3._agent_registry,
        node_id="local"
    )

    tools = assistant3.get_tools()
    tool_names = [t["name"] for t in tools]
    assert "ask_peer" in tool_names
    assert "broadcast_update" in tool_names
    assert "list_peers" in tool_names
    print(f"✓ get_tools() includes peer tools: {tool_names}")

    print("\n[Bidirectional Communication]")
    asyncio.run(_run_integration_test())

    print("\n" + "="*60)
    print("ALL TESTS PASSED!")
    print("="*60)
    print("""
KEY INSIGHT: Every agent is a FULL MESH PARTICIPANT

  The assistant can:
  ├── Use LOCAL tools (search, calculate)
  ├── SEND to peers (ask_peer → analyst)
  ├── RECEIVE from peers (requester → assistant)
  └── BROADCAST to all (broadcast_update)

  SAME PATTERN as the analyst!
  The role ("assistant") defines what it's GOOD at,
  NOT whether it sends or receives.
""")

    # Run LLM tool-use demo
    asyncio.run(demo_assistant_llm_flow())

    print("""
═══════════════════════════════════════════════════════════════════════════════
KEY INSIGHT: ASSISTANT LLM TOOL-USE DECISIONS
═══════════════════════════════════════════════════════════════════════════════

  The Assistant's LLM sees tools and DECIDES:

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  "search for X"     → Use LOCAL tool (search)                           │
  │  "calculate X"      → Use LOCAL tool (calculate)                        │
  │  "analyze X"        → Use PEER tool (ask_peer → analyst)                │
  │  "hello"            → Respond DIRECTLY (no tool needed)                 │
  └─────────────────────────────────────────────────────────────────────────┘

  The Assistant is GOOD at search/calculate, but can delegate analysis!
═══════════════════════════════════════════════════════════════════════════════
""")
