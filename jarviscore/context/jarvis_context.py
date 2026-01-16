"""
JarvisContext - Unified context for Custom Profile agents.

Provides a single object that gives agents access to:
- Workflow information (workflow_id, step_id)
- Task information (task description, params)
- Memory (shared state between steps)
- Dependencies (check/wait for other steps)

This is a facade over existing JarvisCore primitives.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from .memory import MemoryAccessor
from .dependency import DependencyAccessor


@dataclass
class JarvisContext:
    """
    Context passed to wrapped agents during execution.

    Provides unified access to JarvisCore orchestration primitives.
    Agents receive this as the `ctx` parameter when they declare it
    in their run method signature.

    Attributes:
        workflow_id: Unique identifier for the current workflow
        step_id: Unique identifier for the current step
        task: Task description string
        params: Task parameters dictionary
        memory: Accessor for shared workflow memory
        deps: Accessor for dependency management

    Example:
        @jarvis_agent(role="aggregator", capabilities=["aggregation"])
        class Aggregator:
            def run(self, task, ctx: JarvisContext):
                # Access previous step output
                step1_data = ctx.previous("step1")

                # Access all previous results
                all_results = ctx.memory.all()

                # Check workflow info
                print(f"Running step {ctx.step_id} in {ctx.workflow_id}")

                # Use params
                threshold = ctx.params.get("threshold", 0.5)

                return {"aggregated": process(step1_data)}
    """

    # Workflow info
    workflow_id: str
    step_id: str

    # Task info
    task: str
    params: Dict[str, Any] = field(default_factory=dict)

    # Orchestration accessors
    memory: MemoryAccessor = None
    deps: DependencyAccessor = None

    def previous(self, step_id: str, default: Any = None) -> Any:
        """
        Get output from a previous step.

        Convenience method that delegates to memory.get().

        Args:
            step_id: ID of the step to get output from
            default: Default value if not found

        Returns:
            Step output or default

        Example:
            step1_result = ctx.previous("step1")
            optional = ctx.previous("optional_step", default={})
        """
        if self.memory is None:
            return default
        return self.memory.get(step_id, default)

    def all_previous(self) -> Dict[str, Any]:
        """
        Get all previous step outputs.

        Convenience method that delegates to memory.all().

        Returns:
            Dictionary of step_id -> output

        Example:
            all_results = ctx.all_previous()
            for step_id, output in all_results.items():
                print(f"{step_id} produced: {output}")
        """
        if self.memory is None:
            return {}
        return self.memory.all()

    @property
    def previous_results(self) -> Dict[str, Any]:
        """
        Alias for all_previous().

        Provides property-style access to all previous results.

        Example:
            results = ctx.previous_results
        """
        return self.all_previous()

    def has_previous(self, step_id: str) -> bool:
        """
        Check if a previous step's output exists.

        Args:
            step_id: Step to check

        Returns:
            True if output exists

        Example:
            if ctx.has_previous("optional_step"):
                data = ctx.previous("optional_step")
        """
        if self.memory is None:
            return False
        return self.memory.has(step_id)

    def get_param(self, key: str, default: Any = None) -> Any:
        """
        Get a task parameter by key.

        Args:
            key: Parameter key
            default: Default value if not found

        Returns:
            Parameter value or default

        Example:
            threshold = ctx.get_param("threshold", 0.5)
            mode = ctx.get_param("mode", "default")
        """
        return self.params.get(key, default)

    def __repr__(self) -> str:
        return (
            f"<JarvisContext "
            f"workflow={self.workflow_id} "
            f"step={self.step_id} "
            f"params={list(self.params.keys())}>"
        )


def create_context(
    workflow_id: str,
    step_id: str,
    task: str,
    params: Dict[str, Any],
    memory_dict: Dict[str, Any],
    dependency_manager: Optional[Any] = None
) -> JarvisContext:
    """
    Factory function to create a JarvisContext.

    Used internally by the decorator and WorkflowEngine to create
    context objects for agents.

    Args:
        workflow_id: Workflow identifier
        step_id: Step identifier
        task: Task description
        params: Task parameters
        memory_dict: Reference to WorkflowEngine.memory
        dependency_manager: Optional reference to DependencyManager

    Returns:
        Configured JarvisContext instance

    Example:
        ctx = create_context(
            workflow_id="pipeline-1",
            step_id="step2",
            task="Process data",
            params={"threshold": 0.5},
            memory_dict=engine.memory,
            dependency_manager=engine.dependency_manager
        )
    """
    memory_accessor = MemoryAccessor(memory_dict, step_id)
    dep_accessor = DependencyAccessor(dependency_manager, memory_dict)

    return JarvisContext(
        workflow_id=workflow_id,
        step_id=step_id,
        task=task,
        params=params,
        memory=memory_accessor,
        deps=dep_accessor
    )
