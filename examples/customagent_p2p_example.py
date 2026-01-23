"""
CustomAgent P2P Mode Example

Demonstrates LLM-DRIVEN PEER COMMUNICATION where:
- Agents have their own LLM for reasoning
- Peer tools (ask_peer, broadcast) are added to the LLM's toolset
- The LLM AUTONOMOUSLY decides when to ask other agents for help

KEY PATTERN:
    1. Add peer tools to get_tools() → LLM sees them
    2. Route tool execution in execute_tool() → handles peer calls
    3. Update system prompt → tells LLM about peer capabilities
    4. LLM decides → "I need analysis help, let me ask the analyst"

This is ideal for:
- Autonomous agent swarms
- Real-time collaborative systems
- Agents that intelligently delegate tasks

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
# LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class LLMClient:
    """
    LLM client with tool calling support.
    Replace with your actual LLM client (OpenAI, Anthropic, etc.)
    """

    def __init__(self):
        self.available = False
        self.client = None
        self.model = None

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
            print(f"[LLM] Initialized with model: {self.model}")
        except Exception as e:
            print(f"[LLM] Not available: {e} - using mock responses")

    def chat_with_tools(
        self,
        messages: list,
        tools: list,
        system: str = None,
        max_tokens: int = 1024
    ) -> dict:
        """
        Chat with LLM and tools.

        Returns:
            {"type": "text", "content": "..."} or
            {"type": "tool_use", "tool_name": "...", "tool_args": {...}, "tool_use_id": "..."}
        """
        if not self.available:
            # Mock response for testing without API key
            user_msg = ""
            for msg in messages:
                if isinstance(msg.get("content"), str):
                    user_msg = msg.get("content", "").lower()

            if "analyze" in user_msg or "analysis" in user_msg or "trend" in user_msg:
                return {
                    "type": "tool_use",
                    "tool_name": "ask_peer",
                    "tool_args": {"role": "analyst", "question": user_msg},
                    "tool_use_id": "mock_id_001"
                }
            if "search" in user_msg:
                return {
                    "type": "tool_use",
                    "tool_name": "web_search",
                    "tool_args": {"query": user_msg},
                    "tool_use_id": "mock_id_002"
                }
            return {"type": "text", "content": f"Hello! How can I help you today?"}

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

        # Make the API call
        response = self.client.messages.create(**request_kwargs)

        # Parse response - check for tool_use first
        result = {"stop_reason": response.stop_reason}

        for block in response.content:
            if block.type == "tool_use":
                result["type"] = "tool_use"
                result["tool_name"] = block.name
                result["tool_args"] = block.input
                result["tool_use_id"] = block.id
                return result  # Return immediately on tool use
            elif block.type == "text":
                result["type"] = "text"
                result["content"] = block.text

        return result

    def continue_with_tool_result(
        self,
        messages: list,
        tool_use_id: str,
        tool_name: str,
        tool_args: dict,
        tool_result: str,
        tools: list = None,
        system: str = None
    ) -> dict:
        """
        Continue conversation after tool execution.

        This properly formats the assistant's tool use and the tool result.
        """
        if not self.available:
            return {"type": "text", "content": f"Based on the {tool_name} result: {tool_result[:100]}..."}

        # Build new messages with tool use and result
        new_messages = messages + [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": tool_name,
                        "input": tool_args
                    }
                ]
            },
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

        # Continue the conversation
        return self.chat_with_tools(new_messages, tools or [], system)


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYST AGENT - Specialist in data analysis
# ═══════════════════════════════════════════════════════════════════════════════

class AnalystAgent(CustomAgent):
    """
    Analyst agent - specialist in data analysis.

    This agent:
    1. Listens for incoming requests from peers
    2. Processes requests using its own LLM
    3. Has local tools (statistical_analysis, trend_detection)
    4. Can also ask other peers if needed (via peer tools)
    """
    role = "analyst"
    capabilities = ["analysis", "data_interpretation", "reporting"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None
        self.requests_received = []

    async def setup(self):
        """Initialize LLM client."""
        await super().setup()
        self.llm = LLMClient()
        self._logger.info(f"[{self.role}] Ready with LLM-powered analysis")

    def get_tools(self) -> list:
        """
        Tools available to THIS agent's LLM.

        Includes local analysis tools AND peer tools.
        """
        tools = [
            {
                "name": "statistical_analysis",
                "description": "Run statistical analysis on numeric data (mean, std, variance)",
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

        # ADD PEER TOOLS - analyst can ask other agents if needed
        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute a tool - routes to peer tools or local tools."""
        # PEER TOOLS
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)

        # LOCAL TOOLS
        if tool_name == "statistical_analysis":
            data = args.get("data", "")
            return f"Statistical analysis of '{data}': mean=150.3, std=23.4, variance=547.6, trend=positive"

        if tool_name == "trend_detection":
            data = args.get("data", "")
            return f"Trend analysis of '{data}': Upward trend detected with 92% confidence, growth rate 3.2%"

        return f"Unknown tool: {tool_name}"

    async def process_with_llm(self, query: str) -> str:
        """Process request using LLM with tools."""
        system_prompt = """You are an expert data analyst.
You specialize in analyzing data, finding patterns, and providing insights.
You have tools for statistical analysis and trend detection.
Be concise but thorough in your analysis."""

        # Get tools (excluding peer tools to avoid loops in analyst)
        tools = [t for t in self.get_tools()
                 if t["name"] not in ["ask_peer", "broadcast_update", "list_peers"]]

        messages = [{"role": "user", "content": query}]
        response = self.llm.chat_with_tools(messages, tools, system_prompt)

        # Handle tool use
        if response.get("type") == "tool_use":
            tool_name = response["tool_name"]
            tool_args = response["tool_args"]
            tool_use_id = response["tool_use_id"]

            tool_result = await self.execute_tool(tool_name, tool_args)

            response = self.llm.continue_with_tool_result(
                messages, tool_use_id, tool_name, tool_args, tool_result, tools, system_prompt
            )

        return response.get("content", "Analysis complete.")

    async def run(self):
        """Main loop - listen for incoming requests."""
        self._logger.info(f"[{self.role}] Starting run loop...")

        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("question", msg.data.get("query", ""))
                    self.requests_received.append(query)

                    # Show receipt
                    print(f"\n    │  ┌─ [ANALYST] Received request from {msg.sender}")
                    print(f"    │  │  Query: {query[:80]}...")

                    # Process with LLM
                    result = await self.process_with_llm(query)

                    # Show response
                    print(f"    │  │  Processing with LLM...")
                    print(f"    │  └─ [ANALYST] Sending response back")

                    await self.peers.respond(msg, {"response": result})
            else:
                await asyncio.sleep(0.1)

    async def execute_task(self, task: dict) -> dict:
        """Required by base class."""
        return {"status": "success", "note": "This agent uses run() for P2P mode"}


# ═══════════════════════════════════════════════════════════════════════════════
# ASSISTANT AGENT - Coordinator that delegates to specialists
# ═══════════════════════════════════════════════════════════════════════════════

class AssistantAgent(CustomAgent):
    """
    Assistant agent - coordinates with specialist agents.

    KEY PATTERN DEMONSTRATED:
    1. Has its own LLM for reasoning
    2. Peer tools (ask_peer, broadcast) are in its toolset
    3. LLM AUTONOMOUSLY decides when to ask other agents
    4. No manual "if analysis_needed: call_analyst()" logic!

    The LLM sees:
    - web_search (local tool)
    - ask_peer (peer tool) ← LLM decides when to use this!
    - broadcast_update (peer tool)
    - list_peers (peer tool)
    """
    role = "assistant"
    capabilities = ["chat", "coordination", "search"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None
        self.tool_calls = []  # Track what tools LLM uses

    async def setup(self):
        """Initialize LLM client."""
        await super().setup()
        self.llm = LLMClient()
        self._logger.info(f"[{self.role}] Ready with LLM + peer tools")

    def get_tools(self) -> list:
        """
        Tools available to THIS agent's LLM.

        IMPORTANT: This includes PEER TOOLS!
        The LLM sees ask_peer, broadcast_update, list_peers
        and decides when to use them autonomously.
        """
        # Local tools
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

        # ═══════════════════════════════════════════════════════════════════════
        # KEY: ADD PEER TOOLS TO LLM'S TOOLSET
        #
        # This is the core pattern! After this, LLM will see:
        # - ask_peer: Ask another agent by role
        # - broadcast_update: Send message to all peers
        # - list_peers: See available agents and their capabilities
        #
        # The LLM decides when to use these based on the user's request.
        # ═══════════════════════════════════════════════════════════════════════
        if self.peers:
            tools.extend(self.peers.as_tool().schema)

        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """
        Execute a tool by name.

        When LLM decides to use ask_peer, this routes to the peer system.
        No manual delegation logic - just routing!
        """
        self.tool_calls.append({"tool": tool_name, "args": args})

        # PEER TOOLS - route to peer system
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)

        # LOCAL TOOLS
        if tool_name == "web_search":
            query = args.get("query", "")
            return f"Search results for '{query}': Found 10 relevant articles about {query}."

        return f"Unknown tool: {tool_name}"

    async def chat(self, user_message: str) -> str:
        """
        Complete LLM chat with autonomous tool use.

        The LLM sees ALL tools (including peer tools) and decides
        which to use. If user asks for analysis, LLM will use
        ask_peer to contact the analyst - we don't hardcode this!
        """
        # System prompt tells LLM about its capabilities
        system_prompt = """You are a helpful assistant with access to specialist agents.

YOUR TOOLS:
- web_search: Search the web for information
- ask_peer: Ask specialist agents for help. Available specialists:
  * analyst: Expert in data analysis, statistics, and trends
- broadcast_update: Send updates to all connected agents
- list_peers: See what other agents are available

IMPORTANT GUIDELINES:
- When users ask for DATA ANALYSIS, USE ask_peer to ask the analyst
- When users ask for WEB INFORMATION, USE web_search
- Be concise and helpful in your responses
- Always explain what you found from specialists"""

        tools = self.get_tools()
        messages = [{"role": "user", "content": user_message}]

        self._logger.info(f"[{self.role}] Processing: {user_message[:50]}...")
        self._logger.info(f"[{self.role}] Tools available: {[t['name'] for t in tools]}")

        # Call LLM with tools - IT decides which to use
        response = self.llm.chat_with_tools(messages, tools, system_prompt)

        # Handle tool use loop (LLM might use multiple tools)
        iterations = 0
        while response.get("type") == "tool_use" and iterations < 3:
            iterations += 1
            tool_name = response["tool_name"]
            tool_args = response["tool_args"]
            tool_use_id = response["tool_use_id"]

            print(f"\n    ┌─ [ASSISTANT LLM] Decided to use tool: {tool_name}")
            print(f"    │  Args: {tool_args}")

            # Execute the tool (might be ask_peer!)
            tool_result = await self.execute_tool(tool_name, tool_args)

            # Show the result from peer if it was ask_peer
            if tool_name == "ask_peer":
                print(f"    │")
                print(f"    │  ──► [SENT TO ANALYST]")
                print(f"    │")
                print(f"    │  ◄── [ANALYST RESPONDED]:")
                print(f"    │      {tool_result[:200]}...")
            else:
                print(f"    │  Result: {tool_result[:100]}...")

            print(f"    └─ [ASSISTANT LLM] Processing response...")

            # Continue conversation with tool result
            response = self.llm.continue_with_tool_result(
                messages, tool_use_id, tool_name, tool_args, tool_result, tools, system_prompt
            )

        return response.get("content", "I processed your request.")

    async def run(self):
        """Main loop - listen for incoming requests from peers."""
        self._logger.info(f"[{self.role}] Starting run loop...")

        while not self.shutdown_requested:
            if self.peers:
                msg = await self.peers.receive(timeout=0.5)
                if msg and msg.is_request:
                    query = msg.data.get("query", "")
                    result = await self.chat(query)
                    await self.peers.respond(msg, {"response": result})
            else:
                await asyncio.sleep(0.1)

    async def execute_task(self, task: dict) -> dict:
        """Required by base class."""
        return {"status": "success", "note": "This agent uses run() for P2P mode"}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN EXAMPLE
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    """Run CustomAgent P2P mode example with LLM-driven peer communication."""
    print("\n" + "="*70)
    print("JarvisCore: LLM-DRIVEN PEER COMMUNICATION")
    print("="*70)

    print("""
    This example demonstrates the KEY P2P PATTERN:

    ┌─────────────────────────────────────────────────────────────────┐
    │  User: "Analyze the Q4 sales data"                              │
    │                     │                                           │
    │                     ▼                                           │
    │  ┌─────────────────────────────────────────┐                    │
    │  │         ASSISTANT'S LLM                 │                    │
    │  │                                         │                    │
    │  │  Tools: [web_search, ask_peer, ...]     │                    │
    │  │                                         │                    │
    │  │  LLM thinks: "User needs analysis,      │                    │
    │  │  I should ask the analyst agent"        │                    │
    │  │                                         │                    │
    │  │  → Uses ask_peer(role="analyst", ...)   │                    │
    │  └─────────────────────────────────────────┘                    │
    │                     │                                           │
    │                     ▼                                           │
    │  ┌─────────────────────────────────────────┐                    │
    │  │          ANALYST AGENT                  │                    │
    │  │  (Processes with its own LLM + tools)   │                    │
    │  └─────────────────────────────────────────┘                    │
    │                     │                                           │
    │                     ▼ Returns analysis                          │
    │  ┌─────────────────────────────────────────┐                    │
    │  │         ASSISTANT'S LLM                 │                    │
    │  │  "Based on the analyst's findings..."   │                    │
    │  └─────────────────────────────────────────┘                    │
    └─────────────────────────────────────────────────────────────────┘

    The LLM DECIDES to use ask_peer - we don't hardcode this!
    """)

    # Create mesh
    mesh = Mesh(
        mode="p2p",
        config={
            'bind_host': '127.0.0.1',
            'bind_port': 7960,
            'node_name': 'p2p-demo-node',
        }
    )

    # Add agents
    analyst = mesh.add(AnalystAgent)
    assistant = mesh.add(AssistantAgent)

    try:
        await mesh.start()

        print("\n[SETUP] Mesh started in P2P mode")
        print(f"  Agents: {[a.role for a in mesh.agents]}")

        # Show assistant's tools (including peer tools!)
        tools = assistant.get_tools()
        print(f"\n[TOOLS] Assistant's LLM sees these tools:")
        for tool in tools:
            print(f"  - {tool['name']}: {tool['description'][:50]}...")

        # Start analyst's run loop in background
        analyst_task = asyncio.create_task(analyst.run())
        await asyncio.sleep(0.3)

        # ─────────────────────────────────────────────────────────────────
        # TEST 1: Request that should trigger ask_peer → analyst
        # ─────────────────────────────────────────────────────────────────
        print("\n" + "─"*70)
        print("TEST 1: Analysis request (LLM should use ask_peer → analyst)")
        print("─"*70)

        user_message = "Please analyze the Q4 sales trends and identify any anomalies"
        print(f"\n[USER] {user_message}")

        assistant.tool_calls = []  # Reset tracking
        response = await assistant.chat(user_message)

        print(f"\n[ASSISTANT] {response}")
        print(f"\n[TOOLS USED] {assistant.tool_calls}")

        # Verify LLM used ask_peer
        peer_calls = [c for c in assistant.tool_calls if c["tool"] == "ask_peer"]
        if peer_calls:
            print("✓ LLM autonomously decided to ask the analyst!")
        else:
            print("○ LLM responded without asking analyst (might happen with mock)")

        # ─────────────────────────────────────────────────────────────────
        # TEST 2: Request that should use local tool (web_search)
        # ─────────────────────────────────────────────────────────────────
        print("\n" + "─"*70)
        print("TEST 2: Search request (LLM should use web_search)")
        print("─"*70)

        user_message = "Search for the latest Python 3.12 features"
        print(f"\n[USER] {user_message}")

        assistant.tool_calls = []
        response = await assistant.chat(user_message)

        print(f"\n[ASSISTANT] {response}")
        print(f"\n[TOOLS USED] {assistant.tool_calls}")

        search_calls = [c for c in assistant.tool_calls if c["tool"] == "web_search"]
        if search_calls:
            print("✓ LLM used local web_search tool!")

        # ─────────────────────────────────────────────────────────────────
        # TEST 3: Simple greeting (no tools needed)
        # ─────────────────────────────────────────────────────────────────
        print("\n" + "─"*70)
        print("TEST 3: Simple greeting (no tools needed)")
        print("─"*70)

        user_message = "Hello! How are you?"
        print(f"\n[USER] {user_message}")

        assistant.tool_calls = []
        response = await assistant.chat(user_message)

        print(f"\n[ASSISTANT] {response}")
        print(f"\n[TOOLS USED] {assistant.tool_calls}")

        if not assistant.tool_calls:
            print("✓ LLM responded directly without tools!")

        # ─────────────────────────────────────────────────────────────────
        # TEST 4: Analysis with REAL DATA (full bidirectional flow)
        # ─────────────────────────────────────────────────────────────────
        print("\n" + "─"*70)
        print("TEST 4: Analysis with REAL DATA (full flow demonstration)")
        print("─"*70)

        # Actual Q4 sales data with clear anomalies
        q4_sales_data = """
Here is our Q4 2024 monthly sales data:

| Month     | Revenue    | Units Sold | Avg Order Value |
|-----------|------------|------------|-----------------|
| October   | $142,500   | 2,850      | $50.00          |
| November  | $168,300   | 3,366      | $50.00          |
| December  | $312,750   | 4,170      | $75.00          |

Weekly breakdown for December:
- Week 1: $45,200 (normal)
- Week 2: $52,100 (normal)
- Week 3: $185,450 (BLACK FRIDAY + CYBER MONDAY spillover)
- Week 4: $30,000 (post-holiday drop)

Please analyze this data and identify:
1. Key trends
2. Any anomalies
3. Recommendations
"""
        user_message = f"Analyze this Q4 sales data:\n{q4_sales_data}"
        print(f"\n[USER] Providing actual Q4 sales data for analysis...")
        print(q4_sales_data)

        assistant.tool_calls = []
        response = await assistant.chat(user_message)

        print(f"\n[ASSISTANT] {response}")
        print(f"\n[TOOLS USED] {assistant.tool_calls}")

        peer_calls = [c for c in assistant.tool_calls if c["tool"] == "ask_peer"]
        if peer_calls:
            print("✓ Full bidirectional flow completed with real data!")
            print(f"✓ Analyst processed actual sales figures and provided insights!")

        # ─────────────────────────────────────────────────────────────────
        # Summary
        # ─────────────────────────────────────────────────────────────────
        print("\n" + "="*70)
        print("EXAMPLE COMPLETE")
        print("="*70)
        print(f"""
KEY TAKEAWAYS:

1. PEER TOOLS IN TOOLSET
   tools.extend(self.peers.as_tool().schema)

2. LLM DECIDES AUTONOMOUSLY
   - Analysis request → LLM uses ask_peer → analyst
   - Search request → LLM uses web_search
   - Greeting → LLM responds directly
   - Real data analysis → Full bidirectional flow

3. NO HARDCODED DELEGATION
   We don't write: if "analyze" in msg: call_analyst()
   The LLM figures it out from the system prompt!

4. ANALYST RECEIVED: {len(analyst.requests_received)} requests

5. REAL DATA FLOW
   User provides data → Assistant delegates → Analyst analyzes →
   Analyst responds with insights → Assistant presents to user
        """)

        # Cleanup
        analyst.request_shutdown()
        analyst_task.cancel()
        try:
            await analyst_task
        except asyncio.CancelledError:
            pass

        await mesh.stop()

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
