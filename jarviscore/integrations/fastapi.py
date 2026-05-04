"""
FastAPI integration for JarvisCore.

Reduces boilerplate from ~100 lines to 3 lines for integrating
JarvisCore agents with FastAPI applications.

Example:
    from fastapi import FastAPI
    from jarviscore.integrations.fastapi import JarvisLifespan

    agent = MyAgent()
    app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p", bind_port=7950))

    @app.get("/peers")
    async def get_peers(request: Request):
        agent = request.app.state.jarvis_agents.get("my_role")
        return {"peers": agent.peers.list_peers()}
"""
from contextlib import asynccontextmanager
from typing import Union, List, TYPE_CHECKING
import asyncio
import logging

if TYPE_CHECKING:
    from jarviscore.core.agent import Agent

logger = logging.getLogger(__name__)


class JarvisLifespan:
    """
    FastAPI lifespan manager for JarvisCore agents.

    Handles the complete lifecycle of JarvisCore mesh integration:
    - Mesh initialization on startup
    - Background task management for agent run() loops
    - Graceful shutdown with proper cleanup
    - State injection into FastAPI app for handler access

    Args:
        agents: Single agent instance or list of agents to run
        mode: Mesh mode - "p2p", "distributed", or "autonomous"
        **mesh_config: Additional Mesh configuration options:
            - bind_host: P2P bind address (default: "127.0.0.1")
            - bind_port: P2P bind port (default: 7946)
            - seed_nodes: Comma-separated seed nodes for joining cluster
            - node_name: Node identifier for P2P network

    Example - Single Agent:
        from fastapi import FastAPI, Request
        from jarviscore.integrations.fastapi import JarvisLifespan
        from jarviscore.profiles import CustomAgent

        class MyAgent(CustomAgent):
            role = "processor"
            capabilities = ["processing"]

            async def on_peer_request(self, msg):
                return {"processed": msg.data}

        agent = MyAgent()
        app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p", bind_port=7950))

        @app.get("/health")
        async def health(request: Request):
            mesh = request.app.state.jarvis_mesh
            return {"status": "ok", "mesh_started": mesh._started}

    Example - Multiple Agents:
        agents = [ProcessorAgent(), AnalyzerAgent()]
        app = FastAPI(lifespan=JarvisLifespan(agents, mode="p2p"))

    Example - Joining Existing Cluster:
        app = FastAPI(lifespan=JarvisLifespan(
            agent,
            mode="p2p",
            seed_nodes="192.168.1.10:7946,192.168.1.11:7946"
        ))
    """

    def __init__(
        self,
        agents: Union['Agent', List['Agent']],
        **mesh_config
    ):
        """
        Initialize JarvisLifespan.

        Args:
            agents: Single agent or list of agents to run
            **mesh_config: Additional Mesh configuration forwarded to Mesh(config=...)
        """
        self.agents = agents if isinstance(agents, list) else [agents]
        self.mesh_config = mesh_config
        self.mesh = None
        self._background_tasks: List[asyncio.Task] = []
        self._nodes: List['Agent'] = []

    @asynccontextmanager
    async def __call__(self, app):
        """
        ASGI lifespan context manager.

        Called by FastAPI/Starlette on app startup/shutdown.
        Manages the complete mesh lifecycle.
        """
        from jarviscore import Mesh

        # ─────────────────────────────────────────────────────────────
        # STARTUP
        # ─────────────────────────────────────────────────────────────
        logger.info("JarvisLifespan: Starting mesh...")

        # 1. Create mesh with provided configuration
        # Mode is intentionally not passed — Mesh auto-detects infrastructure at start() time.
        self.mesh = Mesh(config=self.mesh_config)

        # 2. Register all agents with the mesh
        self._nodes = []
        for agent in self.agents:
            node = self.mesh.add(agent)
            self._nodes.append(node)
            logger.debug(f"JarvisLifespan: Registered agent {node.role}")

        # 3. Start mesh (initializes P2P coordinator, injects PeerClients)
        await self.mesh.start()
        logger.info(f"JarvisLifespan: Mesh started with {len(self._nodes)} agent(s)")

        # 4. Launch agent run() loops as background tasks
        # This is crucial - without backgrounding, the HTTP server would hang
        for node in self._nodes:
            if hasattr(node, 'run') and asyncio.iscoroutinefunction(node.run):
                task = asyncio.create_task(
                    self._run_agent_with_error_handling(node),
                    name=f"jarvis-agent-{node.agent_id}"
                )
                self._background_tasks.append(task)
                logger.info(f"JarvisLifespan: Started background loop for {node.role}")

        # 5. Inject state into FastAPI app for handler access
        app.state.jarvis_mesh = self.mesh
        app.state.jarvis_agents = {node.role: node for node in self._nodes}

        logger.info("JarvisLifespan: Startup complete")

        # ─────────────────────────────────────────────────────────────
        # APP RUNS HERE
        # ─────────────────────────────────────────────────────────────
        try:
            yield
        finally:
            # ─────────────────────────────────────────────────────────────
            # SHUTDOWN
            # ─────────────────────────────────────────────────────────────
            logger.info("JarvisLifespan: Shutting down...")

            # 1. Request shutdown for all agents (signals run() loops to exit)
            for node in self._nodes:
                node.request_shutdown()

            # 2. Cancel background tasks gracefully with timeout
            for task in self._background_tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await asyncio.wait_for(task, timeout=5.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

            # 3. Stop mesh (cleanup P2P coordinator, call agent teardown)
            if self.mesh:
                await self.mesh.stop()

            logger.info("JarvisLifespan: Shutdown complete")

    async def _run_agent_with_error_handling(self, agent: 'Agent'):
        """
        Run agent loop with error handling and logging.

        Wraps the agent's run() method to catch and log errors
        without crashing the entire application.
        """
        try:
            await agent.run()
        except asyncio.CancelledError:
            logger.debug(f"Agent {agent.agent_id} loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Agent {agent.agent_id} loop error: {e}", exc_info=True)
            # Re-raise to allow task to be marked as failed
            raise


def create_jarvis_app(
    agent: 'Agent',
    title: str = "JarvisCore Agent",
    description: str = "API powered by JarvisCore",
    version: str = "1.0.0",
    **mesh_config
) -> 'FastAPI':
    """
    Create a FastAPI app with JarvisCore integration pre-configured.

    Convenience function for simple single-agent deployments.
    For more control, use JarvisLifespan directly.

    The Mesh auto-detects its operational mode from available infrastructure
    at startup — no mode argument is needed or accepted.

    Args:
        agent: Agent instance to run
        title: FastAPI app title
        description: FastAPI app description
        version: API version
        **mesh_config: Mesh configuration options (e.g. redis_url, p2p_enabled)

    Returns:
        Configured FastAPI app with JarvisCore integration

    Example:
        from jarviscore.integrations.fastapi import create_jarvis_app
        from jarviscore.profiles import CustomAgent

        class MyAgent(CustomAgent):
            role = "processor"
            capabilities = ["processing"]

            async def on_peer_request(self, msg):
                return {"result": "processed"}

        app = create_jarvis_app(MyAgent(), bind_port=7950)

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        # Run with: uvicorn myapp:app --host 0.0.0.0 --port 8000
    """
    from fastapi import FastAPI

    return FastAPI(
        title=title,
        description=description,
        version=version,
        lifespan=JarvisLifespan(agent, **mesh_config)
    )
