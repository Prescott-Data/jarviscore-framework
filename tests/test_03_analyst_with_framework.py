"""
Test 3: Analyst WITH JarvisCore Framework

Same Analyst, but now connected to the mesh.
CAN receive requests from other agents via self.peers.
"""
import asyncio
import sys
sys.path.insert(0, '.')

# Import only what we need (avoid swim dependency)
from jarviscore.core.agent import Agent
from jarviscore.core.mesh import Mesh, MeshMode
from jarviscore.p2p.peer_client import PeerClient
from jarviscore.p2p.messages import PeerInfo, IncomingMessage, MessageType


class ConnectedAnalyst(Agent):
    """
    Analyst agent connected to jarviscore mesh.

    Same capabilities as standalone:
    - Analyze data
    - Generate reports
    - Provide recommendations

    NEW with framework:
    - Can receive requests from other agents
    - Can respond to those requests
    - Has self.peers for P2P communication
    """
    role = "analyst"
    capabilities = ["analysis", "synthesis", "reporting"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.analyses_count = 0

    def analyze(self, data: str) -> dict:
        """Analyze data and return insights."""
        self.analyses_count += 1
        return {
            "response": f"Analysis #{self.analyses_count}: '{data}' shows positive trends",
            "confidence": 0.85,
            "recommendation": "Proceed with caution"
        }

    def generate_report(self, analysis: dict) -> str:
        """Generate a text report from analysis."""
        return (
            f"Report\n"
            f"Summary: {analysis['response']}\n"
            f"Confidence: {analysis['confidence']}"
        )

    async def execute_task(self, task: dict) -> dict:
        """Required by Agent base class."""
        result = self.analyze(task.get("task", ""))
        return {"status": "success", "output": result}

    async def run(self):
        """
        NEW: Listen for peer requests.

        This loop runs continuously, waiting for and responding to
        requests from other agents in the mesh.
        """
        self._logger.info("Analyst listening for peer requests...")

        while not self.shutdown_requested:
            # Wait for incoming message
            msg = await self.peers.receive(timeout=1.0)

            if msg is None:
                continue

            self._logger.info(f"Received {msg.type.value} from {msg.sender}")

            # Handle request - respond with analysis
            if msg.is_request:
                query = msg.data.get("query", "unknown data")
                result = self.analyze(query)
                await self.peers.respond(msg, result)
                self._logger.info(f"Sent response to {msg.sender}")

            # Handle notification - just log it
            elif msg.is_notify:
                self._logger.info(f"Notification: {msg.data}")


# ═══════════════════════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def test_analyst_inherits_from_agent():
    """Analyst inherits from jarviscore Agent."""
    assert issubclass(ConnectedAnalyst, Agent)
    print("✓ Analyst inherits from Agent")


def test_analyst_has_role_and_capabilities():
    """Analyst defines role and capabilities."""
    assert ConnectedAnalyst.role == "analyst"
    assert "analysis" in ConnectedAnalyst.capabilities
    assert "synthesis" in ConnectedAnalyst.capabilities
    print(f"✓ Role: {ConnectedAnalyst.role}")
    print(f"✓ Capabilities: {ConnectedAnalyst.capabilities}")


def test_analyst_can_be_added_to_mesh():
    """Analyst can be added to mesh."""
    mesh = Mesh(mode="p2p")
    analyst = mesh.add(ConnectedAnalyst)

    assert analyst in mesh.agents
    assert analyst.role == "analyst"
    print(f"✓ Added to mesh: {analyst.agent_id}")


def test_analyst_gets_peers_injected():
    """Analyst gets self.peers after injection."""
    mesh = Mesh(mode="p2p")
    analyst = mesh.add(ConnectedAnalyst)

    # Before
    assert analyst.peers is None

    # Inject (mesh.start() does this)
    analyst.peers = PeerClient(
        coordinator=None,
        agent_id=analyst.agent_id,
        agent_role=analyst.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    # After
    assert analyst.peers is not None
    assert analyst.peers.my_role == "analyst"
    print("✓ self.peers injected")
    print(f"  my_role: {analyst.peers.my_role}")
    print(f"  my_id: {analyst.peers.my_id}")


def test_analyst_can_still_analyze():
    """Analyst still has original analyze capability."""
    mesh = Mesh(mode="p2p")
    analyst = mesh.add(ConnectedAnalyst)

    result = analyst.analyze("Q4 sales data")

    assert "Q4 sales data" in result["response"]
    assert result["confidence"] == 0.85
    print(f"✓ Analysis works: {result['response']}")


def test_analyst_has_receive_method():
    """Analyst can now receive messages via self.peers."""
    mesh = Mesh(mode="p2p")
    analyst = mesh.add(ConnectedAnalyst)

    analyst.peers = PeerClient(
        coordinator=None,
        agent_id=analyst.agent_id,
        agent_role=analyst.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    # Has receive capability
    assert hasattr(analyst.peers, 'receive')
    assert hasattr(analyst.peers, 'respond')
    print("✓ Analyst CAN now receive messages")
    print("  - analyst.peers.receive()")
    print("  - analyst.peers.respond()")


async def test_analyst_run_loop():
    """Analyst has a run() loop for listening."""
    mesh = Mesh(mode="p2p")
    analyst = mesh.add(ConnectedAnalyst)

    analyst.peers = PeerClient(
        coordinator=None,
        agent_id=analyst.agent_id,
        agent_role=analyst.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    # Start the run loop
    task = asyncio.create_task(analyst.run())

    # Let it run briefly
    await asyncio.sleep(0.2)

    # Verify it's running
    assert not task.done()
    print("✓ Analyst run() loop is running")

    # Stop it
    analyst.request_shutdown()
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    print("✓ Analyst shutdown cleanly")


async def test_analyst_receives_and_responds():
    """Analyst receives request and sends response."""
    mesh = Mesh(mode="p2p")
    analyst = mesh.add(ConnectedAnalyst)

    # We need a mock sender - create another agent
    class MockSender(Agent):
        role = "sender"
        capabilities = ["sending"]
        async def execute_task(self, task): return {}

    sender = mesh.add(MockSender)

    # Inject peers
    analyst.peers = PeerClient(
        coordinator=None,
        agent_id=analyst.agent_id,
        agent_role=analyst.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )
    sender.peers = PeerClient(
        coordinator=None,
        agent_id=sender.agent_id,
        agent_role=sender.role,
        agent_registry=mesh._agent_registry,
        node_id="local"
    )

    # Start analyst listening
    analyst_task = asyncio.create_task(analyst.run())
    await asyncio.sleep(0.1)

    # Sender sends request to analyst
    response = await sender.peers.request("analyst", {
        "query": "Analyze market data"
    }, timeout=5.0)

    # Verify response
    assert response is not None
    assert "Analysis" in response["response"]
    assert analyst.analyses_count == 1
    print(f"✓ Received response: {response['response']}")

    # Cleanup
    analyst.request_shutdown()
    analyst_task.cancel()
    try:
        await analyst_task
    except asyncio.CancelledError:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST 3: ANALYST WITH JARVISCORE FRAMEWORK")
    print("="*60 + "\n")

    # Sync tests
    test_analyst_inherits_from_agent()
    test_analyst_has_role_and_capabilities()
    test_analyst_can_be_added_to_mesh()
    test_analyst_gets_peers_injected()
    test_analyst_can_still_analyze()
    test_analyst_has_receive_method()

    # Async tests
    print("\n--- Async Tests ---")
    asyncio.run(test_analyst_run_loop())
    asyncio.run(test_analyst_receives_and_responds())

    print("\n" + "-"*60)
    print("Analyst NOW can receive and respond to peer requests!")
    print("")
    print("Before: No way to receive external requests")
    print("After:  self.peers.receive() + self.peers.respond()")
    print("-"*60 + "\n")
