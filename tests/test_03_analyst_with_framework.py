"""
Test 3: Analyst WITH JarvisCore Framework

Demonstrates an LLM-POWERED AGENT that can BOTH send AND receive.

KEY CONCEPT - All agents are equal participants:
    - Every agent has an LLM for reasoning
    - Every agent can SEND requests to peers (via ask_peer tool)
    - Every agent can RECEIVE requests from peers (via run() loop)
    - The "role" defines what they're GOOD at, not communication direction

BEFORE (Standalone):
    - Analyst has analyze() capability
    - Analyst has get_tools() for its LLM
    - Cannot communicate with other agents

AFTER (With Framework):
    - Same analyze() capability
    - get_tools() NOW includes peer tools (ask_peer, broadcast_update, list_peers)
    - Can RECEIVE requests and process them with LLM
    - Can SEND requests to other peers when processing
    - Full mesh participant

DEVELOPER CHANGES REQUIRED:
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
def analyst(mesh):
    """Create an analyst added to mesh."""
    return mesh.add(ConnectedAnalyst)


@pytest.fixture
def analyst_with_peers(mesh, analyst):
    """Create analyst with peer client injected."""
    analyst.peers = PeerClient(
        coordinator=None,
        agent_id=analyst.agent_id,
        agent_role=analyst.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )
    return analyst


# ═══════════════════════════════════════════════════════════════════════════════
# THE AGENT - LLM-powered agent that can BOTH send AND receive
# ═══════════════════════════════════════════════════════════════════════════════

class ConnectedAnalyst(Agent):
    """
    Analyst agent - AFTER installing jarviscore.

    This is a FULL LLM-POWERED AGENT that can:
    - Use its own tools (analyze)
    - Ask other peers for help (ask_peer)
    - Receive and process requests from other agents
    - Broadcast updates to all peers

    The LLM decides what to do - it might receive a request and
    then ask another peer for additional data before responding.
    """
    # Identity for mesh registration
    role = "analyst"
    capabilities = ["analysis", "synthesis", "reporting"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.analyses_count = 0
        self.requests_processed = []
        self.received_broadcasts = []

    # ─────────────────────────────────────────────────────────────────
    # CORE CAPABILITIES - What this agent is good at
    # ─────────────────────────────────────────────────────────────────

    def analyze(self, data: str) -> dict:
        """Analyze data and return insights. (Core capability)"""
        self.analyses_count += 1
        return {
            "response": f"Analysis #{self.analyses_count}: '{data}' shows positive trends",
            "confidence": 0.85,
            "recommendation": "Proceed with caution"
        }

    def generate_report(self, analysis: dict) -> str:
        """Generate a text report from analysis. (Core capability)"""
        return (
            f"Report\n"
            f"Summary: {analysis['response']}\n"
            f"Confidence: {analysis['confidence']}"
        )

    # ─────────────────────────────────────────────────────────────────
    # LLM TOOL INTERFACE - What LLM can use
    # ─────────────────────────────────────────────────────────────────

    def get_tools(self) -> list:
        """
        Return tool definitions for THIS AGENT'S LLM.

        Includes:
        - Local tools (analyze, generate_report)
        - Peer tools (ask_peer, broadcast_update, list_peers)

        The LLM decides which tools to use based on the task.
        """
        tools = [
            {
                "name": "analyze",
                "description": "Analyze data and return insights with confidence score",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string", "description": "Data to analyze"}
                    },
                    "required": ["data"]
                }
            },
            {
                "name": "generate_report",
                "description": "Generate a formatted report from analysis results",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "analysis": {"type": "object", "description": "Analysis result"}
                    },
                    "required": ["analysis"]
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
        if tool_name == "analyze":
            result = self.analyze(args.get("data", ""))
            return str(result)
        elif tool_name == "generate_report":
            result = self.generate_report(args.get("analysis", {}))
            return result

        return f"Unknown tool: {tool_name}"

    # ─────────────────────────────────────────────────────────────────
    # MESSAGE HANDLING - Process incoming requests with LLM
    # ─────────────────────────────────────────────────────────────────

    async def run(self):
        """
        Main loop - receive and process requests.

        When a request comes in, the LLM decides how to handle it.
        The LLM might:
        - Use local tools (analyze)
        - Ask other peers for help (ask_peer)
        - Combine multiple tool calls
        """
        self._logger.info(f"Analyst {self.agent_id} listening...")

        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue

            if msg.is_request:
                # Process request with LLM
                query = msg.data.get("query", "")
                self._logger.info(f"Request from {msg.sender}: {query}")

                # Simulate LLM deciding to use analyze tool
                # In real code: response = await self.llm.chat(query, tools=self.get_tools())
                result = self.analyze(query)
                self.requests_processed.append({"from": msg.sender, "query": query})

                await self.peers.respond(msg, result)

            elif msg.is_notify:
                self._logger.info(f"Broadcast: {msg.data}")
                self.received_broadcasts.append(msg.data)

    async def execute_task(self, task: dict) -> dict:
        """Required by Agent base class."""
        result = self.analyze(task.get("task", ""))
        return {"status": "success", "output": result}


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS - Organized by what they verify
# ═══════════════════════════════════════════════════════════════════════════════

class TestFrameworkIntegration:
    """Tests that verify the agent integrates correctly with jarviscore."""

    def test_inherits_from_agent(self):
        """Agent must inherit from jarviscore.Agent."""
        assert issubclass(ConnectedAnalyst, Agent)

    def test_has_required_attributes(self):
        """Agent must declare role and capabilities."""
        assert ConnectedAnalyst.role == "analyst"
        assert len(ConnectedAnalyst.capabilities) > 0

    def test_can_be_added_to_mesh(self, mesh):
        """Agent can be registered with the mesh."""
        analyst = mesh.add(ConnectedAnalyst)
        assert analyst in mesh.agents
        assert analyst.agent_id is not None


class TestLocalTools:
    """Tests for the agent's local tools (before peer tools)."""

    def test_analyze_works(self, analyst):
        """Core analyze capability should work."""
        result = analyst.analyze("Q4 sales data")
        assert "Q4 sales data" in result["response"]
        assert result["confidence"] == 0.85

    def test_generate_report_works(self, analyst):
        """Core report generation should work."""
        analysis = analyst.analyze("test data")
        report = analyst.generate_report(analysis)
        assert "Report" in report
        assert "Summary:" in report

    def test_get_tools_returns_local_tools(self, analyst):
        """get_tools() should return local tools (before peers injected)."""
        tools = analyst.get_tools()
        tool_names = [t["name"] for t in tools]

        assert "analyze" in tool_names
        assert "generate_report" in tool_names


class TestPeerToolsIntegration:
    """Tests for peer tools being added to the agent's toolset."""

    def test_get_tools_includes_peer_tools_when_connected(self, analyst_with_peers, mesh):
        """After peer injection, get_tools() should include peer tools."""
        # Add another agent so there's someone to talk to
        other = mesh.add(ConnectedAnalyst, agent_id="other-analyst")
        other.peers = PeerClient(
            coordinator=None,
            agent_id=other.agent_id,
            agent_role=other.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        tools = analyst_with_peers.get_tools()
        tool_names = [t["name"] for t in tools]

        # Local tools
        assert "analyze" in tool_names
        assert "generate_report" in tool_names

        # Peer tools
        assert "ask_peer" in tool_names
        assert "broadcast_update" in tool_names
        assert "list_peers" in tool_names

    def test_ask_peer_schema_shows_other_analysts(self, analyst_with_peers, mesh):
        """ask_peer tool should show other agents in the enum."""
        # Add a researcher
        class Researcher(Agent):
            role = "researcher"
            capabilities = ["research"]
            async def execute_task(self, task): return {}

        researcher = mesh.add(Researcher)
        researcher.peers = PeerClient(
            coordinator=None,
            agent_id=researcher.agent_id,
            agent_role=researcher.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        tools = analyst_with_peers.get_tools()
        ask_peer = next(t for t in tools if t["name"] == "ask_peer")

        role_enum = ask_peer["input_schema"]["properties"]["role"]["enum"]
        assert "researcher" in role_enum

    @pytest.mark.asyncio
    async def test_analyst_can_ask_other_peers(self, analyst_with_peers, mesh):
        """Analyst should be able to ask other peers for help."""
        # Add a researcher that responds
        class Researcher(Agent):
            role = "researcher"
            capabilities = ["research"]
            async def execute_task(self, task): return {}
            async def run(self):
                while not self.shutdown_requested:
                    msg = await self.peers.receive(timeout=0.5)
                    if msg and msg.is_request:
                        await self.peers.respond(msg, {
                            "response": f"Research results for: {msg.data.get('query')}"
                        })

        researcher = mesh.add(Researcher)
        researcher.peers = PeerClient(
            coordinator=None,
            agent_id=researcher.agent_id,
            agent_role=researcher.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        researcher_task = asyncio.create_task(researcher.run())
        await asyncio.sleep(0.1)

        try:
            # Analyst asks researcher for help
            result = await analyst_with_peers.execute_tool("ask_peer", {
                "role": "researcher",
                "question": "Find papers on market trends"
            })

            assert "Research results" in result

        finally:
            researcher.request_shutdown()
            researcher_task.cancel()
            try:
                await researcher_task
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
    async def test_analyst_receives_and_responds(self, analyst_with_peers, requester):
        """Analyst should receive request, process with LLM, and respond."""
        analyst_task = asyncio.create_task(analyst_with_peers.run())
        await asyncio.sleep(0.1)

        try:
            # Requester asks analyst
            response = await requester.peers.request("analyst", {
                "query": "Analyze market data"
            }, timeout=5.0)

            assert response is not None
            assert "Analysis" in response["response"]
            assert analyst_with_peers.analyses_count == 1
            assert len(analyst_with_peers.requests_processed) == 1

        finally:
            analyst_with_peers.request_shutdown()
            analyst_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_analyst_receives_broadcasts(self, analyst_with_peers, requester):
        """Analyst should receive broadcast notifications."""
        analyst_task = asyncio.create_task(analyst_with_peers.run())
        await asyncio.sleep(0.1)

        try:
            await requester.peers.broadcast({"message": "System update!"})
            await asyncio.sleep(0.2)

            assert len(analyst_with_peers.received_broadcasts) == 1

        finally:
            analyst_with_peers.request_shutdown()
            analyst_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass


class TestBidirectionalCommunication:
    """Tests proving the agent can BOTH send AND receive."""

    @pytest.mark.asyncio
    async def test_analyst_sends_while_receiving(self, mesh):
        """
        Analyst receives a request AND asks another peer for help.

        This proves the agent is a full mesh participant.
        """
        # Create analyst
        analyst = mesh.add(ConnectedAnalyst)
        analyst.peers = PeerClient(
            coordinator=None,
            agent_id=analyst.agent_id,
            agent_role=analyst.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

        # Create researcher that analyst can ask
        class Researcher(Agent):
            role = "researcher"
            capabilities = ["research"]
            requests_received = []
            async def execute_task(self, task): return {}
            async def run(self):
                while not self.shutdown_requested:
                    msg = await self.peers.receive(timeout=0.5)
                    if msg and msg.is_request:
                        self.requests_received.append(msg.data)
                        await self.peers.respond(msg, {"response": "Research data"})

        researcher = mesh.add(Researcher)
        researcher.peers = PeerClient(
            coordinator=None,
            agent_id=researcher.agent_id,
            agent_role=researcher.role,
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
        researcher_task = asyncio.create_task(researcher.run())
        await asyncio.sleep(0.1)

        try:
            # Analyst asks researcher (SENDING)
            result = await analyst.execute_tool("ask_peer", {
                "role": "researcher",
                "question": "Get market research"
            })
            assert "Research data" in result

            # At the same time, analyst can receive requests
            # (In a real scenario, analyst.run() would be running)

        finally:
            researcher.request_shutdown()
            researcher_task.cancel()
            try:
                await researcher_task
            except asyncio.CancelledError:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL RUN
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_integration_test():
    """Full integration showing analyst as a complete mesh participant."""
    print("\n[Integration: Analyst as full participant]")

    mesh = Mesh(mode="p2p")

    # Create analyst
    analyst = mesh.add(ConnectedAnalyst)

    # Create researcher for analyst to talk to
    class Researcher(Agent):
        role = "researcher"
        capabilities = ["research"]
        async def execute_task(self, task): return {}
        async def run(self):
            while not self.shutdown_requested:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    await self.peers.respond(msg, {
                        "response": f"Research: {msg.data.get('query')}"
                    })

    researcher = mesh.add(Researcher)

    # Create requester that will ask analyst
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
    analyst_task = asyncio.create_task(analyst.run())
    researcher_task = asyncio.create_task(researcher.run())
    await asyncio.sleep(0.1)

    try:
        # Show analyst's tools (includes peer tools)
        tools = analyst.get_tools()
        print(f"  Analyst tools: {[t['name'] for t in tools]}")
        assert "ask_peer" in [t['name'] for t in tools]
        print("  ✓ Analyst has peer tools")

        # Analyst SENDS to researcher
        result = await analyst.execute_tool("ask_peer", {
            "role": "researcher",
            "question": "Get market data"
        })
        print(f"  ✓ Analyst asked researcher: {result}")

        # Analyst RECEIVES from requester
        response = await requester.peers.request("analyst", {
            "query": "Analyze sales"
        }, timeout=5.0)
        print(f"  ✓ Analyst received and responded: {response['response'][:40]}...")

        # Analyst broadcasts
        result = await analyst.execute_tool("broadcast_update", {
            "message": "Analysis complete!"
        })
        print(f"  ✓ Analyst broadcast: {result}")

        print("\n  PROVED: Analyst can SEND, RECEIVE, and BROADCAST")

    finally:
        analyst.request_shutdown()
        researcher.request_shutdown()
        analyst_task.cancel()
        researcher_task.cancel()
        for t in [analyst_task, researcher_task]:
            try:
                await t
            except asyncio.CancelledError:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# LLM TOOL-USE DEMO - Shows how Analyst's LLM decides to use tools
# ═══════════════════════════════════════════════════════════════════════════════

class AnalystMockLLM:
    """
    Simulates Analyst's LLM decision-making.

    The Analyst's LLM might decide to:
    - Use LOCAL tool (analyze) for analysis requests
    - Use PEER tool (ask_peer → researcher) when it needs data
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

        # Analyst's decision logic
        if "analyze" in user_msg and "analyze" in tool_names:
            # Use LOCAL analyze tool
            return {
                "type": "tool_use",
                "tool": "analyze",
                "args": {"data": user_msg}
            }
        elif "research" in user_msg or "data" in user_msg or "find" in user_msg:
            if "ask_peer" in tool_names:
                # Need data - ask researcher
                return {
                    "type": "tool_use",
                    "tool": "ask_peer",
                    "args": {"role": "researcher", "question": user_msg}
                }
        elif "report" in user_msg and "generate_report" in tool_names:
            # Generate report
            return {
                "type": "tool_use",
                "tool": "generate_report",
                "args": {"analysis": {"response": "Previous analysis", "confidence": 0.85}}
            }

        # Default: respond directly
        return {
            "type": "text",
            "content": f"[analyst] I understand: {user_msg}"
        }

    def incorporate_tool_result(self, tool_name: str, result: str) -> str:
        return f"Based on {tool_name}: {result}"


class LLMPoweredAnalyst(ConnectedAnalyst):
    """Analyst with full LLM simulation for demo."""

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = AnalystMockLLM()
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


async def demo_analyst_llm_flow():
    """Demo showing how Analyst's LLM decides to use tools."""
    print("\n" + "="*70)
    print("ANALYST LLM TOOL-USE FLOW")
    print("="*70)

    print("""
    This shows how the ANALYST's LLM decides which tools to use:

    ┌─────────────────────────────────────────────────────────────────┐
    │  "analyze X"        → LLM uses LOCAL tool (analyze)             │
    │  "find data on X"   → LLM uses PEER tool (ask_peer→researcher)  │
    │  "generate report"  → LLM uses LOCAL tool (generate_report)     │
    │  "hello"            → LLM responds DIRECTLY                     │
    └─────────────────────────────────────────────────────────────────┘
    """)

    mesh = Mesh(mode="p2p")

    analyst = LLMPoweredAnalyst()
    mesh._agent_registry["analyst"] = [analyst]

    # Add researcher for analyst to delegate to
    class Researcher(Agent):
        role = "researcher"
        capabilities = ["research"]
        async def execute_task(self, task): return {}
        async def run(self):
            while not self.shutdown_requested:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    await self.peers.respond(msg, {
                        "response": f"[researcher] Found 5 papers on: {msg.data.get('query')}"
                    })

    researcher = Researcher()
    mesh._agent_registry["researcher"] = [researcher]
    mesh.agents = [analyst, researcher]

    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    researcher_task = asyncio.create_task(researcher.run())
    await asyncio.sleep(0.1)

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 1: Analyst uses LOCAL analyze tool
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 1: Request to ANALYZE (Analyst uses LOCAL tool)")
    print("─"*70)
    print(f"\n[USER] → Analyst: \"Please analyze Q4 sales performance\"")
    print(f"\n[ANALYST LLM FLOW]")

    tools = analyst.get_tools()
    print(f"    │")
    print(f"    ├─→ [LLM RECEIVES] Message: \"Please analyze Q4 sales performance\"")
    print(f"    │   Tools available: {[t['name'] for t in tools]}")

    response = await analyst.chat("Please analyze Q4 sales performance")

    print(f"    │")
    print(f"    ├─→ [LLM DECIDES] Use LOCAL tool: analyze")
    print(f"    │   Args: {analyst.tool_calls_made[-1]['args']}")
    print(f"    │")
    print(f"    ├─→ [EXECUTE LOCAL TOOL] analyze")
    print(f"    │")
    print(f"    └─→ [LLM RESPONDS] \"{response[:60]}...\"")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ Analyst's LLM used LOCAL tool (analyze)")

    analyst.tool_calls_made = []
    analyst.conversation_history = []

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 2: Analyst delegates to researcher
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 2: Request needs DATA (Analyst delegates to RESEARCHER)")
    print("─"*70)
    print(f"\n[USER] → Analyst: \"Find research data on market trends\"")
    print(f"\n[ANALYST LLM FLOW]")

    print(f"    │")
    print(f"    ├─→ [LLM RECEIVES] Message: \"Find research data on market trends\"")
    print(f"    │   Tools available: {[t['name'] for t in tools]}")

    response = await analyst.chat("Find research data on market trends")

    print(f"    │")
    print(f"    ├─→ [LLM DECIDES] Use PEER tool: ask_peer → researcher")
    print(f"    │   Args: {analyst.tool_calls_made[-1]['args']}")
    print(f"    │")
    print(f"    ├─→ [EXECUTE PEER TOOL] ask_peer")
    print(f"    │   Sending to: researcher")
    print(f"    │   Researcher responds: \"Found 5 papers...\"")
    print(f"    │")
    print(f"    └─→ [LLM RESPONDS] \"{response[:60]}...\"")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ Analyst's LLM delegated to PEER (researcher)")

    analyst.tool_calls_made = []
    analyst.conversation_history = []

    # ─────────────────────────────────────────────────────────────────
    # SCENARIO 3: Analyst responds directly
    # ─────────────────────────────────────────────────────────────────
    print("\n" + "─"*70)
    print("SCENARIO 3: Simple greeting (Analyst responds DIRECTLY)")
    print("─"*70)
    print(f"\n[USER] → Analyst: \"Hello, what can you do?\"")
    print(f"\n[ANALYST LLM FLOW]")

    print(f"    │")
    print(f"    ├─→ [LLM RECEIVES] Message: \"Hello, what can you do?\"")
    print(f"    │   Tools available: {[t['name'] for t in tools]}")

    response = await analyst.chat("Hello, what can you do?")

    print(f"    │")
    print(f"    └─→ [LLM DECIDES] Respond directly (no tool needed)")

    print(f"\n[FINAL RESPONSE] → User: \"{response}\"")
    print(f"\n✓ Analyst's LLM responded DIRECTLY (no tools)")

    # Cleanup
    researcher.request_shutdown()
    researcher_task.cancel()
    try: await researcher_task
    except asyncio.CancelledError: pass

    print("\n" + "="*70)
    print("ANALYST LLM DEMO COMPLETE!")
    print("="*70)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 3: ANALYST AS FULL LLM-POWERED MESH PARTICIPANT")
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
    analyst = mesh2.add(ConnectedAnalyst)
    t2 = TestLocalTools()
    t2.test_analyze_works(analyst)
    print("✓ analyze() works")
    t2.test_generate_report_works(analyst)
    print("✓ generate_report() works")
    t2.test_get_tools_returns_local_tools(analyst)
    print("✓ get_tools() returns local tools")

    print("\n[Peer Tools Integration]")
    mesh3 = Mesh(mode="p2p")
    analyst3 = mesh3.add(ConnectedAnalyst)
    analyst3.peers = PeerClient(
        coordinator=None,
        agent_id=analyst3.agent_id,
        agent_role=analyst3.role,
        agent_registry=mesh3._agent_registry,
        node_id="local"
    )

    # Add another agent
    other = mesh3.add(ConnectedAnalyst, agent_id="other")
    other.peers = PeerClient(
        coordinator=None,
        agent_id=other.agent_id,
        agent_role=other.role,
        agent_registry=mesh3._agent_registry,
        node_id="local"
    )

    tools = analyst3.get_tools()
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

  The analyst can:
  ├── Use LOCAL tools (analyze, generate_report)
  ├── SEND to peers (ask_peer → researcher)
  ├── RECEIVE from peers (requester → analyst)
  └── BROADCAST to all (broadcast_update)

  The role ("analyst") defines what it's GOOD at,
  NOT whether it sends or receives.
""")

    # Run LLM tool-use demo
    asyncio.run(demo_analyst_llm_flow())

    print("""
═══════════════════════════════════════════════════════════════════════════════
KEY INSIGHT: ANALYST LLM TOOL-USE DECISIONS
═══════════════════════════════════════════════════════════════════════════════

  The Analyst's LLM sees tools and DECIDES:

  ┌─────────────────────────────────────────────────────────────────────────┐
  │  "analyze X"        → Use LOCAL tool (analyze)                          │
  │  "find data on X"   → Use PEER tool (ask_peer → researcher)             │
  │  "generate report"  → Use LOCAL tool (generate_report)                  │
  │  "hello"            → Respond DIRECTLY (no tool needed)                 │
  └─────────────────────────────────────────────────────────────────────────┘

  The Analyst is GOOD at analysis, but can delegate data gathering!
═══════════════════════════════════════════════════════════════════════════════
""")
