"""
Shared base for Investment Committee AutoAgents.

The JarvisCore engine sets task["context"] to only:
  {previous_step_results, workflow_id, step_id}

Workflow-level vars (ticker, amount, mandate, portfolio) are passed
via step["params"] and merged into context here before sandbox execution.

Also sanitizes numpy/pandas types in the output so Redis JSON serialization
never fails (numpy.bool_, numpy.int64, numpy.float64 all cause issues).
"""
import numpy as np
from jarviscore.profiles import AutoAgent


def _to_python(obj):
    """Recursively convert numpy/pandas scalar types to Python natives."""
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_python(v) for v in obj]
    return obj


class CommitteeAutoAgent(AutoAgent):
    """AutoAgent base that merges step params into sandbox context
    and sanitizes numpy types from the result output."""

    async def execute_task(self, task):
        # Inject workflow-level vars (ticker, amount, mandate, portfolio)
        ctx = task.setdefault("context", {})
        ctx.update(task.get("params", {}))

        result = await super().execute_task(task)

        # Sanitize numpy types so Redis json.dumps never fails
        if isinstance(result.get("output"), dict):
            result["output"] = _to_python(result["output"])

        return result
