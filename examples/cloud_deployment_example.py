"""
Cloud Deployment Example (v0.3.0)

Demonstrates agent self-registration with join_mesh() and leave_mesh().
Agents join an existing mesh independently - no central orchestrator needed.

This is the pattern for:
- Docker containers where each container runs one agent
- Kubernetes pods with auto-scaling
- Cloud Functions / Lambda
- Any distributed deployment where agents start independently

Usage:
    # Terminal 1: Start a mesh (or use an existing one)
    python examples/customagent_p2p_example.py

    # Terminal 2: Run standalone agent that joins the mesh
    JARVISCORE_SEED_NODES=127.0.0.1:7946 python examples/cloud_deployment_example.py

Environment Variables:
    JARVISCORE_SEED_NODES: Comma-separated seed nodes (e.g., "host1:7946,host2:7946")
    JARVISCORE_MESH_ENDPOINT: Single mesh endpoint (alternative to seed_nodes)
"""
import asyncio
import os
import signal
import sys

sys.path.insert(0, '.')

from jarviscore.profiles import ListenerAgent


class StandaloneProcessor(ListenerAgent):
    """
    Example standalone agent that joins mesh independently.

    This agent:
    - Self-registers with the mesh on startup
    - Listens for peer requests
    - Shows its view of the mesh (cognitive context)
    - Gracefully leaves mesh on shutdown
    """

    role = "standalone_processor"
    capabilities = ["standalone", "processing", "example"]
    description = "Processes requests from other mesh agents (standalone deployment)"

    async def on_peer_request(self, msg):
        """Handle incoming requests from other agents."""
        print(f"\n[{self.role}] Received request from {msg.sender}:")
        print(f"  Data: {msg.data}")

        # Process the request
        task = msg.data.get("task", "")
        result = {
            "status": "success",
            "output": f"Processed: {task}",
            "agent_id": self.agent_id,
            "processed_by": self.role
        }

        print(f"[{self.role}] Sending response: {result}")
        return result

    async def on_peer_notify(self, msg):
        """Handle incoming notifications from other agents."""
        print(f"\n[{self.role}] Received notification from {msg.sender}:")
        print(f"  Event: {msg.data.get('event', 'unknown')}")
        print(f"  Data: {msg.data}")


async def main():
    print("=" * 60)
    print("Standalone Agent Example - Cloud Deployment Pattern")
    print("=" * 60)

    # Check for mesh connection info
    endpoint = os.environ.get("JARVISCORE_MESH_ENDPOINT")
    seed_nodes = os.environ.get("JARVISCORE_SEED_NODES")

    if not endpoint and not seed_nodes:
        print("\nNo mesh endpoint configured!")
        print("\nSet one of:")
        print("  - JARVISCORE_MESH_ENDPOINT (single endpoint)")
        print("  - JARVISCORE_SEED_NODES (comma-separated list)")
        print("\nExample:")
        print("  JARVISCORE_SEED_NODES=127.0.0.1:7946 python cloud_deployment_example.py")
        print("\nTo start a mesh first, run:")
        print("  python examples/customagent_p2p_example.py")
        return

    print(f"\nConnecting to mesh via: {endpoint or seed_nodes}")

    # Create agent
    agent = StandaloneProcessor()

    # Join the mesh
    print(f"\nJoining mesh...")
    try:
        await agent.join_mesh()
    except Exception as e:
        print(f"Failed to join mesh: {e}")
        return

    print(f"\nSuccessfully joined mesh!")
    print(f"  Agent ID: {agent.agent_id}")
    print(f"  Role: {agent.role}")
    print(f"  Capabilities: {agent.capabilities}")

    # Show discovered peers
    print(f"\n--- Discovered Peers ---")
    peers = agent.peers.list_peers()
    if peers:
        for p in peers:
            location = f" ({p.get('location', 'unknown')})" if 'location' in p else ""
            print(f"  - {p['role']}: {p['capabilities']}{location}")
    else:
        print("  No other peers discovered yet")

    # Show cognitive context (what an LLM would see)
    print(f"\n--- Cognitive Context for LLM ---")
    print(agent.peers.get_cognitive_context())

    # Setup graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler():
        print("\n\nShutdown requested (Ctrl+C)...")
        agent.request_shutdown()
        shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    print(f"\n--- Agent Running ---")
    print("Listening for peer requests...")
    print("Press Ctrl+C to stop.\n")

    # Run agent (ListenerAgent's run() handles the message loop)
    try:
        await agent.run()
    except asyncio.CancelledError:
        pass

    # Leave mesh gracefully
    print("\nLeaving mesh...")
    await agent.leave_mesh()
    print("Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
