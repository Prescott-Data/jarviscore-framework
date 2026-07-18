"""
Mesh — Central orchestrator for the JarvisCore agent framework.

The Mesh manages agent lifecycle, enables peer-to-peer communication,
runs workflow orchestration, and adapts to available infrastructure
automatically.  You never specify a "mode" — the Mesh detects what is
reachable (Redis, SWIM) at start() time and activates the right features.

Capabilities (auto-detected, always accurate after start()):
  "workflow"          — WorkflowEngine ready  (always enabled)
  "run_loops"         — Agents with run() are running  (when present)
  "peer_local"        — PeerClient routing via in-process registry  (always)
  "peer_distributed"  — PeerClient routing via Redis pub/sub  (with Redis)
  "peer_swim"         — PeerClient routing via SWIM/ZMQ  (with P2P stack)
  "redis"             — RedisContextStore connected
  "blob"              — BlobStorage connected
  "auth"              — AuthenticationManager active
  "nexus"             — NexusLocalStore ready (when NEXUS_GATEWAY_URL set or NEXUS_ENABLED=true)
  "athena"            — AthenaClient connected (when ATHENA_URL set)
  "prometheus"        — Metrics server running

Usage:
    mesh = Mesh()                    # No mode — auto-detects everything
    mesh.add(ScraperAgent)
    mesh.add(AnalystAgent)           # Can have run() — will be started
    await mesh.start()               # Infrastructure probed, features enabled
    results = await mesh.workflow(   # Workflow engine always available
        "my-pipeline", [...]
    )
    await mesh.run_forever()         # Start run() loops for agents that have them
"""
from typing import List, Dict, Any, Optional, Set
import asyncio
import logging
import warnings

from .agent import Agent

logger = logging.getLogger(__name__)


class MeshMode:  # noqa: N801 (kept as deprecated shim — do not use in new code)
    """
    Deprecated shim — kept only for backward-compatibility imports.

    ``MeshMode`` no longer controls Mesh behaviour.  The Mesh auto-detects
    what infrastructure is available and activates features accordingly.
    Do not pass ``mode=`` when constructing ``Mesh()``.

    If you are importing ``MeshMode`` anywhere, switch to
    ``mesh.has_capability(cap)`` for runtime capability checks.
    """
    AUTONOMOUS  = "autonomous"
    DISTRIBUTED = "distributed"
    P2P         = "p2p"
    AUTO        = "auto"
    LOCAL       = "autonomous"
    MESH        = "auto"

    def __init__(self, value: str = "auto"):
        self.value = value

    def __eq__(self, other):
        if isinstance(other, MeshMode):
            return self.value == other.value
        return self.value == other

    def __hash__(self):
        return hash(self.value)

    def __repr__(self):
        return f"MeshMode({self.value!r})"


class Mesh:
    """
    Central orchestrator for JarvisCore agent framework.

    The Mesh manages agent lifecycle, coordinates execution, and provides
    three operational modes:

    1. **Autonomous Mode**: Execute multi-step workflows locally
       - User defines workflow steps with dependencies
       - Mesh routes tasks to capable agents
       - Handles crash recovery and checkpointing

    2. **Distributed Mode**: Run as P2P service (workflow-driven)
       - Agents join P2P network and announce capabilities
       - Receive and execute tasks from other nodes
       - Coordinate with remote agents for complex workflows

    3. **P2P Mode**: Direct agent-to-agent communication
       - Agents run their own execution loops via run() method
       - Agents communicate directly via self.peers client
       - No workflow engine - agents control their own flow

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
        await mesh.serve_forever()  # Run as workflow service

    Example (P2P):
        mesh = Mesh(mode="p2p")
        mesh.add(ScoutAgent)    # Has run() method
        mesh.add(AnalystAgent)  # Has run() method

        await mesh.start()
        await mesh.run_forever()  # Agents run their own loops
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        **_legacy_kwargs,  # absorbs deprecated mode= kwarg without crashing
    ):
        """
        Initialize Mesh orchestrator.

        Args:
            config: Optional configuration dictionary:
                - redis_url:            Redis connection string (auto-detected from env)
                - p2p_enabled:          bool — enable SWIM/ZMQ peer transport
                - checkpoint_interval:  save checkpoints every N steps (default: 1)
                - max_parallel:         max parallel step execution (default: 5)

        The Mesh detects available infrastructure at ``start()`` time and
        activates features accordingly.  You do not need to specify a mode.
        Pass ``REDIS_URL`` in the environment and the Mesh will use Redis
        automatically in production.
        """
        if _legacy_kwargs.get("mode"):
            warnings.warn(
                "Mesh(mode=...) is deprecated and has no effect. "
                "The Mesh auto-detects infrastructure at start() time. "
                "Remove the mode= argument.",
                DeprecationWarning,
                stacklevel=2,
            )

        self.config: Dict[str, Any] = config or {}

        # Agent registries
        self.agents: List[Agent] = []
        self._agent_registry: Dict[str, List[Agent]] = {}  # role → agents
        self._agent_ids: Set[str] = set()
        self._capability_index: Dict[str, List[Agent]] = {}  # capability → agents

        # Infrastructure components — populated at start()
        self._p2p_coordinator = None
        self._workflow_engine = None
        self._auth_manager    = None
        self._redis_store     = None
        self._settings        = None
        self._blob_storage    = None
        self._nexus_store     = None   # NexusLocalStore — when nexus is configured
        self._athena_client   = None   # AthenaClient — when ATHENA_URL set
        self._distributed_worker_task = None
        self._agent_run_tasks: List[asyncio.Task] = []

        # Capability set — populated at start() based on what's reachable
        # Inspect with mesh.has_capability(cap) or mesh.capabilities
        self._capabilities: Set[str] = set()

        # Deprecated mode shim — reflects detected capabilities after start()
        # Kept so code doing `mesh.mode.value` doesn't crash
        self.mode = MeshMode("auto")

        self._started = False
        self._logger = logging.getLogger("jarviscore.mesh")
        self._logger.info("Mesh created — capabilities will be detected at start()")

    def add(
        self,
        agent_class_or_instance,
        agent_id: Optional[str] = None,
        **kwargs
    ) -> Agent:
        """
        Register an agent with the mesh.

        Args:
            agent_class_or_instance: Agent class to instantiate, or pre-instantiated
                agent (from wrap() function). Must inherit from Agent.
            agent_id: Optional unique identifier for the agent (ignored if instance)
            **kwargs: Additional arguments passed to agent constructor (ignored if instance)

        Returns:
            Agent instance

        Raises:
            ValueError: If agent with same role already registered
            TypeError: If agent doesn't inherit from Agent

        Example:
            mesh = Mesh()

            # Add a class (will be instantiated)
            scraper = mesh.add(ScraperAgent, agent_id="scraper-1")

            # Add a pre-instantiated agent (from wrap())
            wrapped = wrap(my_instance, role="processor", capabilities=["processing"])
            mesh.add(wrapped)
        """
        # Check if it's already an instance (from wrap() function)
        if isinstance(agent_class_or_instance, Agent):
            agent = agent_class_or_instance
        else:
            # It's a class - validate and instantiate
            agent_class = agent_class_or_instance
            if not issubclass(agent_class, Agent):
                raise TypeError(
                    f"{agent_class.__name__} must inherit from Agent base class"
                )
            agent = agent_class(agent_id=agent_id, **kwargs)

        # Check for duplicate agent_ids
        if agent.agent_id in self._agent_ids:
            raise ValueError(
                f"Agent with id '{agent.agent_id}' already registered. "
                f"Each agent must have a unique agent_id."
            )

        # If agent_id was NOT explicitly provided (auto-generated),
        # prevent duplicate roles to avoid accidents
        # For instances (from wrap()), check if it's a new role
        is_instance = isinstance(agent_class_or_instance, Agent)
        if not is_instance and agent_id is None and agent.role in self._agent_registry:
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

        self._logger.info("Starting mesh — probing infrastructure...")

        # ── 1. Infrastructure detection ───────────────────────────────────────
        from jarviscore.config.settings import Settings
        self._settings = Settings()
        self._redis_store = self._init_redis(self._settings)
        self._blob_storage = self._init_blob_storage(self._settings)

        # Nexus: always available (local encrypted store, zero dep)
        self._nexus_store = self._init_nexus()

        # Athena: optional, when ATHENA_URL is set
        self._athena_client = self._init_athena(self._settings)

        if self._redis_store:
            self._capabilities.add("redis")
            self._capabilities.add("peer_distributed")
        if self._blob_storage:
            self._capabilities.add("blob")
        if self._nexus_store:
            self._capabilities.add("nexus")
        if self._athena_client:
            self._capabilities.add("athena")

        # ── 2. Infrastructure injection into agents ───────────────────────────
        # Must happen before agent.setup() so agents can use stores during setup
        self._inject_infrastructure()

        # ── 3. Agent setup ────────────────────────────────────────────────────
        for agent in self.agents:
            try:
                await agent.setup()
                self._logger.info("Agent setup complete: %s", agent.agent_id)
            except Exception as exc:
                self._logger.error("Failed to setup agent %s: %s", agent.agent_id, exc)
                raise

        # ── 4. P2P coordinator (when SWIM is configured) ──────────────────────
        # Merge Settings.p2p_enabled → config so P2P_ENABLED=true in .env works
        # without requiring the developer to pass config={"p2p_enabled": True} to Mesh().
        if self._settings and getattr(self._settings, "p2p_enabled", False):
            self.config.setdefault("p2p_enabled", True)

        if self.config.get("p2p_enabled", False):
            self._logger.info("Initializing P2P coordinator (SWIM)...")
            try:
                from jarviscore.p2p import P2PCoordinator
                from jarviscore.config import get_config_from_dict
                full_config = get_config_from_dict(self.config)
                self._p2p_coordinator = P2PCoordinator(self.agents, full_config)
                await self._p2p_coordinator.start()
                self._capabilities.add("peer_swim")
                self._logger.info("✓ P2P coordinator started")

                # Wait for SWIM to stabilise: if seed_nodes are configured,
                # poll until at least one peer is known (up to 5s); otherwise
                # a short 0.3s pause is enough for single-node scenarios.
                seed_nodes = self.config.get("seed_nodes", "")
                if seed_nodes:
                    deadline = asyncio.get_event_loop().time() + 5.0
                    while asyncio.get_event_loop().time() < deadline:
                        members = getattr(
                            getattr(self._p2p_coordinator, "swim_manager", None),
                            "alive_members", None,
                        )
                        if members:
                            break
                        await asyncio.sleep(0.2)
                else:
                    await asyncio.sleep(0.3)

                await self._p2p_coordinator.announce_capabilities()
                await self._p2p_coordinator.request_peer_capabilities()
                self._logger.info("✓ P2P capabilities announced and exchanged")
            except Exception as exc:
                self._logger.warning("P2P coordinator init failed (continuing without): %s", exc)

        # ── 5. PeerClients — always injected, transport depends on capabilities
        self._inject_peer_clients()
        self._capabilities.add("peer_local")
        self._logger.info(
            "✓ PeerClients injected (transports: %s)",
            ", ".join(c for c in self._capabilities if c.startswith("peer")),
        )

        # ── 6. Authentication (optional, declared via config) ─────────────────
        if self.config.get("auth_mode"):
            try:
                from jarviscore.auth.manager import AuthenticationManager
                self._auth_manager = AuthenticationManager(self.config)
                self._capabilities.add("auth")
                self._logger.info(
                    "✓ AuthenticationManager started (mode=%s)", self.config["auth_mode"]
                )
            except Exception as exc:
                self._logger.warning("Auth manager init failed (continuing without): %s", exc)

        if self._auth_manager:
            injected = sum(
                1 for agent in self.agents
                if getattr(agent, "requires_auth", False)
                and not setattr(agent, "_auth_manager", self._auth_manager)  # type: ignore
            )
            if injected:
                self._logger.info("✓ AuthenticationManager injected into %d agent(s)", injected)

        # ── 7. Workflow engine — ALWAYS started (not mode-gated) ─────────────
        self._logger.info("Initializing workflow engine...")
        try:
            from jarviscore.orchestration import WorkflowEngine
            self._workflow_engine = WorkflowEngine(
                mesh=self,
                p2p_coordinator=self._p2p_coordinator,
                config=self.config,
                redis_store=self._redis_store,
            )
            await self._workflow_engine.start()
            self._capabilities.add("workflow")
            self._logger.info("✓ Workflow engine started")
        except Exception as exc:
            self._logger.warning("WorkflowEngine init failed (continuing without): %s", exc)

        # ── 8. Distributed worker — when Redis is available ───────────────────
        if "redis" in self._capabilities:
            self._distributed_worker_task = asyncio.create_task(
                self._run_distributed_worker(),
                name="distributed-worker",
            )
            self._logger.info("✓ Distributed worker started (Redis-backed step claiming)")

        # ── 9. Prometheus metrics ─────────────────────────────────────────────
        if self._settings and self._settings.prometheus_enabled:
            try:
                from jarviscore.telemetry.metrics import start_prometheus_server
                start_prometheus_server(self._settings.prometheus_port)
                self._capabilities.add("prometheus")
                self._logger.info(
                    "✓ Prometheus metrics on port %d", self._settings.prometheus_port
                )
            except Exception as exc:
                self._logger.warning("Prometheus init failed: %s", exc)

        # ── 10. Update deprecated mode shim for any code that reads mesh.mode ─
        if "peer_swim" in self._capabilities:
            self.mode = MeshMode("p2p")
        elif "redis" in self._capabilities:
            self.mode = MeshMode("distributed")
        else:
            self.mode = MeshMode("autonomous")

        self._started = True
        self._logger.info(
            "Mesh started: %d agent(s) | capabilities: %s",
            len(self.agents),
            ", ".join(sorted(self._capabilities)),
        )

    async def workflow(
        self,
        workflow_id: str,
        steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Execute a multi-step workflow.

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

        """
        if not self._started:
            raise RuntimeError("Mesh not started. Call await mesh.start() first.")

        if not self._workflow_engine:
            raise RuntimeError(
                "Workflow engine not available. This usually means WorkflowEngine "
                "failed to start — check startup logs for the root cause."
            )

        self._logger.info("Executing workflow: %s (%d steps)", workflow_id, len(steps))
        return await self._workflow_engine.execute(workflow_id, steps)

    async def fanout(
        self,
        fanout_id: str,
        *,
        agent: str,
        items: Any,
        task: Any,
        context: Any = None,
        concurrency: int = 5,
        budget: Optional[int] = None,
        on_error: str = "collect",
        timeout: Optional[float] = None,
    ):
        """
        Dynamic fan-out: run one task template over N runtime items with
        bounded concurrency, and aggregate the results explicitly.

        Where workflow() executes a DAG declared upfront, fanout() handles
        the map-shape agent systems hit constantly — scan results, file
        lists, symbol boards — where N is data, not authorship (issue #52).

        Args:
            fanout_id:   Unique id; namespaces every item's step identity so
                         concurrent items cannot cross-contaminate.
            agent:       Role or capability that executes each item.
            items:       Iterable of items — the dynamic N. Order defines
                         result order.
            task:        Task string, or callable ``item -> str``.
            context:     Static dict, or callable ``item -> dict``.
            concurrency: Max items in flight (default 5). Always bounded.
            budget:      Optional cap on items attempted; the remainder is
                         reported in ``result.skipped``, never dropped silently.
            on_error:    "collect" (default) — failures land in ``result.failed``
                         and the rest continue; "fail_fast" — first failure
                         cancels pending items.
            timeout:     Optional per-item timeout in seconds.

        Returns:
            FanoutResult with ``.results`` (item order, each stamped with
            ``item`` and ``step_id``), ``.succeeded``/``.failed`` views,
            ``.skipped``, and explicit reduce helpers ``.aggregate(fn)`` /
            ``.summarize(llm, prompt)``.

        Example:
            result = await mesh.fanout(
                "board-scan",
                agent="analyst",
                items=symbols,
                task=lambda s: f"Deep-read {s} and return a thesis JSON.",
                context=lambda s: {"symbol": s},
                concurrency=5,
                budget=20,
            )
            theses = [r["payload"] for r in result.succeeded]
        """
        if not self._started:
            raise RuntimeError("Mesh not started. Call await mesh.start() first.")

        from jarviscore.orchestration.fanout import run_fanout

        self._logger.info("Executing fanout: %s (agent=%s)", fanout_id, agent)
        return await run_fanout(
            fanout_id=fanout_id,
            find_agent=self._find_agent_for_step,
            agent=agent,
            items=items,
            task=task,
            context=context,
            concurrency=concurrency,
            budget=budget,
            on_error=on_error,
            timeout=timeout,
        )

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
        1. Requests shutdown for all agents (p2p mode)
        2. Calls teardown() on all agents
        3. Disconnects from P2P network
        4. Saves state and checkpoints
        5. Closes all connections

        Example:
            await mesh.stop()
        """
        if not self._started:
            return

        self._logger.info("Stopping mesh...")

        # Request shutdown for all agents (for p2p mode loops)
        for agent in self.agents:
            agent.request_shutdown()

        # Unregister peer clients
        if self._p2p_coordinator:
            for agent in self.agents:
                self._p2p_coordinator.unregister_peer_client(agent.agent_id)

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

        # Phase 7D: Cleanup auth manager
        if self._auth_manager:
            try:
                await self._auth_manager.close()
            except Exception:
                pass
            self._auth_manager = None
            self._logger.info("✓ AuthenticationManager stopped")

        # Cancel distributed worker
        if self._distributed_worker_task and not self._distributed_worker_task.done():
            self._distributed_worker_task.cancel()
            try:
                await self._distributed_worker_task
            except asyncio.CancelledError:
                pass
        self._distributed_worker_task = None

        # Phase 9: Clear infrastructure references
        self._blob_storage = None
        self._settings = None

        self._started = False
        self._logger.info("Mesh stopped successfully")

    # ─────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────
    # Distributed worker (autonomous step claiming across nodes)
    # ─────────────────────────────────────────────────────────────────

    async def _run_distributed_worker(self) -> None:
        """
        Background task: scans active workflows in Redis for pending steps
        that match this node's agent capabilities, claims them atomically
        via SETNX, and executes them.

        Agents declare their capabilities via `role` and `capabilities` — the
        Mesh handles all routing. No manual wiring or step-ID knowledge needed.
        Runs only in distributed mode when a redis_store is available.
        """
        capability_map: Dict[str, Any] = {}
        for agent in self.agents:
            for cap in ([agent.role] + list(getattr(agent, "capabilities", []))):
                if cap and cap not in capability_map:
                    capability_map[cap] = agent

        if not capability_map:
            return

        self._logger.info(
            f"[DistributedWorker] Online | capabilities: {list(capability_map)}"
        )

        while self._started:
            try:
                for workflow_id in self._redis_store.get_active_workflows():
                    for step_id in self._redis_store.get_all_step_ids(workflow_id):
                        step_def = self._redis_store.get_step_definition(
                            workflow_id, step_id
                        )
                        if not step_def or step_def.get("status") != "pending":
                            continue
                        agent = capability_map.get(step_def.get("agent", ""))
                        if not agent:
                            continue
                        # Respect dependencies — only claim when all deps are completed
                        if not self._redis_store.are_dependencies_met(workflow_id, step_id):
                            continue
                        if self._redis_store.claim_step(
                            workflow_id, step_id, agent.agent_id
                        ):
                            self._logger.info(
                                f"[DistributedWorker] Claimed '{step_id}' "
                                f"in '{workflow_id}' → {agent.agent_id}"
                            )
                            asyncio.create_task(
                                self._execute_distributed_step(
                                    agent, workflow_id, step_id, step_def
                                ),
                                name=f"dist-{step_id}",
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._logger.warning(f"[DistributedWorker] Error: {exc}")

            await asyncio.sleep(2.0)

    async def _execute_distributed_step(
        self, agent: Any, workflow_id: str, step_id: str, step_def: dict
    ) -> None:
        """Execute a claimed distributed step and persist the result to Redis."""
        task = {
            "id": step_id,
            "agent": agent.role,
            "task": step_def.get("task", ""),
            "context": {
                "previous_step_results": {},
                "workflow_id": workflow_id,
                "step_id": step_id,
            },
        }
        try:
            result = await agent.execute_task(task)
        except Exception as exc:
            self._logger.error(
                f"[DistributedWorker] '{step_id}' in '{workflow_id}' failed: {exc}"
            )
            self._redis_store.update_step_status(workflow_id, step_id, "failed")
            return

        self._redis_store.save_step_output(workflow_id, step_id, output=result)
        self._redis_store.update_step_status(workflow_id, step_id, "completed")
        s = result.get("status", "?") if isinstance(result, dict) else "done"
        self._logger.info(
            f"[DistributedWorker] '{step_id}' in '{workflow_id}' complete (status={s})"
        )

    # Phase 9: Infrastructure helpers
    # ─────────────────────────────────────────────────────────────────

    def _init_redis(self, settings):
        """
        Init RedisContextStore. Config dict (runtime) overrides Settings (env vars).
        Returns None gracefully when no URL configured or connection fails.
        """
        url = (
            self.config.get("redis_store_url")
            or self.config.get("redis_url")
            or getattr(settings, "redis_url", None)
        )
        if not url:
            return None
        try:
            from types import SimpleNamespace
            from jarviscore.storage.redis_store import RedisContextStore
            _s = SimpleNamespace(
                redis_url=url,
                redis_context_ttl_days=getattr(settings, "redis_context_ttl_days", 7),
            )
            store = RedisContextStore(settings=_s)
            if not store.enabled:
                self._logger.warning("Redis URL configured but connection failed — running without Redis")
                return None
            self._logger.info("✓ RedisContextStore connected")
            return store
        except Exception as exc:
            self._logger.warning(f"Redis store init failed (continuing without): {exc}")
            return None

    def _init_blob_storage(self, settings):
        """Init BlobStorage from settings. Always succeeds (local backend is default)."""
        try:
            from jarviscore.storage import get_blob_storage
            storage = get_blob_storage(settings)
            backend = getattr(settings, "storage_backend", "local")
            self._logger.info(f"✓ BlobStorage initialized ({backend})")
            return storage
        except Exception as exc:
            self._logger.warning(f"BlobStorage init failed (continuing without): {exc}")
            return None

    def _init_nexus(self):
        """
        Init NexusLocalStore — the built-in credential vault.

        Optional: only initialised when nexus is explicitly configured.
        Detection order:
          1. config dict key ``nexus_enabled`` (runtime override)
          2. ``NEXUS_ENABLED`` env var / Settings.nexus_enabled
          3. Auto-detect: enabled when ``NEXUS_GATEWAY_URL`` is set

        Credentials are stored at ~/.jarviscore/nexus.enc, AES-256-GCM
        encrypted.  Agents access via self._nexus_store.build_auth_info()
        or through nexus_call() which the Kernel injects into the sandbox.
        """
        # 1. Explicit runtime config takes priority
        enabled = self.config.get("nexus_enabled")
        # 2. Fall back to settings field
        if enabled is None:
            enabled = getattr(self._settings, "nexus_enabled", None)
        # 3. Auto-detect from gateway URL presence
        if enabled is None:
            enabled = bool(getattr(self._settings, "nexus_gateway_url", None))

        if not enabled:
            self._logger.debug(
                "Nexus store not configured — skipping "
                "(set NEXUS_GATEWAY_URL or NEXUS_ENABLED=true to enable)"
            )
            return None

        try:
            from jarviscore.nexus.store import NexusLocalStore
            store = NexusLocalStore()
            registered = store.list()
            self._logger.info(
                "✓ Nexus credential store ready (%d provider%s registered)",
                len(registered), "s" if len(registered) != 1 else "",
            )
            return store
        except Exception as exc:
            self._logger.warning("Nexus store init failed (continuing without): %s", exc)
            return None

    def _init_athena(self, settings):
        """
        Init AthenaClient — optional remote memory OS.

        Returns None gracefully when ATHENA_URL is not set.
        When connected, agents get cross-session semantic memory via
        self._athena_client. UnifiedMemory uses this as its 4th tier.
        """
        try:
            from jarviscore.memory.athena_client import AthenaClient
            client = AthenaClient.from_env()
            if client:
                self._logger.info("✓ Athena memory client connected")
            return client
        except Exception as exc:
            self._logger.debug("Athena client init skipped: %s", exc)
            return None

    def _resolve_auto_mode(self) -> "MeshMode":
        """
        Detect the best operational mode from the live environment.

        Called at start() time when mode="auto" (the default).  By then
        ``_redis_store`` has already been initialised, so we know exactly
        what infrastructure is reachable.

        Decision logic
        --------------
        1. Redis reachable AND p2p_enabled config flag set  →  ``p2p``
        2. Redis reachable                                  →  ``distributed``
        3. Nothing reachable                                →  ``autonomous``

        This means:
        - On your laptop with no Redis  →  autonomous  (just works)
        - On a dev/staging server with Redis  →  distributed  (prod-like)
        - On prod with Redis + p2p_enabled  →  p2p  (full mesh)

        You never have to think about it.  Set REDIS_URL in env and the
        mesh does the right thing.
        """
        has_redis = self._redis_store is not None
        wants_p2p = self.config.get("p2p_enabled", False)

        if has_redis and wants_p2p:
            return MeshMode.P2P
        if has_redis:
            return MeshMode.DISTRIBUTED
        return MeshMode.AUTONOMOUS

    def _inject_infrastructure(self):
        """
        Inject redis_store, blob_storage, mailbox, and HITLQueue into all agents.

        Called during start() before agent setup() so agents have full access
        to infrastructure stores and escalation channels during initialization.

        Every agent ends up with:
          agent._redis_store   — RedisContextStore (or None)
          agent._blob_storage  — BlobStorage (or None)
          agent.mailbox        — MailboxManager (always, file-backed if no Redis)
          agent.hitl           — HITLQueue (always, writes to hitl_inbox/)
        """
        from jarviscore.mailbox import MailboxManager

        # Resolve hitl_inbox path from config or use package-relative default
        inbox_dir = self.config.get("hitl_inbox_dir", None)

        # Import framework-native HITLQueue
        try:
            from jarviscore.hitl import HITLQueue as _HITLQueue
        except ImportError:
            _HITLQueue = None

        for agent in self.agents:
            agent._redis_store   = self._redis_store
            agent._blob_storage  = self._blob_storage
            agent._nexus_store   = self._nexus_store    # always set (NexusLocalStore)
            agent._athena_client = self._athena_client  # set when ATHENA_URL configured

            # Mailbox: use Redis when available, local-only otherwise
            if self._redis_store:
                agent.mailbox = MailboxManager(agent.agent_id, self._redis_store)
            else:
                agent.mailbox = MailboxManager(agent.agent_id, None)

            # HITLQueue: always available; Redis-enhanced when connected
            if _HITLQueue is not None:
                agent.hitl = _HITLQueue(
                    agent_id=agent.agent_id,
                    inbox_dir=inbox_dir,
                    redis_store=self._redis_store,
                )
            else:
                agent.hitl = None  # degraded — log once
                self._logger.warning(
                    "HITLQueue not available — install jarviscore[hitl] or ensure "
                    "services/hitl.py is on PYTHONPATH"
                )

        self._logger.info(
            "✓ Infrastructure injected into %d agent(s) "
            "(redis=%s, blob=%s, hitl=%s)",
            len(self.agents),
            "yes" if self._redis_store else "no",
            "yes" if self._blob_storage else "no",
            "yes" if _HITLQueue else "no",
        )

    def _inject_peer_clients(self):
        """
        Inject PeerClient instances into all agents regardless of mesh mode.

        **P2P mode**: Full SWIM-backed ``PeerClient`` — uses the coordinator
        and ZMQ transport for cross-process agent communication.

        **AUTONOMOUS / DISTRIBUTED mode**: Local-only ``PeerClient``
        (``coordinator=None``) — ``ask_peer`` routes through the in-process
        ``_agent_registry`` so AutoAgents can delegate to co-registered
        agents (e.g., Sentinel delegating to Coder) without SWIM.

        This fixes Dogfooding Issue #13: ``ask_peer`` was P2P-only.
        ``AutoAgent`` (which always runs in autonomous mode)
        now gets a fully functional ``self.peers`` client.
        """
        try:
            from jarviscore.p2p import PeerClient
        except (ImportError, TypeError) as exc:
            # TypeError: Python 3.9 SWIM uses kw_only=True (3.10+ only).
            # ImportError: p2p deps not installed.
            # Fall back: load peer_client.py directly via importlib to bypass
            # the package __init__.py which chains to SWIM.
            self._logger.warning(
                "P2P PeerClient unavailable (%s: %s) — using local-only peer stubs",
                type(exc).__name__, exc,
            )
            import importlib.util as _ilu
            import pathlib as _pl
            _pc_path = _pl.Path(__file__).parent.parent / "p2p" / "peer_client.py"
            _spec = _ilu.spec_from_file_location("jarviscore.p2p.peer_client", str(_pc_path))
            _mod = _ilu.module_from_spec(_spec)

            # peer_client.py imports .messages — load that first the same way
            _msg_path = _pl.Path(__file__).parent.parent / "p2p" / "messages.py"
            _msg_spec = _ilu.spec_from_file_location("jarviscore.p2p.messages", str(_msg_path))
            _msg_mod = _ilu.module_from_spec(_msg_spec)
            import sys as _sys
            _sys.modules["jarviscore.p2p.messages"] = _msg_mod
            _msg_spec.loader.exec_module(_msg_mod)

            _sys.modules["jarviscore.p2p.peer_client"] = _mod
            _spec.loader.exec_module(_mod)
            PeerClient = _mod.PeerClient

        is_p2p = self.mode == MeshMode.P2P

        node_id = ""
        if is_p2p and self._p2p_coordinator and self._p2p_coordinator.swim_manager:
            addr = self._p2p_coordinator.swim_manager.bind_addr
            if addr:
                node_id = f"{addr[0]}:{addr[1]}"

        coordinator = self._p2p_coordinator if is_p2p else None

        for agent in self.agents:
            peer_client = PeerClient(
                coordinator=coordinator,
                agent_id=agent.agent_id,
                agent_role=agent.role,
                agent_registry=self._agent_registry,
                node_id=node_id
            )
            agent.peers = peer_client

            # Register with coordinator for remote message routing (P2P only)
            if is_p2p and self._p2p_coordinator:
                self._p2p_coordinator.register_peer_client(agent.agent_id, peer_client)

            self._logger.debug(
                "Injected PeerClient into agent: %s (local_only=%s)",
                agent.agent_id, not is_p2p,
            )

    async def run_forever(self):
        """
        Start ``async def run()`` loops for every registered agent that has one,
        and block until all loops exit or the process is interrupted.

        Works in every mesh configuration — no mode required.
        Agents without a ``run()`` method are skipped (they are driven by
        ``mesh.workflow()`` instead).

        Combines cleanly with ``mesh.workflow()``: some agents can have run()
        loops for self-management while the workflow engine handles orchestrated
        multi-step tasks.

        Example::

            mesh = Mesh()
            mesh.add(Compass)      # Has run() — self-drives standups, planning
            mesh.add(Sentinel)     # Has run() — self-drives intel scans
            mesh.add(Quill)        # Has run() — processes mailbox tasks
            mesh.add(Coder)        # No run() — only called via workflow/delegate

            await mesh.start()
            await mesh.run_forever()   # blocks; Coder available via mesh.delegate()
        """
        if not self._started:
            raise RuntimeError("Mesh not started. Call await mesh.start() first.")

        self._logger.info("Starting agent run() loops...")

        agent_tasks: List[asyncio.Task] = []
        for agent in self.agents:
            if hasattr(agent, "run") and asyncio.iscoroutinefunction(agent.run):
                task = asyncio.create_task(
                    self._run_agent_loop(agent),
                    name=f"agent-loop-{agent.agent_id}",
                )
                self._agent_run_tasks.append(task)
                agent_tasks.append(task)
                self._logger.info("Started run() loop: %s", agent.agent_id)
            else:
                self._logger.debug(
                    "Agent %s has no run() — will be driven by workflow/delegate",
                    agent.agent_id,
                )

        if agent_tasks:
            self._capabilities.add("run_loops")
            self._logger.info(
                "Running %d agent loop(s). Press Ctrl+C to stop.", len(agent_tasks)
            )
        else:
            self._logger.info(
                "No agents have run() loops — mesh is workflow-only. "
                "Use mesh.workflow() or mesh.delegate() to drive agents."
            )
            return

        try:
            await asyncio.gather(*agent_tasks)
        except asyncio.CancelledError:
            self._logger.info("Agent loops cancelled")
        except KeyboardInterrupt:
            self._logger.info("Keyboard interrupt received")
        finally:
            for agent in self.agents:
                if hasattr(agent, "request_shutdown"):
                    agent.request_shutdown()
            for task in agent_tasks:
                if not task.done():
                    task.cancel()
            await self.stop()

            # Cancel any remaining tasks
            for task in agent_tasks:
                if not task.done():
                    task.cancel()

            await self.stop()

    async def _run_agent_loop(self, agent: Agent):
        """
        Run a single agent's loop with crash-restart supervision.

        If an agent's run() raises, this supervisor logs the error and
        restarts it with exponential backoff — the other agents in the
        mesh are unaffected.  Only asyncio.CancelledError (intentional
        mesh shutdown) propagates upward.

        This mirrors the _safe_run() pattern that exists in the agent
        layer (signal.py) but was never wired into mesh.run_forever().
        """
        backoff = 5
        max_backoff = 120
        while self._started:
            try:
                await agent.run()
                self._logger.info(
                    f"Agent {agent.agent_id} run() returned normally — exiting supervisor"
                )
                break  # clean exit — agent chose to stop
            except asyncio.CancelledError:
                self._logger.debug(f"Agent {agent.agent_id} loop cancelled")
                raise
            except Exception as e:
                self._logger.error(
                    f"Agent {agent.agent_id} loop crashed "
                    f"({type(e).__name__}: {e}) — restarting in {backoff}s"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)


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
        Use get_agents_by_capability() to query agents by capability tag.

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

    # ─────────────────────────────────────────────────────────────────
    # CAPABILITY INSPECTION
    # ─────────────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> Set[str]:
        """
        Return the set of infrastructure capabilities available in this mesh.

        Populated at ``start()`` time based on what is reachable.
        Always accurate after the mesh has started.

        Common values:
            "workflow"          — WorkflowEngine ready
            "run_loops"         — Agent run() loops are active
            "peer_local"        — In-process PeerClient (always present)
            "peer_distributed"  — Redis-backed peer routing
            "peer_swim"         — SWIM/ZMQ cross-node routing
            "redis"             — Redis connected
            "blob"              — BlobStorage connected
            "auth"              — AuthenticationManager active
            "prometheus"        — Metrics server running
        """
        return frozenset(self._capabilities)

    def has_capability(self, cap: str) -> bool:
        """
        Check whether a specific infrastructure capability is active.

        Replaces the old ``mesh.mode == MeshMode.X`` pattern.

        Args:
            cap: Capability name (see ``mesh.capabilities`` for full list)

        Returns:
            True if the capability is active, False otherwise

        Example::

            if mesh.has_capability("redis"):
                # Use Redis-backed storage
            else:
                # Fall back to in-process
        """
        return cap in self._capabilities

    # ─────────────────────────────────────────────────────────────────
    # DELEGATION  (Dogfooding Issue #12)
    # ─────────────────────────────────────────────────────────────────

    async def delegate(
        self,
        to: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        capability: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Delegate a task to another agent in the mesh by role or capability.

        This is the canonical inter-agent communication primitive.  Any agent
        whose generated code has access to ``mesh`` (injected by AutoAgent's
        sandbox namespace) can hand off work to a specialist agent and await
        a structured result — without knowing anything about the target's
        internal implementation.

        Resolution order:
            1. Exact role match  →  ``mesh.get_agent(to)``
            2. Capability match  →  ``mesh.get_agents_by_capability(capability or to)``
            3. ``ValueError`` if nothing found

        Args:
            to:         Role name of the target agent (e.g. ``"coder"``).
            task:       Natural language task description passed to the agent.
            context:    Optional dict merged into the task payload under
                        ``"context"`` — use this to pass prior step outputs,
                        file paths, briefs, etc.
            capability: Fallback capability string if the role is not found.
                        Defaults to ``to`` when not specified.
            timeout:    Optional per-call timeout in seconds (currently advisory;
                        the target agent's own timeout governs actual execution).

        Returns:
            The raw dict returned by ``agent.execute_task()``.  Always contains
            at least ``{"status": "success"|"failure", ...}``.

        Raises:
            ValueError:  No agent with the given role or capability was found.
            RuntimeError: Target agent has no ``execute_task`` method.

        Example — from inside generated code or a service::

            result = await mesh.delegate(
                to="coder",
                task="Generate the Q2 investor deck as a branded PPTX",
                context={
                    "brief": team_brief,
                    "output_filename": "quarterly_report_q2.pptx",
                },
            )
            pptx_path = result["files_created"][0]

        Example — delegate to whichever agent has a specific capability::

            result = await mesh.delegate(
                to="any",
                capability="pdf_generation",
                task="Convert the attached HTML report to a branded PDF",
            )
        """
        # 1. Resolve target agent
        agent = self.get_agent(to)

        if agent is None and capability:
            agents = self.get_agents_by_capability(capability)
            agent = agents[0] if agents else None

        if agent is None:
            # Try capability fallback using the ``to`` string itself
            agents = self.get_agents_by_capability(to)
            agent = agents[0] if agents else None

        if agent is None:
            registered_roles = list(self._agent_registry.keys())
            raise ValueError(
                f"mesh.delegate(): no agent found for role='{to}' "
                f"or capability='{capability or to}'. "
                f"Registered roles: {registered_roles}"
            )

        if not hasattr(agent, "execute_task"):
            raise RuntimeError(
                f"mesh.delegate(): agent '{agent.agent_id}' (role={agent.role}) "
                f"has no execute_task() method. It must inherit from AutoAgent."
            )

        self._logger.info(
            "mesh.delegate: %s → %s  task=%s",
            "caller", agent.agent_id, task[:80],
        )

        payload: Dict[str, Any] = {"task": task}
        if context:
            payload["context"] = context

        return await agent.execute_task(payload)

    async def run_task(
        self,
        agent: str = "",
        agent_role: str = "",
        task: str = "",
        context: Optional[Dict[str, Any]] = None,
        complexity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Dispatch a single task to an agent by role.

        This is the primary user-facing API for running a task on a specific
        agent.  It wraps ``delegate()`` with a friendlier signature and adds
        support for the ``complexity`` parameter (multi-tier model routing).

        Args:
            agent:      Agent role name (e.g. ``"researcher"``).
            agent_role: Alias for ``agent`` — used internally by WorkflowBuilder.
            task:       Natural language task description.
            context:    Optional dict merged into the task payload.
            complexity: Optional model tier hint: ``"nano"``, ``"standard"``,
                        or ``"heavy"``.  Passed through to the Kernel via
                        context so it selects the appropriate LLM model.

        Returns:
            The result dict from the agent's ``execute_task()`` — always
            contains at least ``{"status": "success"|"failure", ...}``.

        Example::

            result = await mesh.run_task(
                agent="analyst",
                task="Summarise the following paragraph in one sentence.",
                complexity="nano",
            )
        """
        role = agent or agent_role
        if not role:
            raise ValueError("run_task() requires 'agent' or 'agent_role'.")

        ctx = dict(context) if context else {}
        if complexity:
            ctx["complexity"] = complexity

        return await self.delegate(to=role, task=task, context=ctx or None)

    # ─────────────────────────────────────────────────────────────────
    # DIAGNOSTICS
    # ─────────────────────────────────────────────────────────────────

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Get diagnostic information about the mesh and P2P connectivity.

        Useful for debugging P2P issues, monitoring mesh health,
        and understanding the current state of the distributed system.

        Returns:
            Dictionary containing:
            - local_node: This node's configuration and status
            - known_peers: List of discovered remote peers
            - local_agents: List of local agents with capabilities
            - connectivity_status: Overall health assessment
            - keepalive_status: Keepalive manager health (if P2P enabled)
            - swim_status: SWIM protocol status (if P2P enabled)
            - capability_map: Mapping of capabilities to agent IDs

        Example:
            diagnostics = mesh.get_diagnostics()
            print(f"Status: {diagnostics['connectivity_status']}")
            for peer in diagnostics['known_peers']:
                print(f"  {peer['role']} at {peer['node_id']}: {peer['status']}")
        """
        result = {
            "local_node": self._get_local_node_info(),
            "known_peers": self._get_peer_list(),
            "local_agents": self._get_local_agents_info(),
            "connectivity_status": self._assess_connectivity_status()
        }

        # Add P2P-specific diagnostics if coordinator is available
        if self._p2p_coordinator:
            result["keepalive_status"] = self._get_keepalive_status()
            result["swim_status"] = self._get_swim_status()
            result["capability_map"] = self._get_capability_map()

        return result

    def _get_local_node_info(self) -> Dict[str, Any]:
        """Get local node information."""
        info = {
            "mode": self.mode.value,
            "started": self._started,
            "agent_count": len(self.agents)
        }

        if self._p2p_coordinator and self._p2p_coordinator.swim_manager:
            addr = self._p2p_coordinator.swim_manager.bind_addr
            if addr:
                info["bind_address"] = f"{addr[0]}:{addr[1]}"

        return info

    def _get_peer_list(self) -> List[Dict[str, Any]]:
        """Get list of known remote peers."""
        peers = []

        if self._p2p_coordinator:
            for agent in self._p2p_coordinator.list_remote_agents():
                peers.append({
                    "role": agent.get("role", "unknown"),
                    "agent_id": agent.get("agent_id", "unknown"),
                    "node_id": agent.get("node_id", "unknown"),
                    "capabilities": agent.get("capabilities", []),
                    "status": "connected"
                })

        return peers

    def _get_local_agents_info(self) -> List[Dict[str, Any]]:
        """Get information about local agents."""
        return [
            {
                "role": agent.role,
                "agent_id": agent.agent_id,
                "capabilities": list(agent.capabilities),
                "description": getattr(agent, 'description', ''),
                "has_peers": hasattr(agent, 'peers') and agent.peers is not None
            }
            for agent in self.agents
        ]

    def _assess_connectivity_status(self) -> str:
        """
        Assess overall connectivity status.

        Returns:
            "healthy" - P2P fully operational with peers
            "isolated" - No peers connected
            "degraded" - Some connectivity issues detected
            "not_started" - Mesh not yet started
            "local_only" - Not in distributed/p2p mode
        """
        if not self._started:
            return "not_started"

        if self.mode == MeshMode.AUTONOMOUS:
            return "local_only"

        if not self._p2p_coordinator:
            return "local_only"

        # Check SWIM health
        if self._p2p_coordinator.swim_manager:
            if not self._p2p_coordinator.swim_manager.is_healthy():
                return "degraded"

        # Check for connected peers
        remote_agents = self._p2p_coordinator.list_remote_agents()
        if not remote_agents:
            return "isolated"

        # Check keepalive health if available
        if hasattr(self._p2p_coordinator, 'keepalive_manager') and self._p2p_coordinator.keepalive_manager:
            health = self._p2p_coordinator.keepalive_manager.get_health_status()
            if health.get('circuit_state') == 'OPEN':
                return "degraded"

        return "healthy"

    def _get_keepalive_status(self) -> Optional[Dict[str, Any]]:
        """Get keepalive manager status."""
        if not self._p2p_coordinator:
            return None

        if hasattr(self._p2p_coordinator, 'keepalive_manager') and self._p2p_coordinator.keepalive_manager:
            return self._p2p_coordinator.keepalive_manager.get_health_status()

        return None

    def _get_swim_status(self) -> Optional[Dict[str, Any]]:
        """Get SWIM protocol status."""
        if not self._p2p_coordinator or not self._p2p_coordinator.swim_manager:
            return None

        return self._p2p_coordinator.swim_manager.get_status()

    def _get_capability_map(self) -> Dict[str, List[str]]:
        """Get the capability to agent_id mapping."""
        if not self._p2p_coordinator:
            return {}

        # Convert defaultdict to regular dict for serialization
        return dict(self._p2p_coordinator._capability_map)

    def __repr__(self) -> str:
        """String representation of mesh."""
        return (
            f"<Mesh mode={self.mode.value} "
            f"agents={len(self.agents)} "
            f"started={self._started}>"
        )
