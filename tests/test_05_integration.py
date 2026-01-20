"""
Test 5: Integration Test - Full Communication Flow

Both agents connected via jarviscore mesh, communicating with each other.
This is the complete developer experience.
"""
import asyncio
import sys
sys.path.insert(0, '.')

from jarviscore.core.agent import Agent
from jarviscore.core.mesh import Mesh
from jarviscore.p2p.peer_client import PeerClient


# ═══════════════════════════════════════════════════════════════════════════════
# CONNECTED ANALYST
# ═══════════════════════════════════════════════════════════════════════════════

class Analyst(Agent):
    """Analyst that receives and responds to peer requests."""
    role = "analyst"
    capabilities = ["analysis", "synthesis"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.analyses_count = 0
        self.received_broadcasts = []

    def analyze(self, data: str) -> dict:
        self.analyses_count += 1
        return {
            "response": f"Analysis #{self.analyses_count}: '{data}' shows positive trends with 15% growth",
            "confidence": 0.87
        }

    async def execute_task(self, task): return {}

    async def run(self):
        """Listen for peer messages."""
        self._logger.info("Analyst listening...")

        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg is None:
                continue

            if msg.is_request:
                query = msg.data.get("query", "")
                self._logger.info(f"Request from {msg.sender}: {query}")
                result = self.analyze(query)
                await self.peers.respond(msg, result)

            elif msg.is_notify:
                self._logger.info(f"Broadcast from {msg.sender}: {msg.data}")
                self.received_broadcasts.append(msg.data)


# ═══════════════════════════════════════════════════════════════════════════════
# CONNECTED ASSISTANT
# ═══════════════════════════════════════════════════════════════════════════════

class Assistant(Agent):
    """Assistant with local tools + peer communication."""
    role = "assistant"
    capabilities = ["chat", "search", "calculate"]

    def search(self, query: str) -> str:
        return f"Search results for '{query}'"

    def calculate(self, expression: str) -> str:
        try:
            return f"Result: {eval(expression)}"
        except:
            return "Error"

    def get_tools(self) -> list:
        tools = [
            {"name": "search", "description": "Search the web"},
            {"name": "calculate", "description": "Calculate math"}
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, name: str, args: dict) -> str:
        if self.peers and name in ["ask_peer", "broadcast_update", "list_peers"]:
            return await self.peers.as_tool().execute(name, args)
        if name == "search":
            return self.search(args.get("query", ""))
        if name == "calculate":
            return self.calculate(args.get("expression", ""))
        return f"Unknown: {name}"

    async def execute_task(self, task): return {}


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════════

async def test_full_integration():
    """
    Complete integration test:
    1. Create mesh
    2. Add both agents
    3. Inject peer clients
    4. Start analyst listener
    5. Assistant discovers analyst
    6. Assistant asks analyst
    7. Assistant broadcasts to analyst
    8. Verify all communication worked
    """
    print("\n" + "="*60)
    print("INTEGRATION TEST: Full Communication Flow")
    print("="*60)

    # ─────────────────────────────────────────────────────────────
    # STEP 1: Create mesh
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 1] Creating mesh...")
    mesh = Mesh(mode="p2p")
    print(f"✓ Mesh created: mode={mesh.mode.value}")

    # ─────────────────────────────────────────────────────────────
    # STEP 2: Add agents
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 2] Adding agents...")
    assistant = mesh.add(Assistant)
    analyst = mesh.add(Analyst)
    print(f"✓ Added: {assistant.role} ({assistant.agent_id})")
    print(f"✓ Added: {analyst.role} ({analyst.agent_id})")

    # ─────────────────────────────────────────────────────────────
    # STEP 3: Inject peer clients (mesh.start() does this)
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 3] Injecting peer clients...")
    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=None,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )
    print(f"✓ Assistant has peers: {assistant.peers is not None}")
    print(f"✓ Analyst has peers: {analyst.peers is not None}")

    # ─────────────────────────────────────────────────────────────
    # STEP 4: Start analyst listener
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 4] Starting analyst listener...")
    analyst_task = asyncio.create_task(analyst.run())
    await asyncio.sleep(0.1)
    print("✓ Analyst is listening for requests")

    # ─────────────────────────────────────────────────────────────
    # STEP 5: Assistant discovers analyst
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 5] Assistant discovers peers...")
    tools = assistant.get_tools()
    tool_names = [t["name"] for t in tools]
    print(f"✓ Assistant tools: {tool_names}")

    peers = assistant.peers.list_peers()
    print(f"✓ Discovered peers: {[p['role'] for p in peers]}")

    result = await assistant.execute_tool("list_peers", {})
    print(f"✓ list_peers result:\n{result}")

    # ─────────────────────────────────────────────────────────────
    # STEP 6: Assistant asks analyst (request-response)
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 6] Assistant asks analyst...")
    result = await assistant.execute_tool("ask_peer", {
        "role": "analyst",
        "question": "Analyze Q4 sales data"
    })
    print(f"✓ ask_peer result: {result}")
    print(f"✓ Analyst analyses done: {analyst.analyses_count}")

    # Ask again
    result2 = await assistant.execute_tool("ask_peer", {
        "role": "analyst",
        "question": "Analyze market trends"
    })
    print(f"✓ ask_peer result 2: {result2}")
    print(f"✓ Analyst analyses done: {analyst.analyses_count}")

    # ─────────────────────────────────────────────────────────────
    # STEP 7: Assistant broadcasts to all
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 7] Assistant broadcasts update...")
    result = await assistant.execute_tool("broadcast_update", {
        "message": "All tasks complete!"
    })
    print(f"✓ broadcast result: {result}")

    await asyncio.sleep(0.2)  # Let analyst receive
    print(f"✓ Analyst received broadcasts: {len(analyst.received_broadcasts)}")

    # ─────────────────────────────────────────────────────────────
    # STEP 8: Verify everything worked
    # ─────────────────────────────────────────────────────────────
    print("\n[Step 8] Verification...")

    # Assertions
    assert "ask_peer" in tool_names, "Should have ask_peer tool"
    assert "broadcast_update" in tool_names, "Should have broadcast_update tool"
    assert "list_peers" in tool_names, "Should have list_peers tool"
    assert analyst.analyses_count == 2, "Analyst should have done 2 analyses"
    assert len(analyst.received_broadcasts) == 1, "Analyst should have 1 broadcast"

    print("✓ All assertions passed!")

    # ─────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────
    print("\n[Cleanup]...")
    analyst.request_shutdown()
    analyst_task.cancel()
    try:
        await analyst_task
    except asyncio.CancelledError:
        pass
    print("✓ Cleanup complete")

    # ─────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("INTEGRATION TEST PASSED!")
    print("="*60)
    print("""
Communication Summary:
  1. Assistant discovered Analyst via list_peers
  2. Assistant asked Analyst twice via ask_peer → got responses
  3. Assistant broadcast update → Analyst received it

What the framework provided:
  - Mesh for agent registration
  - PeerClient injection (self.peers)
  - PeerTool for LLM tool integration (self.peers.as_tool())
  - Automatic message routing between agents
""")


async def test_simulated_llm_conversation():
    """
    Simulate what happens when an LLM uses the peer tools.

    This shows the actual developer experience - LLM decides to use tools.
    """
    print("\n" + "="*60)
    print("SIMULATED LLM CONVERSATION")
    print("="*60)

    # Setup
    mesh = Mesh(mode="p2p")
    assistant = mesh.add(Assistant)
    analyst = mesh.add(Analyst)

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

    # ─────────────────────────────────────────────────────────────
    # Simulate LLM conversation
    # ─────────────────────────────────────────────────────────────

    print("\n--- Turn 1: User asks for analysis ---")
    print("User: Please analyze the Q4 sales data and give me a summary")
    print()

    # LLM sees tools including ask_peer
    tools = assistant.get_tools()
    print(f"LLM sees tools: {[t['name'] for t in tools]}")

    # LLM decides to use ask_peer
    print("LLM thinks: I need analysis capability. Let me check who can help.")
    result = await assistant.execute_tool("list_peers", {})
    print(f"LLM calls list_peers: {result}")

    print("LLM thinks: Found analyst! Let me ask them.")
    result = await assistant.execute_tool("ask_peer", {
        "role": "analyst",
        "question": "Analyze Q4 sales data and provide summary"
    })
    print(f"LLM calls ask_peer: {result}")

    print("LLM responds to user: Based on the analyst's findings,")
    print(f"                      {result}")

    print("\n--- Turn 2: User asks to notify team ---")
    print("User: Great! Please let everyone know the analysis is done.")
    print()

    print("LLM thinks: I should broadcast this update.")
    result = await assistant.execute_tool("broadcast_update", {
        "message": "Q4 analysis complete - positive trends with 15% growth!"
    })
    print(f"LLM calls broadcast_update: {result}")

    print("LLM responds: Done! I've notified all team members.")

    # Cleanup
    analyst.request_shutdown()
    analyst_task.cancel()
    try:
        await analyst_task
    except asyncio.CancelledError:
        pass

    print("\n" + "="*60)
    print("SIMULATED CONVERSATION COMPLETE")
    print("="*60)


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    asyncio.run(test_full_integration())
    asyncio.run(test_simulated_llm_conversation())
