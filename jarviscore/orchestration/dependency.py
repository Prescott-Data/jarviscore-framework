"""
Dependency Manager - Resolves step dependencies

Simplified from integration-agent
Removes: Kafka integration, complex P2P queries
Keeps: Memory cache, basic waiting logic
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
    - Tier 2: P2P queries (simplified - future)
    - Tier 3: Kafka (removed for MVP)
    """

    def __init__(self, memory_cache: Optional[Dict] = None):
        """
        Initialize dependency manager.

        Args:
            memory_cache: Optional shared memory cache for step outputs
        """
        self.memory = memory_cache or {}
        self.waiting_steps: Dict[str, List[str]] = {}  # step_id -> [dep_ids]
        logger.info("Dependency manager initialized")

    async def wait_for(
        self,
        dependencies: List[str],
        memory: Dict[str, Any],
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Wait for dependencies to be satisfied.

        Args:
            dependencies: List of step IDs this step depends on
            memory: Workflow memory containing step outputs
            timeout: Maximum time to wait in seconds

        Returns:
            Dictionary of dependency_id -> output

        Raises:
            TimeoutError: If dependencies not satisfied within timeout
            ValueError: If required dependency not found

        Example:
            # Step 2 depends on step 1
            deps = await manager.wait_for(['step1'], memory)
            input_data = deps['step1']['output']
        """
        if not dependencies:
            return {}

        logger.info(f"Waiting for {len(dependencies)} dependencies: {dependencies}")

        start_time = asyncio.get_event_loop().time()
        resolved = {}

        for dep_id in dependencies:
            # Check if already in memory
            if dep_id in memory:
                resolved[dep_id] = memory[dep_id]
                logger.debug(f"Dependency {dep_id} found in memory")
                continue

            # Wait for dependency to appear in memory
            logger.info(f"Waiting for dependency: {dep_id}")
            while dep_id not in memory:
                if asyncio.get_event_loop().time() - start_time > timeout:
                    raise TimeoutError(
                        f"Dependency {dep_id} not satisfied within {timeout}s"
                    )

                await asyncio.sleep(0.5)  # Poll every 500ms

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
