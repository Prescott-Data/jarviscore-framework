"""
Dependency Manager - Resolves step dependencies

Simplified from integration-agent
Removes: Kafka integration, complex P2P queries
Keeps: Memory cache, basic waiting logic

Phase 7C: Added Redis path — when a redis_store is provided, wait_for()
polls redis_store.are_dependencies_met() instead of the local memory dict.
This makes dependency resolution authoritative across multi-process / crashed
workflows where the memory dict is empty after restart.
"""
import logging
import asyncio
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class DependencyManager:
    """
    Manages step dependencies and resolution.

    Simplified from integration-agent's 3-tier system:
    - Tier 1: Memory cache (kept)
    - Tier 2: Redis DAG (Phase 7C: added)
    - Tier 3: Kafka (removed for MVP)

    When redis_store is provided, wait_for() routes through Redis so that
    dependency state is shared across processes and survives crashes.
    Falls back to polling the local memory dict when redis_store is None.
    """

    def __init__(
        self,
        memory_cache: Optional[Dict] = None,
        redis_store=None,
    ):
        """
        Initialize dependency manager.

        Args:
            memory_cache: Optional shared memory cache for step outputs
            redis_store: Optional RedisContextStore for cross-process dep checks
        """
        self.memory = memory_cache or {}
        self.redis = redis_store  # Phase 7C: optional Redis backing
        self.waiting_steps: Dict[str, List[str]] = {}  # step_id -> [dep_ids]
        logger.info("Dependency manager initialized")

    async def wait_for(
        self,
        dependencies: List[str],
        memory: Dict[str, Any],
        timeout: float = 300.0,
        workflow_id: str = "",
    ) -> Dict[str, Any]:
        """
        Wait for dependencies to be satisfied.

        Args:
            dependencies: List of step IDs this step depends on
            memory: Workflow memory containing step outputs
            timeout: Maximum time to wait in seconds
            workflow_id: Workflow ID (required when redis_store is set)

        Returns:
            Dictionary of dependency_id -> output

        Raises:
            TimeoutError: If dependencies not satisfied within timeout

        Example:
            deps = await manager.wait_for(['step1'], memory, workflow_id='wf-1')
            input_data = deps['step1']['output']
        """
        if not dependencies:
            return {}

        logger.info(f"Waiting for {len(dependencies)} dependencies: {dependencies}")

        if self.redis and workflow_id:
            return await self._wait_redis(dependencies, workflow_id, timeout)

        return await self._wait_memory(dependencies, memory, timeout)

    # ------------------------------------------------------------------
    # Redis path (Phase 7C)
    # ------------------------------------------------------------------

    async def _wait_redis(
        self,
        dependencies: List[str],
        workflow_id: str,
        timeout: float,
    ) -> Dict[str, Any]:
        """
        Poll get_step_status() per dep until all dependencies complete.

        Uses 0.5 s backoff — same cadence as the reactive loop — so this
        method never runs faster than the engine ticks.
        """
        start = asyncio.get_event_loop().time()

        while True:
            all_done = all(
                self.redis.get_step_status(workflow_id, dep_id) == "completed"
                for dep_id in dependencies
            )
            if all_done:
                break

            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= timeout:
                raise TimeoutError(
                    f"Dependencies {dependencies} for workflow {workflow_id} "
                    f"not satisfied within {timeout}s"
                )

            await asyncio.sleep(0.5)

        # Fetch outputs from Redis for each dep
        resolved = {}
        for dep_id in dependencies:
            saved = self.redis.get_step_output(workflow_id, dep_id)
            resolved[dep_id] = saved.get("output", saved) if saved else None
            logger.debug(f"Dependency {dep_id} resolved via Redis")

        logger.info(f"All dependencies satisfied via Redis: {list(resolved.keys())}")
        return resolved

    # ------------------------------------------------------------------
    # In-memory path (original)
    # ------------------------------------------------------------------

    async def _wait_memory(
        self,
        dependencies: List[str],
        memory: Dict[str, Any],
        timeout: float,
    ) -> Dict[str, Any]:
        """Poll local memory dict until all deps appear."""
        start_time = asyncio.get_event_loop().time()
        resolved = {}

        for dep_id in dependencies:
            if dep_id in memory:
                resolved[dep_id] = memory[dep_id]
                logger.debug(f"Dependency {dep_id} found in memory")
                continue

            logger.info(f"Waiting for dependency: {dep_id}")
            while dep_id not in memory:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    raise TimeoutError(
                        f"Dependency {dep_id} not satisfied within {timeout}s"
                    )
                await asyncio.sleep(0.5)

            resolved[dep_id] = memory[dep_id]
            logger.debug(f"Dependency {dep_id} satisfied")

        logger.info(f"All dependencies satisfied: {list(resolved.keys())}")
        return resolved

    def check_dependencies(
        self,
        dependencies: List[str],
        memory: Dict[str, Any]
    ) -> tuple[bool, List[str]]:
        """
        Check if dependencies are satisfied (non-blocking).

        Args:
            dependencies: List of step IDs to check
            memory: Workflow memory

        Returns:
            Tuple of (all_satisfied, missing_deps)
        """
        if not dependencies:
            return True, []

        missing = [dep for dep in dependencies if dep not in memory]

        if missing:
            logger.debug(f"Missing dependencies: {missing}")
            return False, missing

        return True, []

    def register_waiting(self, step_id: str, dependencies: List[str]):
        """
        Register a step as waiting for dependencies.

        Args:
            step_id: Step that is waiting
            dependencies: List of dependency step IDs
        """
        self.waiting_steps[step_id] = dependencies
        logger.debug(f"Step {step_id} waiting for: {dependencies}")

    def resolve_step(self, step_id: str):
        """
        Mark a step as resolved (completed).

        Args:
            step_id: Step that has been completed
        """
        if step_id in self.waiting_steps:
            del self.waiting_steps[step_id]
            logger.debug(f"Step {step_id} resolved")

    def get_waiting_steps(self) -> Dict[str, List[str]]:
        """Get all steps currently waiting for dependencies."""
        return self.waiting_steps.copy()
