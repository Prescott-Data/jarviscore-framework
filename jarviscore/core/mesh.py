"""
Mesh - Central orchestrator for JarvisCore framework.

The Mesh coordinates agent execution and provides two operational modes:
- Autonomous: Execute multi-step workflows with dependency resolution
- Distributed: Run as P2P service responding to task requests

Day 1: Foundation with agent registration and setup
Day 2: P2P integration for agent discovery and coordination
Day 3: Full workflow orchestration with state management
"""
from typing import List, Dict, Any, Optional, Type
from enum import Enum
import logging

from .agent import Agent

logger = logging.getLogger(__name__)


class MeshMode(Enum):
    """Operational modes for Mesh."""
    AUTONOMOUS = "autonomous"  # Execute workflows locally
    DISTRIBUTED = "distributed"  # Run as P2P service


class Mesh:
    """
    Central orchestrator for JarvisCore agent framework.

    The Mesh manages agent lifecycle, coordinates execution, and provides
    two operational modes:

    1. **Autonomous Mode**: Execute multi-step workflows locally
       - User defines workflow steps with dependencies
       - Mesh routes tasks to capable agents
       - Handles crash recovery and checkpointing

    2. **Distributed Mode**: Run as P2P service
       - Agents join P2P network and announce capabilities
       - Receive and execute tasks from other nodes
       - Coordinate with remote agents for complex workflows

    Example (Autonomous):
        mesh = Mesh(mode="autonomous")
        mesh.add(ScraperAgent)
        mesh.add(ProcessorAgent)

        await mesh.start()
        results = await mesh.workflow("scrape-and-process", [
            {"agent": "scraper", "task": "Scrape example.com"},
            {"agent": "processor", "task": "Process data", "depends_on": [0]}
        ])

    Example (Distributed):
        mesh = Mesh(mode="distributed")
        mesh.add(APIAgent)
        mesh.add(DatabaseAgent)

        await mesh.start()
        await mesh.serve_forever()  # Run as service
    """

    def __init__(
        self,
        mode: str = "autonomous",
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize Mesh orchestrator.

        Args:
            mode: Operational mode ("autonomous" or "distributed")
            config: Optional configuration dictionary:
                - p2p_enabled: Enable P2P networking (default: True for distributed)
                - state_backend: "file", "redis", "mongodb" (default: "file")
                - event_store: Path or connection string for event storage
                - checkpoint_interval: Save checkpoints every N steps (default: 1)
                - max_parallel: Max parallel step execution (default: 5)

        Raises:
            ValueError: If invalid mode specified
        """
        # Validate mode
        try:
            self.mode = MeshMode(mode)
        except ValueError:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be 'autonomous' or 'distributed'"
            )

        self.config = config or {}
        self.agents: List[Agent] = []
        self._agent_registry: Dict[str, List[Agent]] = {}  # role -> list of agents
        self._agent_ids: set = set()  # Track unique agent IDs
        self._capability_index: Dict[str, List[Agent]] = {}  # capability -> agents

        # Components (initialized in start())
        self._p2p_coordinator = None  # Day 2: P2P integration
        self._workflow_engine = None  # Day 3: Workflow orchestration
        self._state_manager = None    # Day 3: State management

        self._started = False
        self._logger = logging.getLogger(f"jarviscore.mesh")

        self._logger.info(f"Mesh initialized in {self.mode.value} mode")

    def add(
        self,
        agent_class: Type[Agent],
        agent_id: Optional[str] = None,
        **kwargs
    ) -> Agent:
        """
        Register an agent with the mesh.

        Args:
            agent_class: Agent class to instantiate (must inherit from Agent)
            agent_id: Optional unique identifier for the agent
            **kwargs: Additional arguments passed to agent constructor

        Returns:
            Instantiated agent instance

        Raises:
            ValueError: If agent with same role already registered
            TypeError: If agent_class doesn't inherit from Agent

        Example:
            mesh = Mesh()
            scraper = mesh.add(ScraperAgent, agent_id="scraper-1")
            processor = mesh.add(ProcessorAgent)
        """
        # Validate agent class
        if not issubclass(agent_class, Agent):
            raise TypeError(
                f"{agent_class.__name__} must inherit from Agent base class"
            )

        # Instantiate agent
        agent = agent_class(agent_id=agent_id, **kwargs)

        # Check for duplicate agent_ids
        if agent.agent_id in self._agent_ids:
            raise ValueError(
                f"Agent with id '{agent.agent_id}' already registered. "
                f"Each agent must have a unique agent_id."
            )

        # If agent_id was NOT explicitly provided (auto-generated),
        # prevent duplicate roles to avoid accidents
        if agent_id is None and agent.role in self._agent_registry:
            raise ValueError(
                f"Agent with role '{agent.role}' already registered. "
                f"Use agent_id parameter to create multiple agents with same role."
            )

        # Link agent to mesh
        agent._mesh = self

        # Register agent
        self.agents.append(agent)
        self._agent_ids.add(agent.agent_id)

        # Register by role (allow multiple agents per role)
        if agent.role not in self._agent_registry:
            self._agent_registry[agent.role] = []
        self._agent_registry[agent.role].append(agent)

        # Index by capabilities
        for capability in agent.capabilities:
            if capability not in self._capability_index:
                self._capability_index[capability] = []
            self._capability_index[capability].append(agent)

        self._logger.info(
            f"Registered agent: {agent.agent_id} "
            f"(role={agent.role}, capabilities={agent.capabilities})"
        )

        return agent

    async def start(self):
        """
        Initialize mesh and setup all registered agents.

        This method:
        1. Calls setup() on all registered agents
        2. Initializes P2P coordinator (distributed mode)
        3. Announces agent capabilities to network (distributed mode)
        4. Initializes workflow engine (autonomous mode)

        Raises:
            RuntimeError: If no agents registered or already started

        Example:
            mesh = Mesh()
            mesh.add(ScraperAgent)
            await mesh.start()  # Agents are now ready
        """
        if self._started:
            raise RuntimeError("Mesh already started. Call stop() first.")

        if not self.agents:
            raise RuntimeError("No agents registered. Use mesh.add() to register agents.")

        self._logger.info("Starting mesh...")

        # Setup all agents
        for agent in self.agents:
            try:
                await agent.setup()
                self._logger.info(f"Agent setup complete: {agent.agent_id}")
            except Exception as e:
                self._logger.error(f"Failed to setup agent {agent.agent_id}: {e}")
                raise

        # Initialize P2P coordinator (Day 2 implementation)
        if self.mode == MeshMode.DISTRIBUTED or self.config.get("p2p_enabled", False):
            self._logger.info("Initializing P2P coordinator...")
            from jarviscore.p2p import P2PCoordinator
            from jarviscore.config import get_config_from_dict

            # Get full config with defaults
            full_config = get_config_from_dict(self.config)

            # Initialize P2P Coordinator
            self._p2p_coordinator = P2PCoordinator(self.agents, full_config)
            await self._p2p_coordinator.start()
            self._logger.info("✓ P2P coordinator started")

            # Announce capabilities to network
            await self._p2p_coordinator.announce_capabilities()
            self._logger.info("✓ Capabilities announced to mesh")

        # Initialize workflow engine (Day 3 implementation)
        if self.mode == MeshMode.AUTONOMOUS:
            self._logger.info("Initializing workflow engine...")
            from jarviscore.orchestration import WorkflowEngine

            # Initialize workflow engine
            self._workflow_engine = WorkflowEngine(
                mesh=self,
                p2p_coordinator=self._p2p_coordinator,
                config=self.config
            )
            await self._workflow_engine.start()
            self._logger.info("✓ Workflow engine started")

        self._started = True
        self._logger.info(
            f"Mesh started successfully with {len(self.agents)} agent(s) "
            f"in {self.mode.value} mode"
        )

    async def workflow(
        self,
        workflow_id: str,
        steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute a multi-step workflow (autonomous mode only).

        Args:
            workflow_id: Unique workflow identifier (for crash recovery)
            steps: List of step specifications, each containing:
                - agent: Agent role or capability to execute step
                - task: Task description
                - depends_on: List of step indices this step depends on (optional)
                - params: Additional parameters (optional)

        Returns:
            List of step results in execution order

        Raises:
            RuntimeError: If mesh not started or not in autonomous mode
            ValueError: If workflow specification is invalid

        Example:
            results = await mesh.workflow("data-pipeline", [
                {
                    "agent": "scraper",
                    "task": "Scrape example.com for product data"
                },
                {
                    "agent": "processor",
                    "task": "Clean and normalize product data",
                    "depends_on": [0]
                },
                {
                    "agent": "storage",
                    "task": "Save to database",
                    "depends_on": [1]
                }
            ])

        DAY 1: Mock implementation (returns placeholder results)
        DAY 3: Full implementation with state management and crash recovery
        """
        if not self._started:
            raise RuntimeError("Mesh not started. Call await mesh.start() first.")

        if self.mode != MeshMode.AUTONOMOUS:
            raise RuntimeError(
                f"workflow() only available in autonomous mode. "
                f"Current mode: {self.mode.value}"
            )

        self._logger.info(f"Executing workflow: {workflow_id} with {len(steps)} step(s)")

        # Execute workflow using workflow engine
        if self._workflow_engine:
            return await self._workflow_engine.execute(workflow_id, steps)
        else:
            # Fallback if workflow engine not initialized
            raise RuntimeError("Workflow engine not initialized")

    async def serve_forever(self):
        """
        Run mesh as a service (distributed mode only).

        Keeps the mesh running indefinitely, processing incoming tasks from
        the P2P network. Handles:
        - Task routing to capable agents
        - Heartbeat/keepalive with P2P network
        - Graceful shutdown on interrupt

        Raises:
            RuntimeError: If mesh not started or not in distributed mode

        Example:
            mesh = Mesh(mode="distributed")
            mesh.add(APIAgent)
            await mesh.start()
            await mesh.serve_forever()  # Blocks until interrupted

        DAY 1: Basic keep-alive loop
        DAY 2: Full P2P integration with task routing
        """
        if not self._started:
            raise RuntimeError("Mesh not started. Call await mesh.start() first.")

        if self.mode != MeshMode.DISTRIBUTED:
            raise RuntimeError(
                f"serve_forever() only available in distributed mode. "
                f"Current mode: {self.mode.value}"
            )

        self._logger.info("Serving requests in distributed mode...")
        self._logger.info("Press Ctrl+C to stop")

        # Run P2P service
        try:
            if self._p2p_coordinator:
                await self._p2p_coordinator.serve()
            else:
                # Fallback if P2P not initialized
                import asyncio
                await asyncio.Event().wait()
        except KeyboardInterrupt:
            self._logger.info("Shutting down...")
            await self.stop()

    async def stop(self):
        """
        Stop mesh and cleanup resources.

        This method:
        1. Calls teardown() on all agents
        2. Disconnects from P2P network (distributed mode)
        3. Saves state and checkpoints
        4. Closes all connections

        Example:
            await mesh.stop()
        """
        if not self._started:
            return

        self._logger.info("Stopping mesh...")

        # Teardown agents
        for agent in self.agents:
            try:
                await agent.teardown()
                self._logger.info(f"Agent teardown complete: {agent.agent_id}")
            except Exception as e:
                self._logger.error(f"Error during agent teardown {agent.agent_id}: {e}")

        # Cleanup P2P coordinator
        if self._p2p_coordinator:
            await self._p2p_coordinator.stop()
            self._logger.info("✓ P2P coordinator stopped")

        # Cleanup workflow engine
        if self._workflow_engine:
            await self._workflow_engine.stop()
            self._logger.info("✓ Workflow engine stopped")

        self._started = False
        self._logger.info("Mesh stopped successfully")

    def _find_agent_for_step(self, step: Dict[str, Any]) -> Optional[Agent]:
        """
        Find agent capable of executing a step.

        Args:
            step: Step specification with 'agent' field (role or capability)

        Returns:
            Agent instance or None if no capable agent found
        """
        required = step.get("agent")
        if not required:
            return None

        # Try exact role match first
        if required in self._agent_registry:
            agents = self._agent_registry[required]
            return agents[0] if agents else None

        # Try capability match
        if required in self._capability_index:
            agents = self._capability_index[required]
            return agents[0] if agents else None

        return None

    def get_agent(self, role: str) -> Optional[Agent]:
        """
        Get first agent by role.

        If multiple agents share the same role, returns the first registered agent.
        Use get_agents_by_role() to get all agents with a specific role.

        Args:
            role: Agent role identifier

        Returns:
            Agent instance or None if not found
        """
        agents = self._agent_registry.get(role, [])
        return agents[0] if agents else None

    def get_agents_by_capability(self, capability: str) -> List[Agent]:
        """
        Get all agents with a specific capability.

        Args:
            capability: Capability identifier

        Returns:
            List of agents with the capability (empty if none found)
        """
        return self._capability_index.get(capability, [])

    def __repr__(self) -> str:
        """String representation of mesh."""
        return (
            f"<Mesh mode={self.mode.value} "
            f"agents={len(self.agents)} "
            f"started={self._started}>"
        )
