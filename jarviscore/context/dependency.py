"""
DependencyAccessor - Clean API over DependencyManager.

Wraps the existing orchestration.DependencyManager to provide
a developer-friendly interface for Custom Profile agents.
"""
from typing import List, Dict, Any, Tuple, Optional


class DependencyAccessor:
    """
    Provides clean access to dependency management.

    This is a facade over the existing DependencyManager class.
    It provides a simpler interface for checking and waiting on dependencies.

    Example:
        # In agent's run method with ctx: JarvisContext
        await ctx.deps.wait_for(["step1", "step2"])
        ready, missing = ctx.deps.check(["step1", "step2"])
        if ctx.deps.is_ready("optional_step"):
            ...
    """

    def __init__(
        self,
        dependency_manager: Optional[Any],
        memory: Dict[str, Any]
    ):
        """
        Initialize dependency accessor.

        Args:
            dependency_manager: Reference to orchestration.DependencyManager
            memory: Reference to WorkflowEngine.memory dict
        """
        self._manager = dependency_manager
        self._memory = memory

    async def wait_for(
        self,
        step_ids: List[str],
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Wait for specific steps to complete.

        Blocks until all specified steps have outputs in memory.

        Args:
            step_ids: List of step IDs to wait for
            timeout: Maximum wait time in seconds (default: 5 minutes)

        Returns:
            Dictionary of step_id -> output

        Raises:
            TimeoutError: If dependencies not ready within timeout

        Example:
            results = await deps.wait_for(["step1", "step2"])
            step1_data = results["step1"]
        """
        if self._manager is None:
            # Fallback: simple check without manager
            return self._simple_wait(step_ids)

        return await self._manager.wait_for(step_ids, self._memory, timeout)

    def _simple_wait(self, step_ids: List[str]) -> Dict[str, Any]:
        """
        Simple synchronous check (used when manager not available).

        Returns outputs for steps that exist in memory.
        """
        result = {}
        for step_id in step_ids:
            if step_id in self._memory:
                value = self._memory[step_id]
                if isinstance(value, dict) and 'output' in value:
                    result[step_id] = value['output']
                else:
                    result[step_id] = value
        return result

    def check(self, step_ids: List[str]) -> Tuple[bool, List[str]]:
        """
        Check if dependencies are satisfied (non-blocking).

        Args:
            step_ids: Steps to check

        Returns:
            Tuple of (all_satisfied, missing_step_ids)

        Example:
            ready, missing = deps.check(["step1", "step2"])
            if not ready:
                print(f"Still waiting for: {missing}")
        """
        if self._manager is None:
            # Fallback: simple check without manager
            missing = [s for s in step_ids if s not in self._memory]
            return (len(missing) == 0, missing)

        return self._manager.check_dependencies(step_ids, self._memory)

    def is_ready(self, step_id: str) -> bool:
        """
        Check if a single step is ready (non-blocking).

        Args:
            step_id: Step to check

        Returns:
            True if step output exists in memory

        Example:
            if deps.is_ready("optional_step"):
                data = ctx.memory.get("optional_step")
        """
        return step_id in self._memory

    def all_ready(self, step_ids: List[str]) -> bool:
        """
        Check if all specified steps are ready.

        Args:
            step_ids: Steps to check

        Returns:
            True if all steps have outputs in memory

        Example:
            if deps.all_ready(["step1", "step2", "step3"]):
                # All dependencies satisfied
                ...
        """
        return all(self.is_ready(s) for s in step_ids)

    def any_ready(self, step_ids: List[str]) -> bool:
        """
        Check if any of the specified steps are ready.

        Args:
            step_ids: Steps to check

        Returns:
            True if at least one step has output in memory

        Example:
            if deps.any_ready(["cache_step", "compute_step"]):
                # At least one source available
                ...
        """
        return any(self.is_ready(s) for s in step_ids)

    def __repr__(self) -> str:
        ready_count = sum(1 for k in self._memory.keys())
        return f"<DependencyAccessor ready_steps={ready_count}>"
