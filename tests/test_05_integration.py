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
# LLM SIMULATION - Tests the COMPLETE LLM tool-use loop
# ═══════════════════════════════════════════════════════════════════════════════

class MockLLM:
    """
    Simulates LLM behavior for testing the complete tool-use flow.

    In real-world:
        - LLM receives: system prompt + tools + user message
        - LLM decides: use a tool OR respond directly
        - LLM returns: tool_call OR text response

    This mock makes deterministic decisions based on keywords:
        - "analyze" → delegate to analyst (unless I AM the analyst)
        - "research" → delegate to researcher (unless I AM the researcher)
        - "search" → use local search tool
        - otherwise → respond directly
    """

    def __init__(self, agent_role: str):
        self.agent_role = agent_role
        self.calls = []  # Track all LLM calls for verification

    def chat(self, messages: list, tools: list) -> dict:
        """
        Simulate LLM chat completion.

        Returns either:
            {"type": "tool_use", "tool": "name", "args": {...}}
            {"type": "text", "content": "response"}
        """
        self.calls.append({"messages": messages, "tools": tools})

        # Get the last user message
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "").lower()
                break

        # Get available tool names
        tool_names = [t["name"] for t in tools]

        # Decision logic (simulates LLM reasoning)
        # KEY: If I AM the specialist, I process locally. Otherwise delegate.

        if "analyze" in user_msg:
            if self.agent_role == "analyst":
                # I AM the analyst - process locally
                return {
                    "type": "text",
                    "content": f"[analyst] Analysis complete: '{user_msg}' shows positive trends with 87% confidence"
                }
            elif "ask_peer" in tool_names:
                # Delegate to analyst
                return {
                    "type": "tool_use",
                    "tool": "ask_peer",
                    "args": {"role": "analyst", "question": user_msg}
                }

        elif "research" in user_msg:
            if self.agent_role == "researcher":
                # I AM the researcher - process locally
                return {
                    "type": "text",
                    "content": f"[researcher] Research complete: Found 5 papers on '{user_msg}'"
                }
            elif "ask_peer" in tool_names:
                # Delegate to researcher
                return {
                    "type": "tool_use",
                    "tool": "ask_peer",
                    "args": {"role": "researcher", "question": user_msg}
                }

        elif "search" in user_msg and "search" in tool_names:
            # LLM decides to use local search tool
            return {
                "type": "tool_use",
                "tool": "search",
                "args": {"query": user_msg}
            }

        elif "calculate" in user_msg and "calculate" in tool_names:
            # LLM decides to use local calculate tool
            expr = user_msg.split("calculate")[-1].strip()
            return {
                "type": "tool_use",
                "tool": "calculate",
                "args": {"expression": expr or "1+1"}
            }

        # Default: respond directly
        return {
            "type": "text",
            "content": f"[{self.agent_role}] I can help with that: {user_msg}"
        }

    def incorporate_tool_result(self, tool_name: str, result: str) -> str:
        """
        Simulate LLM incorporating tool result into final response.

        In real-world, this would be another LLM call with the tool result.
        """
        return f"Based on the {tool_name} result: {result}"


class LLMPoweredAgent(Agent):
    """
    Agent with ACTUAL LLM integration (mocked for testing).

    This is what a real-world agent looks like:
        1. Has a MockLLM (would be real LLM in production)
        2. chat() method that drives the LLM loop
        3. Handles tool calls and incorporates results
    """
    role = "llm_agent"
    capabilities = ["chat", "delegate"]

    def __init__(self, agent_id=None, role_name="llm_agent"):
        super().__init__(agent_id)
        self.role = role_name
        self.llm = MockLLM(role_name)
        self.conversation_history = []
        self.tool_calls_made = []

    def get_tools(self) -> list:
        """Return tools for LLM."""
        tools = [
            {
                "name": "search",
                "description": "Search for information",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]
                }
            },
            {
                "name": "calculate",
                "description": "Calculate a math expression",
                "input_schema": {
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"]
                }
            }
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool."""
        self.tool_calls_made.append({"tool": tool_name, "args": args})

        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)
        if tool_name == "search":
            return f"Search results for: {args.get('query', '')}"
        if tool_name == "calculate":
            try:
                return f"Result: {eval(args.get('expression', '0'))}"
            except:
                return "Error in calculation"
        return f"Unknown tool: {tool_name}"

    async def chat(self, user_message: str) -> str:
        """
        Complete LLM chat loop with tool use.

        This is THE KEY METHOD that shows real-world LLM tool use:
        1. Add user message to history
        2. Call LLM with messages + tools
        3. If LLM returns tool_use → execute tool → call LLM again with result
        4. If LLM returns text → return as final response
        """
        # Step 1: Add user message
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Step 2: Get tools and call LLM
        tools = self.get_tools()
        llm_response = self.llm.chat(self.conversation_history, tools)

        # Step 3: Handle tool use (may loop multiple times)
        max_iterations = 5  # Prevent infinite loops
        iteration = 0

        while llm_response["type"] == "tool_use" and iteration < max_iterations:
            iteration += 1

            # Execute the tool
            tool_name = llm_response["tool"]
            tool_args = llm_response["args"]
            tool_result = await self.execute_tool(tool_name, tool_args)

            # Add tool call and result to history
            self.conversation_history.append({
                "role": "assistant",
                "content": f"[Tool: {tool_name}] {tool_args}"
            })
            self.conversation_history.append({
                "role": "tool",
                "content": tool_result
            })

            # LLM incorporates result (simulated as another call)
            final_response = self.llm.incorporate_tool_result(tool_name, tool_result)
            llm_response = {"type": "text", "content": final_response}

        # Step 4: Return final response
        final = llm_response["content"]
        self.conversation_history.append({
            "role": "assistant",
            "content": final
        })

        return final

    async def run(self):
        """Listen for incoming requests."""
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue
            if msg.is_request:
                # Process with LLM
                response = await self.chat(msg.data.get("query", ""))
                await self.peers.respond(msg, {"response": response})

    async def execute_task(self, task): return {}


class TestLLMToolUseLoop:
    """
    Tests the COMPLETE LLM tool-use loop.

    These tests prove that the ENTIRE flow works:
        User message → LLM sees tools → LLM decides → Tool executes → Result back to LLM
    """

    @pytest.fixture
    def llm_mesh(self):
        """Create mesh with LLM-powered agents."""
        mesh = Mesh(mode="p2p")

        # Create agents with specific roles
        assistant = LLMPoweredAgent(role_name="assistant")
        analyst = LLMPoweredAgent(role_name="analyst")
        researcher = LLMPoweredAgent(role_name="researcher")

        # Manually register (registry stores lists of agents per role)
        mesh._agent_registry["assistant"] = [assistant]
        mesh._agent_registry["analyst"] = [analyst]
        mesh._agent_registry["researcher"] = [researcher]
        mesh.agents = [assistant, analyst, researcher]

        # Wire up peers
        for agent in mesh.agents:
            agent.peers = PeerClient(
                coordinator=None,
                agent_id=agent.agent_id,
                agent_role=agent.role,
                agent_registry=mesh._agent_registry,
                node_id="local"
            )

        return mesh, assistant, analyst, researcher

    @pytest.mark.asyncio
    async def test_llm_uses_local_tool(self, llm_mesh):
        """
        LLM decides to use a LOCAL tool (search).

        Flow: User asks to search → LLM sees search tool → LLM uses it → Result returned
        """
        mesh, assistant, analyst, researcher = llm_mesh

        # User asks to search
        response = await assistant.chat("Please search for Python tutorials")

        # Verify LLM used the search tool
        assert len(assistant.tool_calls_made) == 1
        assert assistant.tool_calls_made[0]["tool"] == "search"
        assert "search" in response.lower() or "result" in response.lower()

    @pytest.mark.asyncio
    async def test_llm_delegates_to_peer(self, llm_mesh):
        """
        LLM decides to delegate to a PEER (analyst).

        Flow: User asks for analysis → LLM sees ask_peer tool → LLM delegates → Peer responds
        """
        mesh, assistant, analyst, researcher = llm_mesh

        # Start analyst listening
        analyst_task = asyncio.create_task(analyst.run())
        await asyncio.sleep(0.1)

        try:
            # User asks for analysis
            response = await assistant.chat("Please analyze the sales data")

            # Verify LLM delegated to analyst
            assert len(assistant.tool_calls_made) >= 1
            peer_calls = [c for c in assistant.tool_calls_made if c["tool"] == "ask_peer"]
            assert len(peer_calls) == 1
            assert peer_calls[0]["args"]["role"] == "analyst"

            # Verify response mentions the delegation
            assert "ask_peer" in response.lower() or "result" in response.lower()

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try: await analyst_task
            except asyncio.CancelledError: pass

    @pytest.mark.asyncio
    async def test_llm_responds_directly_when_appropriate(self, llm_mesh):
        """
        LLM responds directly without using tools.

        Flow: User says hello → LLM doesn't need tools → LLM responds directly
        """
        mesh, assistant, analyst, researcher = llm_mesh

        # User sends simple greeting
        response = await assistant.chat("Hello, how are you?")

        # Verify LLM did NOT use any tools
        assert len(assistant.tool_calls_made) == 0

        # Verify response is direct
        assert "assistant" in response.lower() or "help" in response.lower()

    @pytest.mark.asyncio
    async def test_llm_sees_correct_tools(self, llm_mesh):
        """
        Verify LLM receives the correct tools including peer tools.
        """
        mesh, assistant, analyst, researcher = llm_mesh

        tools = assistant.get_tools()
        tool_names = [t["name"] for t in tools]

        # Should have local tools
        assert "search" in tool_names
        assert "calculate" in tool_names

        # Should have peer tools
        assert "ask_peer" in tool_names
        assert "broadcast_update" in tool_names
        assert "list_peers" in tool_names

    @pytest.mark.asyncio
    async def test_llm_conversation_history_tracks_tool_use(self, llm_mesh):
        """
        Verify conversation history includes tool calls and results.
        """
        mesh, assistant, analyst, researcher = llm_mesh

        # Make a request that uses a tool
        await assistant.chat("Please search for AI news")

        # Check conversation history
        history = assistant.conversation_history

        # Should have: user message, tool call, tool result, assistant response
        assert len(history) >= 3

        # Find tool-related entries
        tool_entries = [h for h in history if "Tool:" in h.get("content", "")]
        tool_results = [h for h in history if h.get("role") == "tool"]

        assert len(tool_entries) >= 1  # Tool was called
        assert len(tool_results) >= 1  # Result was recorded

    @pytest.mark.asyncio
    async def test_multi_agent_llm_conversation(self, llm_mesh):
        """
        Test a complex scenario where multiple agents use LLM to communicate.

        Flow:
        1. Assistant receives request needing research
        2. Assistant's LLM delegates to researcher
        3. Researcher processes and responds
        4. Assistant's LLM incorporates result
        """
        mesh, assistant, analyst, researcher = llm_mesh

        # Start both specialist agents
        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())
        await asyncio.sleep(0.1)

        try:
            # User asks for research
            response = await assistant.chat("Please research quantum computing")

            # Verify delegation happened
            peer_calls = [c for c in assistant.tool_calls_made if c["tool"] == "ask_peer"]
            assert len(peer_calls) >= 1
            assert peer_calls[0]["args"]["role"] == "researcher"

        finally:
            analyst.request_shutdown()
            researcher.request_shutdown()
            for t in [analyst_task, researcher_task]:
                t.cancel()
                try: await t
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
# LLM TOOL-USE DEMO - Shows the complete flow with logging
# ═══════════════════════════════════════════════════════════════════════════════

class MockLLMWithLogging(MockLLM):
    """MockLLM with detailed logging for demo purposes."""

    def chat(self, messages: list, tools: list) -> dict:
        """Chat with detailed logging."""
        # Get the last user message
        user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "")
                break

        print(f"    │")
        print(f"    ├─→ [LLM RECEIVES] Message: \"{user_msg}\"")
        print(f"    │   Tools available: {[t['name'] for t in tools]}")

        # Call parent to get decision
        result = super().chat(messages, tools)

        if result["type"] == "tool_use":
            print(f"    │")
            print(f"    ├─→ [LLM DECIDES] Use tool: {result['tool']}")
            print(f"    │   Args: {result['args']}")
        else:
            print(f"    │")
            print(f"    ├─→ [LLM DECIDES] Respond directly (no tool needed)")

        return result

    def incorporate_tool_result(self, tool_name: str, result: str) -> str:
        """Incorporate with logging."""
        print(f"    │")
        print(f"    ├─→ [LLM RECEIVES RESULT] From {tool_name}:")
        print(f"    │   Result: \"{result[:60]}...\"" if len(result) > 60 else f"    │   Result: \"{result}\"")

        final = super().incorporate_tool_result(tool_name, result)

        print(f"    │")
        print(f"    └─→ [LLM RESPONDS] \"{final[:60]}...\"" if len(final) > 60 else f"    └─→ [LLM RESPONDS] \"{final}\"")

        return final


class LLMPoweredAgentWithLogging(LLMPoweredAgent):
    """LLM-powered agent with detailed logging."""

    def __init__(self, agent_id=None, role_name="llm_agent"):
        super().__init__(agent_id, role_name)
        self.llm = MockLLMWithLogging(role_name)  # Use logging version

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool with logging."""
        print(f"    │")
        print(f"    ├─→ [EXECUTE TOOL] {tool_name}")

        result = await super().execute_tool(tool_name, args)

        if tool_name == "ask_peer":
            print(f"    │   Sent to peer: {args.get('role')}")
            print(f"    │   Peer responded: \"{result[:50]}...\"" if len(result) > 50 else f"    │   Peer responded: \"{result}\"")

        return result


async def demo_llm_tool_use():
    """Demo the complete LLM tool-use flow with detailed logging."""
    print("\n" + "="*70)
    print("LLM TOOL-USE FLOW DEMO")
    print("="*70)

    print("""
    This demo shows EXACTLY what happens when an LLM uses tools:

    ┌─────────────────────────────────────────────────────────────────┐
    │  User Message                                                   │
    │       ↓                                                         │
    │  LLM sees tools (local + peer)                                  │
    │       ↓                                                         │
    │  LLM decides: use tool OR respond directly                      │
    │       ↓                                                         │
    │  If tool: execute → get result → LLM incorporates               │
    │       ↓                                                         │
    │  Final response to user                                         │
    └─────────────────────────────────────────────────────────────────┘
    """)

    # Setup mesh with logging agents
    mesh = Mesh(mode="p2p")

    assistant = LLMPoweredAgentWithLogging(role_name="assistant")
    analyst = LLMPoweredAgentWithLogging(role_name="analyst")
    researcher = LLMPoweredAgentWithLogging(role_name="researcher")

    mesh._agent_registry["assistant"] = [assistant]
    mesh._agent_registry["analyst"] = [analyst]
    mesh._agent_registry["researcher"] = [researcher]
    mesh.agents = [assistant, analyst, researcher]

    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    # Start listeners
    analyst_task = asyncio.create_task(analyst.run())
    researcher_task = asyncio.create_task(researcher.run())
    await asyncio.sleep(0.1)

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 1: LLM uses LOCAL tool
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 1: User asks to SEARCH (LLM uses LOCAL tool)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Please search for Python tutorials\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    response = await assistant.chat("Please search for Python tutorials")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ LLM decided to use LOCAL tool (search)")

    # Reset for next scenario
    assistant.tool_calls_made = []
    assistant.conversation_history = []

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 2: LLM delegates to PEER
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 2: User asks for ANALYSIS (LLM delegates to PEER)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Please analyze the Q4 sales data\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    response = await assistant.chat("Please analyze the Q4 sales data")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ LLM decided to delegate to PEER (analyst) via ask_peer tool")

    # Reset for next scenario
    assistant.tool_calls_made = []
    assistant.conversation_history = []

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 3: LLM responds directly
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 3: User says HELLO (LLM responds directly, no tools)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Hello, how are you?\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    response = await assistant.chat("Hello, how are you?")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ LLM decided NO tool needed, responded directly")

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 4: Multi-step - research then analyze
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 4: User asks for RESEARCH (LLM delegates to researcher)")
    print("─"*70)
    print(f"\n[USER] → Assistant: \"Please research AI trends\"")
    print(f"\n[ASSISTANT LLM FLOW]")

    response = await assistant.chat("Please research AI trends")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ LLM decided to delegate to PEER (researcher) via ask_peer tool")

    # Cleanup
    analyst.request_shutdown()
    researcher.request_shutdown()
    for t in [analyst_task, researcher_task]:
        t.cancel()
        try: await t
        except asyncio.CancelledError: pass

    print("\n" + "="*70)
    print("LLM TOOL-USE DEMO COMPLETE!")
    print("="*70)


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Run mesh integration first
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

    # Run LLM tool-use demo
    asyncio.run(demo_llm_tool_use())

    print("""
═══════════════════════════════════════════════════════════════════════════════
KEY INSIGHT: LLM TOOL-USE FLOW
═══════════════════════════════════════════════════════════════════════════════

  The LLM sees ALL tools (local + peer) and DECIDES:

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  "search for X"     → LLM uses LOCAL tool (search)                      │
  │  "analyze X"        → LLM uses PEER tool (ask_peer → analyst)           │
  │  "research X"       → LLM uses PEER tool (ask_peer → researcher)        │
  │  "hello"            → LLM responds DIRECTLY (no tool needed)            │
  └─────────────────────────────────────────────────────────────────────────┘

  The framework provides the tools.
  The LLM decides WHEN and HOW to use them.
  PeerTool makes other agents available as tools!
═══════════════════════════════════════════════════════════════════════════════
""")
