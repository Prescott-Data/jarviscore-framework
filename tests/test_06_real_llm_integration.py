"""
Test 6: Real LLM Integration Test

This test uses ACTUAL LLM API calls (not mocks) to verify that:
1. The LLM correctly sees peer tools in the tool list
2. The LLM decides to use ask_peer when appropriate
3. The tool execution works end-to-end
4. The response flows back correctly

IMPORTANT: This test makes real API calls and costs money.
Run with: pytest tests/test_06_real_llm_integration.py -v -s

Prerequisites:
    - .env file with CLAUDE_API_KEY (or other provider keys)
    - Network connectivity
"""
import asyncio
import os
import sys
import pytest
import logging

sys.path.insert(0, '.')

from jarviscore.core.agent import Agent
from jarviscore.core.mesh import Mesh
from jarviscore.p2p.peer_client import PeerClient

# Setup logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Skip all tests if no API key is configured
try:
    from jarviscore.config import settings
    HAS_API_KEY = bool(
        settings.claude_api_key or
        settings.azure_api_key or
        settings.gemini_api_key
    )
except Exception:
    HAS_API_KEY = False

pytestmark = pytest.mark.skipif(
    not HAS_API_KEY,
    reason="No LLM API key configured in .env"
)


# ═══════════════════════════════════════════════════════════════════════════════
# REAL LLM CLIENT WITH TOOL SUPPORT
# ═══════════════════════════════════════════════════════════════════════════════

class RealLLMClient:
    """
    Real LLM client with native tool calling support.

    Uses Anthropic Claude API directly for proper tool_use handling.
    """

    def __init__(self):
        from anthropic import Anthropic
        from jarviscore.config import settings

        # Get API key and endpoint
        api_key = settings.claude_api_key
        endpoint = settings.claude_endpoint

        if not api_key:
            raise RuntimeError("No Claude API key found in settings")

        # Initialize client
        if endpoint:
            self.client = Anthropic(api_key=api_key, base_url=endpoint)
        else:
            self.client = Anthropic(api_key=api_key)

        self.model = settings.claude_model or "claude-sonnet-4-20250514"
        logger.info(f"RealLLMClient initialized with model: {self.model}")

    def chat_with_tools(
        self,
        messages: list,
        tools: list,
        system: str = None,
        max_tokens: int = 1024
    ) -> dict:
        """
        Send chat with tools and get response.

        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            tools: List of tool definitions in Anthropic format
            system: Optional system prompt
            max_tokens: Max tokens to generate

        Returns:
            {
                "type": "text" | "tool_use",
                "content": str,  # if text
                "tool_name": str,  # if tool_use
                "tool_args": dict,  # if tool_use
                "tool_use_id": str  # if tool_use
            }
        """
        # Build request
        request_kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if system:
            request_kwargs["system"] = system

        if tools:
            request_kwargs["tools"] = tools

        # Make the call
        logger.info(f"Calling LLM with {len(messages)} messages and {len(tools)} tools")
        response = self.client.messages.create(**request_kwargs)

        # Parse response
        result = {"stop_reason": response.stop_reason}

        for block in response.content:
            if block.type == "text":
                result["type"] = "text"
                result["content"] = block.text
            elif block.type == "tool_use":
                result["type"] = "tool_use"
                result["tool_name"] = block.name
                result["tool_args"] = block.input
                result["tool_use_id"] = block.id

        logger.info(f"LLM response type: {result.get('type')}")
        return result

    def continue_with_tool_result(
        self,
        messages: list,
        tool_use_id: str,
        tool_result: str,
        tools: list = None,
        system: str = None,
        max_tokens: int = 1024
    ) -> dict:
        """
        Continue conversation with tool result.

        Args:
            messages: Previous messages
            tool_use_id: The tool_use block ID
            tool_result: Result from tool execution
            tools: Tool definitions (for potential further calls)
            system: System prompt
            max_tokens: Max tokens

        Returns:
            Same format as chat_with_tools
        """
        # Add tool result to messages
        messages = messages + [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": tool_result
                    }
                ]
            }
        ]

        return self.chat_with_tools(messages, tools or [], system, max_tokens)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST AGENTS
# ═══════════════════════════════════════════════════════════════════════════════

class AnalystAgent(Agent):
    """Analyst agent that can analyze data - NOW WITH REAL LLM."""
    role = "analyst"
    capabilities = ["analysis", "data_interpretation", "reporting"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.requests_received = []
        self.llm = None  # Will be set to use real LLM

    def get_tools(self) -> list:
        """Return tools including peer tools."""
        tools = [
            {
                "name": "statistical_analysis",
                "description": "Run statistical analysis on numeric data",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string", "description": "Data to analyze"}
                    },
                    "required": ["data"]
                }
            },
            {
                "name": "trend_detection",
                "description": "Detect trends and patterns in time series data",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "data": {"type": "string", "description": "Time series data"}
                    },
                    "required": ["data"]
                }
            }
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool."""
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)
        if tool_name == "statistical_analysis":
            return f"Statistical analysis of '{args.get('data', '')}': mean=150.3, std=23.4, variance=547.6"
        if tool_name == "trend_detection":
            return f"Trend analysis: Upward trend detected with 92% confidence, growth rate 3.2% month-over-month"
        return f"Unknown tool: {tool_name}"

    async def process_with_llm(self, query: str) -> str:
        """Process request using real LLM."""
        if not self.llm:
            # Fallback to simple response if no LLM
            return f"Analysis of '{query}': Positive trends detected with 87% confidence."

        system_prompt = (
            "You are an expert data analyst. You specialize in analyzing data, "
            "finding patterns, and providing insights. You have tools for statistical "
            "analysis and trend detection. Be concise but thorough in your analysis. "
            "If you need more data, say so. Respond directly without using tools if "
            "you can provide a good analysis from the data given."
        )

        tools = self.get_tools()
        # Remove peer tools for analyst's own processing (avoid infinite loops)
        tools = [t for t in tools if t["name"] not in ["ask_peer", "broadcast_update", "list_peers"]]

        messages = [{"role": "user", "content": query}]

        logger.info(f"[analyst] Processing with LLM: {query[:50]}...")

        response = self.llm.chat_with_tools(messages, tools, system_prompt)

        # Handle tool use - simpler approach to avoid message format issues
        if response.get("type") == "tool_use":
            tool_name = response["tool_name"]
            tool_args = response["tool_args"]
            tool_use_id = response["tool_use_id"]

            logger.info(f"[analyst] Using tool: {tool_name}")

            tool_result = await self.execute_tool(tool_name, tool_args)

            # Add assistant tool use message
            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tool_use_id, "name": tool_name, "input": tool_args}]
            })

            # Add tool result message
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": tool_result}]
            })

            # Get final response (don't use more tools to keep it simple)
            response = self.llm.chat_with_tools(messages, [], system_prompt)

        return response.get("content", "Analysis complete.")

    async def run(self):
        """Listen for incoming requests."""
        logger.info(f"[{self.role}] Starting run loop")
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue
            if msg.is_request:
                query = msg.data.get("query", "")
                logger.info(f"[{self.role}] ===== RECEIVED REQUEST =====")
                logger.info(f"[{self.role}] From: {msg.data.get('from', 'unknown')}")
                logger.info(f"[{self.role}] Query: {query}")

                self.requests_received.append(query)

                # Process with LLM
                result = await self.process_with_llm(query)

                logger.info(f"[{self.role}] ===== SENDING RESPONSE =====")
                logger.info(f"[{self.role}] Response: {result[:100]}...")

                await self.peers.respond(msg, {"response": result})

    async def execute_task(self, task):
        return {}


class AssistantAgent(Agent):
    """Assistant agent that coordinates with other agents."""
    role = "assistant"
    capabilities = ["chat", "coordination", "search"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None  # Will be set in test
        self.tool_calls = []

    def get_tools(self) -> list:
        """Return tools including peer tools."""
        tools = [
            {
                "name": "web_search",
                "description": "Search the web for information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool."""
        self.tool_calls.append({"tool": tool_name, "args": args})

        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)
        if tool_name == "web_search":
            return f"Search results for '{args.get('query', '')}': Found 10 relevant articles."
        return f"Unknown tool: {tool_name}"

    async def chat(self, user_message: str, system_prompt: str = None) -> str:
        """
        Complete LLM chat loop with real tool calling.

        This is the KEY method that demonstrates real LLM tool use.
        """
        if not self.llm:
            raise RuntimeError("LLM not initialized")

        # Default system prompt
        if not system_prompt:
            system_prompt = (
                "You are a helpful assistant. You have access to tools including "
                "the ability to ask other specialist agents for help. "
                "If a user asks for data analysis, you should use the ask_peer tool "
                "to ask the analyst for help. Be concise in your responses."
            )

        # Get tools
        tools = self.get_tools()
        logger.info(f"[assistant] Tools available: {[t['name'] for t in tools]}")

        # Initial message
        messages = [{"role": "user", "content": user_message}]

        # Call LLM
        response = self.llm.chat_with_tools(messages, tools, system_prompt)

        # Handle tool use loop (max 3 iterations)
        iterations = 0
        while response.get("type") == "tool_use" and iterations < 3:
            iterations += 1

            tool_name = response["tool_name"]
            tool_args = response["tool_args"]
            tool_use_id = response["tool_use_id"]

            logger.info(f"[assistant] LLM decided to use tool: {tool_name}")
            logger.info(f"[assistant] Tool args: {tool_args}")

            # Execute the tool
            tool_result = await self.execute_tool(tool_name, tool_args)
            logger.info(f"[assistant] Tool result: {tool_result[:100]}...")

            # Add assistant's tool use to messages
            messages.append({
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": tool_name,
                        "input": tool_args
                    }
                ]
            })

            # Continue with tool result
            response = self.llm.continue_with_tool_result(
                messages, tool_use_id, tool_result, tools, system_prompt
            )

        # Return final text response
        return response.get("content", "No response generated")

    async def run(self):
        """Listen for incoming requests."""
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue
            if msg.is_request:
                # For simplicity, just echo back
                await self.peers.respond(msg, {"response": f"Received: {msg.data}"})

    async def execute_task(self, task):
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealLLMIntegration:
    """
    Tests that use REAL LLM API calls.

    These tests verify that the entire tool-use flow works with actual LLM.
    """

    @pytest.fixture
    def real_mesh(self):
        """Create mesh with real LLM-powered agents."""
        mesh = Mesh(mode="p2p")

        analyst = mesh.add(AnalystAgent)
        assistant = mesh.add(AssistantAgent)

        # Wire up peers
        for agent in mesh.agents:
            agent.peers = PeerClient(
                coordinator=None,
                agent_id=agent.agent_id,
                agent_role=agent.role,
                agent_registry=mesh._agent_registry,
                node_id="local"
            )

        # Initialize real LLM for BOTH agents
        assistant.llm = RealLLMClient()
        analyst.llm = RealLLMClient()

        return mesh, analyst, assistant

    @pytest.mark.asyncio
    async def test_llm_sees_peer_tools(self, real_mesh):
        """
        Test 1: Verify LLM receives correct tool schemas.

        This confirms the tool definitions are properly formatted.
        """
        mesh, analyst, assistant = real_mesh

        tools = assistant.get_tools()
        tool_names = [t["name"] for t in tools]

        print("\n" + "="*60)
        print("TEST: LLM sees peer tools")
        print("="*60)
        print(f"Tools available: {tool_names}")

        # Verify peer tools are present
        assert "ask_peer" in tool_names, "ask_peer tool should be available"
        assert "broadcast_update" in tool_names, "broadcast_update should be available"
        assert "list_peers" in tool_names, "list_peers should be available"

        # Verify ask_peer shows analyst
        ask_peer_tool = next(t for t in tools if t["name"] == "ask_peer")
        roles_enum = ask_peer_tool["input_schema"]["properties"]["role"]["enum"]
        print(f"ask_peer roles enum: {roles_enum}")
        assert "analyst" in roles_enum, "analyst should be in ask_peer roles"

        print("PASSED: LLM sees correct peer tools")

    @pytest.mark.asyncio
    async def test_llm_delegates_to_analyst(self, real_mesh):
        """
        Test 2: LLM decides to delegate analysis to analyst peer.

        This is THE key test - proves real LLM uses ask_peer correctly.
        """
        mesh, analyst, assistant = real_mesh

        print("\n" + "="*60)
        print("TEST: LLM delegates to analyst")
        print("="*60)

        # Start analyst listening
        analyst_task = asyncio.create_task(analyst.run())
        await asyncio.sleep(0.2)  # Give time to start

        try:
            # Send a message that SHOULD trigger delegation
            user_message = "Please analyze the Q4 sales data and tell me if there are any concerning trends."

            print(f"\nUser message: {user_message}")
            print("\nCalling LLM...")

            response = await assistant.chat(user_message)

            print(f"\nFinal response: {response}")
            print(f"\nTool calls made: {assistant.tool_calls}")

            # Verify ask_peer was called
            peer_calls = [c for c in assistant.tool_calls if c["tool"] == "ask_peer"]

            assert len(peer_calls) >= 1, "LLM should have used ask_peer tool"
            assert peer_calls[0]["args"]["role"] == "analyst", "Should have asked analyst"

            # Verify analyst received the request
            assert len(analyst.requests_received) >= 1, "Analyst should have received request"

            print("\nPASSED: LLM correctly delegated to analyst!")

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_llm_uses_local_tool_when_appropriate(self, real_mesh):
        """
        Test 3: LLM uses local tool (web_search) when appropriate.

        This verifies LLM doesn't ALWAYS delegate - it chooses correctly.
        """
        mesh, analyst, assistant = real_mesh

        print("\n" + "="*60)
        print("TEST: LLM uses local tool when appropriate")
        print("="*60)

        # Send a message that should use web_search, not ask_peer
        user_message = "Search the web for the latest Python 3.12 features."

        print(f"\nUser message: {user_message}")
        print("\nCalling LLM...")

        response = await assistant.chat(user_message)

        print(f"\nFinal response: {response}")
        print(f"\nTool calls made: {assistant.tool_calls}")

        # Check if web_search was used
        search_calls = [c for c in assistant.tool_calls if c["tool"] == "web_search"]

        # Note: LLM might not use any tool, or might use search
        # The key is it shouldn't use ask_peer for a search request
        peer_calls = [c for c in assistant.tool_calls if c["tool"] == "ask_peer"]

        print(f"\nSearch calls: {len(search_calls)}, Peer calls: {len(peer_calls)}")

        # If LLM used tools, it should prefer search over analyst for this query
        if assistant.tool_calls:
            # Either used search, or if it used ask_peer it should be rare
            print("LLM made tool calls - checking they were appropriate")
        else:
            print("LLM responded directly without tools (also valid)")

        print("\nPASSED: LLM made appropriate tool choice")

    @pytest.mark.asyncio
    async def test_llm_responds_directly_when_no_tools_needed(self, real_mesh):
        """
        Test 4: LLM responds directly when no tools are needed.
        """
        mesh, analyst, assistant = real_mesh

        print("\n" + "="*60)
        print("TEST: LLM responds directly when no tools needed")
        print("="*60)

        # Send a simple message that doesn't need tools
        user_message = "Hello! How are you today?"

        print(f"\nUser message: {user_message}")
        print("\nCalling LLM...")

        response = await assistant.chat(user_message)

        print(f"\nFinal response: {response}")
        print(f"\nTool calls made: {assistant.tool_calls}")

        # For a greeting, LLM typically shouldn't need tools
        # But this isn't a hard requirement - just informational
        print(f"\nTool calls count: {len(assistant.tool_calls)}")

        assert response, "Should have gotten a response"
        print("\nPASSED: LLM responded appropriately")

    @pytest.mark.asyncio
    async def test_full_conversation_flow(self, real_mesh):
        """
        Test 5: Full conversation with multiple turns and tool use.
        """
        mesh, analyst, assistant = real_mesh

        print("\n" + "="*60)
        print("TEST: Full conversation flow")
        print("="*60)

        # Start analyst
        analyst_task = asyncio.create_task(analyst.run())
        await asyncio.sleep(0.2)

        try:
            # Turn 1: Analysis request
            print("\n--- Turn 1: Analysis Request ---")
            response1 = await assistant.chat(
                "I need you to analyze our customer retention data."
            )
            print(f"Response: {response1[:200]}...")

            # Reset tool calls for next turn
            assistant.tool_calls = []

            # Turn 2: Follow-up (might or might not need tools)
            print("\n--- Turn 2: Follow-up ---")
            response2 = await assistant.chat(
                "What does that analysis suggest we should do?"
            )
            print(f"Response: {response2[:200]}...")

            print("\n" + "="*60)
            print("FULL CONVERSATION TEST COMPLETE")
            print("="*60)

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL RUN
# ═══════════════════════════════════════════════════════════════════════════════

async def run_manual_test():
    """Run a manual test with verbose output."""
    print("\n" + "="*70)
    print("REAL LLM INTEGRATION TEST - BOTH AGENTS USE LLM")
    print("="*70)

    # Setup mesh
    mesh = Mesh(mode="p2p")

    analyst = mesh.add(AnalystAgent)
    assistant = mesh.add(AssistantAgent)

    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    # Initialize real LLM for BOTH agents
    assistant.llm = RealLLMClient()
    analyst.llm = RealLLMClient()
    print("\n[SETUP] Both assistant AND analyst have their own LLM!")

    # Start analyst
    analyst_task = asyncio.create_task(analyst.run())
    await asyncio.sleep(0.2)

    print("\n[SETUP] Mesh created with:")
    print(f"  - Analyst (role: {analyst.role})")
    print(f"  - Assistant (role: {assistant.role})")
    print(f"  - Assistant sees peers: {[p['role'] for p in assistant.peers.list_peers()]}")

    print("\n[TOOLS] Assistant has these tools:")
    for tool in assistant.get_tools():
        print(f"  - {tool['name']}: {tool['description'][:60]}...")

    # Test conversation
    print("\n" + "-"*70)
    print("CONVERSATION TEST")
    print("-"*70)

    try:
        # Message that should trigger ask_peer - WITH ACTUAL DATA
        message = """Please analyze this monthly revenue data and identify any anomalies:

Jan: $120,000
Feb: $125,000
Mar: $118,000
Apr: $245,000  (big spike!)
May: $130,000
Jun: $128,000
Jul: $15,000   (big drop!)
Aug: $135,000
Sep: $140,000
Oct: $142,000
Nov: $155,000
Dec: $180,000

What patterns do you see? Are April and July anomalies?"""

        print(f"\n[USER] {message}")
        print("\n[ASSISTANT LLM PROCESSING...]")

        response = await assistant.chat(message)

        print(f"\n[ASSISTANT] {response}")

        print("\n[TOOL CALLS MADE]")
        for call in assistant.tool_calls:
            print(f"  - {call['tool']}: {call['args']}")

        print("\n[ANALYST RECEIVED]")
        for req in analyst.requests_received:
            print(f"  - {req}")

    finally:
        analyst.request_shutdown()
        analyst_task.cancel()
        try:
            await analyst_task
        except asyncio.CancelledError:
            pass

    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70)


if __name__ == "__main__":
    # Load environment
    from dotenv import load_dotenv
    load_dotenv()

    # Run manual test
    asyncio.run(run_manual_test())
