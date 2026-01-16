"""
MemoryAccessor - Clean API over workflow memory.

Wraps the existing WorkflowEngine.memory dict to provide
a developer-friendly interface for Custom Profile agents.
"""
from typing import Dict, Any, Optional, List


class MemoryAccessor:
    """
    Provides clean access to workflow memory (shared state between agents).

    This is a facade over the existing WorkflowEngine.memory dict.
    It extracts 'output' from step results automatically and provides
    a simple get/put/has/all interface.

    Example:
        # In agent's run method with ctx: JarvisContext
        data = ctx.memory.get("step1")
        ctx.memory.put("intermediate", processed)
        all_results = ctx.memory.all()
    """

    def __init__(self, memory: Dict[str, Any], current_step: str = ""):
        """
        Initialize memory accessor.

        Args:
            memory: Reference to WorkflowEngine.memory dict
            current_step: ID of the current step (for context)
        """
        self._memory = memory
        self._current_step = current_step

    def get(self, step_id: str, default: Any = None) -> Any:
        """
        Get output from a specific step.

        Automatically extracts 'output' from step result dicts.

        Args:
            step_id: Step to get output from
            default: Default value if not found

        Returns:
            Step output or default

        Example:
            data = memory.get("step1")
            data = memory.get("optional", default=[])
        """
        result = self._memory.get(step_id, default)

        # If result is a dict with 'output' key, extract it
        if isinstance(result, dict) and 'output' in result:
            return result['output']

        return result

    def get_raw(self, step_id: str, default: Any = None) -> Any:
        """
        Get raw result from a step (without extracting 'output').

        Use this when you need the full result dict including
        status, error, agent_id, etc.

        Args:
            step_id: Step to get result from
            default: Default value if not found

        Returns:
            Full step result dict or default
        """
        return self._memory.get(step_id, default)

    def put(self, key: str, value: Any) -> None:
        """
        Store a value in memory.

        Use for intermediate results that other steps may need.
        Note: Step outputs are automatically stored by the engine.

        Args:
            key: Key to store under
            value: Value to store

        Example:
            memory.put("intermediate_result", processed_data)
        """
        self._memory[key] = value

    def has(self, step_id: str) -> bool:
        """
        Check if a step's output exists in memory.

        Args:
            step_id: Step to check

        Returns:
            True if output exists

        Example:
            if memory.has("optional_step"):
                data = memory.get("optional_step")
        """
        return step_id in self._memory

    def all(self) -> Dict[str, Any]:
        """
        Get all memory contents with outputs extracted.

        Returns:
            Dictionary of step_id -> output

        Example:
            all_results = memory.all()
            for step_id, output in all_results.items():
                print(f"{step_id}: {output}")
        """
        result = {}
        for key, value in self._memory.items():
            if isinstance(value, dict) and 'output' in value:
                result[key] = value['output']
            else:
                result[key] = value
        return result

    def keys(self) -> List[str]:
        """
        Get all step IDs in memory.

        Returns:
            List of step IDs
        """
        return list(self._memory.keys())

    def __contains__(self, step_id: str) -> bool:
        """Support 'in' operator: if 'step1' in memory"""
        return self.has(step_id)

    def __getitem__(self, step_id: str) -> Any:
        """Support dict-style access: memory['step1']"""
        return self.get(step_id)

    def __setitem__(self, key: str, value: Any) -> None:
        """Support dict-style assignment: memory['key'] = value"""
        self.put(key, value)

    def __len__(self) -> int:
        """Return number of items in memory."""
        return len(self._memory)

    def __repr__(self) -> str:
        return f"<MemoryAccessor keys={self.keys()}>"
