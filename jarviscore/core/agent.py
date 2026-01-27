"""
Agent base class - defines WHAT an agent does (role, capabilities).

This is the foundation of the JarvisCore framework. All agents inherit from this class.

For p2p mode, agents can implement a run() method for their own execution loop
and use self.peers for direct peer-to-peer communication.

For cloud deployment, agents can self-register with a mesh using join_mesh().
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from uuid import uuid4
import asyncio
import logging
import os

if TYPE_CHECKING:
    from jarviscore.p2p import PeerClient
    from jarviscore.p2p.coordinator import P2PCoordinator

logger = logging.getLogger(__name__)


class Agent(ABC):
    """
    Base class for all agents in JarvisCore framework.

    Agents define WHAT they do via class attributes:
    - role: The agent's role identifier
    - capabilities: List of capabilities this agent provides

    Subclasses (Profiles) define HOW they execute tasks.

    Example:
        class MyAgent(PromptDevAgent):
            role = "scraper"
            capabilities = ["web_scraping", "data_extraction"]
            system_prompt = "You are an expert web scraper..."
    """

    # Class attributes - user must define these
    role: str = None
    capabilities: List[str] = []

    def __init__(self, agent_id: Optional[str] = None):
        """
        Initialize agent with validation.

        Args:
            agent_id: Optional unique identifier (auto-generated if not provided)

        Raises:
            ValueError: If role or capabilities are not defined
        """
        # Validate required attributes
        if not self.role:
            raise ValueError(
                f"{self.__class__.__name__} must define 'role' class attribute\n"
                f"Example: role = 'scraper'"
            )

        if not self.capabilities:
            raise ValueError(
                f"{self.__class__.__name__} must define 'capabilities' class attribute\n"
                f"Example: capabilities = ['web_scraping']"
            )

        # Initialize instance attributes
        self.agent_id = agent_id or f"{self.role}-{uuid4().hex[:8]}"
        self._mesh = None  # Set by Mesh when agent is added
        self._logger = logging.getLogger(f"jarviscore.agent.{self.agent_id}")

        # P2P mode support
        self.peers: Optional['PeerClient'] = None  # Injected by Mesh in p2p mode
        self.shutdown_requested: bool = False  # Set True to stop run() loop

        # Cloud deployment support (standalone mode)
        self._standalone_p2p: Optional['P2PCoordinator'] = None
        self._mesh_connected: bool = False

        self._logger.debug(f"Agent initialized: {self.agent_id}")

    @abstractmethod
    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task (implemented by profile subclasses).

        This defines HOW the agent executes tasks. Different profiles implement
        this differently:
        - PromptDevAgent: LLM code generation + sandbox execution
        - MCPAgent: User-defined MCP tool calls

        Args:
            task: Task specification containing:
                - task (str): Task description
                - id (str): Task identifier
                - params (dict, optional): Additional parameters

        Returns:
            Result dictionary containing:
                - status (str): "success" or "failure"
                - output (Any): Task output
                - error (str, optional): Error message if failed
                - tokens_used (int, optional): LLM tokens consumed
                - cost_usd (float, optional): Cost in USD

        Raises:
            NotImplementedError: If subclass doesn't implement this method
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement execute_task()"
        )

    async def setup(self):
        """
        Optional setup hook called when agent joins mesh.

        Override this to perform initialization:
        - Connect to external services
        - Load models
        - Setup resources

        Example:
            async def setup(self):
                await super().setup()
                self.db = await connect_to_database()
        """
        self._logger.info(f"Setting up agent: {self.agent_id}")

    async def teardown(self):
        """
        Optional cleanup hook called when agent leaves mesh.

        Override this to cleanup resources:
        - Close connections
        - Save state
        - Release resources

        Example:
            async def teardown(self):
                await self.db.close()
                await super().teardown()
        """
        self._logger.info(f"Tearing down agent: {self.agent_id}")

    async def run(self):
        """
        Optional execution loop for p2p mode agents.

        Override this for agents that run their own execution loops
        instead of waiting for tasks from the workflow engine.

        The loop should check self.shutdown_requested to know when to stop.

        Example:
            async def run(self):
                while not self.shutdown_requested:
                    # Do agent work
                    result = await self.do_work()

                    # Notify peer
                    await self.peers.notify("analyst", {"done": True, "data": result})

                    # Wait before next cycle
                    await asyncio.sleep(5)
        """
        # Default: do nothing (for task-driven agents)
        pass

    def request_shutdown(self):
        """
        Request the agent to stop its run() loop.

        Called by Mesh during shutdown.
        """
        self.shutdown_requested = True
        self._logger.info(f"Shutdown requested for agent: {self.agent_id}")

    def can_handle(self, task: Dict[str, Any]) -> bool:
        """
        Check if agent can handle a task based on capabilities.

        Args:
            task: Task specification with 'capability' or 'role' key

        Returns:
            True if agent has the required capability

        Example:
            task = {"task": "Scrape website", "role": "scraper"}
            if agent.can_handle(task):
                result = await agent.execute_task(task)
        """
        required = task.get("capability") or task.get("role")
        can_handle = required in self.capabilities or required == self.role

        self._logger.debug(
            f"Can handle task requiring '{required}': {can_handle}"
        )

        return can_handle

    def __repr__(self) -> str:
        """String representation of agent."""
        return (
            f"<{self.__class__.__name__} "
            f"id={self.agent_id} "
            f"role={self.role} "
            f"capabilities={self.capabilities}>"
        )

    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"{self.role} ({self.agent_id})"

    # ─────────────────────────────────────────────────────────────────
    # CLOUD DEPLOYMENT (Standalone Mode)
    # ─────────────────────────────────────────────────────────────────

    async def join_mesh(
        self,
        endpoint: str = None,
        seed_nodes: str = None,
        config: dict = None
    ) -> bool:
        """
        Self-register with a running mesh (for cloud/container deployment).

        Instead of using mesh.add(), agents can join an existing mesh
        independently. This is the pattern for containerized deployments
        where each container runs a single agent.

        Args:
            endpoint: Mesh endpoint (host:port) - uses JARVISCORE_MESH_ENDPOINT env if not provided
            seed_nodes: Comma-separated seed nodes - uses JARVISCORE_SEED_NODES env if not provided
            config: Additional P2P configuration options

        Returns:
            True if successfully joined the mesh

        Raises:
            ValueError: If no endpoint or seed_nodes provided and not in environment

        Example - Direct:
            agent = MyAgent()
            await agent.join_mesh(seed_nodes="192.168.1.10:7946")
            await agent.run()
            await agent.leave_mesh()

        Example - Environment Variable:
            # Set JARVISCORE_SEED_NODES=192.168.1.10:7946
            agent = MyAgent()
            await agent.join_mesh()  # Auto-discovers from env
            await agent.run()
            await agent.leave_mesh()

        Example - Docker/K8s:
            # In container entrypoint
            async def main():
                agent = ProcessorAgent()
                await agent.join_mesh()  # Uses env vars
                await agent.run_standalone()  # Handles graceful shutdown
        """
        from jarviscore.p2p.coordinator import P2PCoordinator
        from jarviscore.p2p.peer_client import PeerClient

        # 1. Resolve connection info from args or environment
        endpoint = endpoint or os.environ.get("JARVISCORE_MESH_ENDPOINT")
        seed_nodes = seed_nodes or os.environ.get("JARVISCORE_SEED_NODES", "")

        if not endpoint and not seed_nodes:
            raise ValueError(
                "Must provide endpoint, seed_nodes, or set "
                "JARVISCORE_MESH_ENDPOINT / JARVISCORE_SEED_NODES environment variable"
            )

        # 2. Build P2P configuration - use same config loading as Mesh
        from jarviscore.config import get_config_from_dict
        mesh_config = get_config_from_dict(config)

        # Set seed nodes for joining the cluster
        if endpoint:
            mesh_config["seed_nodes"] = endpoint
        if seed_nodes:
            mesh_config["seed_nodes"] = seed_nodes

        # Find an available port for this agent's P2P listener
        # SWIM doesn't support bind_port=0, so we find a free port
        if "bind_port" not in mesh_config or mesh_config.get("bind_port") == 0:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', 0))
                mesh_config["bind_port"] = s.getsockname()[1]

        mesh_config["node_name"] = f"agent-{self.agent_id}"

        self._logger.info(f"Joining mesh via {endpoint or seed_nodes}...")

        # 3. Setup agent (call setup hook)
        await self.setup()

        # 4. Start standalone P2P coordinator
        self._standalone_p2p = P2PCoordinator([self], mesh_config)
        await self._standalone_p2p.start()

        # 5. Wait for SWIM cluster to converge
        # This allows SWIM gossip to sync membership
        import asyncio
        self._logger.info("Waiting for SWIM cluster convergence...")
        await asyncio.sleep(1.0)  # Brief wait for SWIM gossip

        # 6. Request existing capabilities from peers (we're a late joiner)
        # Note: request_peer_capabilities will wait for ZMQ connections internally
        self._logger.info("Requesting capabilities from existing peers...")
        await self._standalone_p2p.request_peer_capabilities()

        # 7. Announce our own capabilities to mesh
        # Note: announce_capabilities will wait for ZMQ connections internally
        await self._standalone_p2p.announce_capabilities()

        # 7. Setup PeerClient for this agent
        node_id = ""
        if self._standalone_p2p.swim_manager:
            addr = self._standalone_p2p.swim_manager.bind_addr
            if addr:
                node_id = f"{addr[0]}:{addr[1]}"

        self.peers = PeerClient(
            coordinator=self._standalone_p2p,
            agent_id=self.agent_id,
            agent_role=self.role,
            agent_registry={self.role: [self]},
            node_id=node_id
        )

        # Register PeerClient with coordinator for message routing
        self._standalone_p2p.register_peer_client(self.agent_id, self.peers)

        self._mesh_connected = True
        self._logger.info(f"Successfully joined mesh as {self.role} ({self.agent_id})")

        return True

    async def leave_mesh(self) -> bool:
        """
        Gracefully deregister from mesh.

        Called when agent is shutting down to notify other nodes
        that this agent is no longer available.

        Returns:
            True if successfully left the mesh

        Example:
            try:
                await agent.run()
            finally:
                await agent.leave_mesh()
        """
        if not self._mesh_connected:
            return True

        self._logger.info("Leaving mesh...")

        # 1. Deannounce capabilities (notify mesh we're leaving)
        if self._standalone_p2p:
            try:
                await self._standalone_p2p.deannounce_capabilities()
            except Exception as e:
                self._logger.warning(f"Error deannouncing capabilities: {e}")

        # 2. Unregister peer client
        if self._standalone_p2p:
            self._standalone_p2p.unregister_peer_client(self.agent_id)

        # 3. Stop P2P coordinator
        if self._standalone_p2p:
            await self._standalone_p2p.stop()
            self._standalone_p2p = None

        # 4. Teardown agent (call teardown hook)
        await self.teardown()

        self._mesh_connected = False
        self.peers = None
        self._logger.info("Successfully left mesh")

        return True

    @property
    def is_mesh_connected(self) -> bool:
        """Check if agent is currently connected to a mesh."""
        return self._mesh_connected

    async def run_standalone(self):
        """
        Run agent in standalone mode with automatic mesh cleanup.

        Combines run() loop with graceful leave_mesh() on exit.
        Use this as the main entrypoint for containerized agents.

        Example - Container Entrypoint:
            async def main():
                agent = ProcessorAgent()
                await agent.join_mesh()
                await agent.run_standalone()  # Blocks until shutdown

            if __name__ == "__main__":
                asyncio.run(main())
        """
        if not self._mesh_connected:
            raise RuntimeError(
                "Not connected to mesh. Call join_mesh() first."
            )

        try:
            # Run the agent's main loop
            if hasattr(self, 'run') and asyncio.iscoroutinefunction(self.run):
                await self.run()
            else:
                # No run() method - just wait for shutdown signal
                while not self.shutdown_requested:
                    await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            self._logger.info("Agent cancelled, cleaning up...")
        except Exception as e:
            self._logger.error(f"Agent error: {e}")
            raise
        finally:
            # Always leave mesh gracefully
            await self.leave_mesh()
