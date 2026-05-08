---
icon: material/sitemap
---

# Workflow DAGs

JarvisCore's `WorkflowBuilder` lets you compose multi-agent workflows as Directed Acyclic Graphs (DAGs). Each step is assigned to a specific agent role, steps declare their dependencies, and the framework executes them in topological order — parallelising independent steps automatically.

This guide covers the full `WorkflowBuilder` API, the result reference syntax for chaining step outputs, Redis-backed persistence, and production patterns.

---

## Core Concepts

A **workflow** is a named, executable DAG composed of **steps**. Each step has:

- A unique `step_id` (the key you use to reference its output downstream)
- An `agent` role to dispatch the task to
- A `task` description (natural language)
- An optional `depends_on` list of step IDs that must succeed first

Steps without dependencies are eligible to run immediately. When all dependencies of a step have succeeded, that step becomes eligible. The framework runs all eligible steps concurrently in each round.

---

## Building a Workflow

```python
from jarviscore.orchestration.workflow_builder import WorkflowBuilder

wf = (
    WorkflowBuilder()
    .step("research",  "researcher", "Gather market data on EV adoption in Europe for Q1 2026.")
    .step("analyse",   "analyst",    "Analyse findings: {research.result}", depends_on=["research"])
    .step("draft",     "writer",     "Draft executive report from: {analyse.result}", depends_on=["analyse"])
    .step("review",    "reviewer",   "QA the draft for accuracy and tone.", depends_on=["draft"])
    .build(title="EV Market Report", team="market-intelligence")
)
```

### WorkflowBuilder.step

```python
builder.step(
    step_id="research",
    agent="researcher",
    task="Gather market data on topic X.",
    depends_on=["prior_step_id"],  # optional
)
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `step_id` | `str` | Yes | Unique step identifier. Used for `{step_id.result}` references in downstream tasks. |
| `agent` | `str` | Yes | Role of the agent to dispatch this step to (must match the `role` attribute on the agent class). |
| `task` | `str` | Yes | Natural language task description. May contain `{step_id.result}` placeholders. |
| `depends_on` | `list[str]` | No | List of `step_id` values that must succeed before this step runs. |

> [!IMPORTANT]
> Steps must be declared in topological order. If step `B` depends on step `A`, you must call `.step("A", ...)` before `.step("B", ..., depends_on=["A"])`. Declaring a dependency on an undeclared step raises `ValueError` immediately at build time.

### WorkflowBuilder.build

```python
workflow = builder.build(title="My Pipeline", team="my-team")
```

Returns a `Workflow` object ready for registration and execution. Raises `ValueError` if no steps have been added.

---

## Result Reference Syntax

Downstream steps can reference the output of upstream steps using `{step_id.result}` placeholders in the task description:

```python
.step("analyse", "analyst", "Analyse these findings: {research.result}", depends_on=["research"])
```

At execution time, the placeholder is replaced with the actual output of the `research` step before the task is dispatched to the agent. If the referenced step's output is a dict, the framework extracts the `output` or `result` key. The substituted value is capped at 500 characters.

---

## Registering and Executing

### register

Persists the DAG to Redis. This enables dashboard visibility and cross-node coordination.

```python
workflow_id = await wf.register(redis_store)
```

If `redis_store` is `None`, the workflow runs in-memory only. The `workflow_id` is still returned and can be used for local tracking.

### execute

Runs the workflow by dispatching steps to agents via the Mesh.

```python
results = await wf.execute(mesh, redis_store=redis_store, timeout_per_step=300)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `mesh` | `Mesh` | Required | The active JarvisCore Mesh instance |
| `redis_store` | `RedisContextStore` | `None` | When set, step status is written to Redis in real time |
| `timeout_per_step` | `int` | `300` | Seconds per step before it is marked `timeout` |

Returns a list of step result dicts:

```python
[
    {"step_id": "research", "agent": "researcher", "status": "success", "output": {...}, "error": None, "elapsed_ms": 4820},
    {"step_id": "analyse",  "agent": "analyst",    "status": "success", "output": {...}, "error": None, "elapsed_ms": 3100},
    {"step_id": "draft",    "agent": "writer",     "status": "success", "output": {...}, "error": None, "elapsed_ms": 6450},
    {"step_id": "review",   "agent": "reviewer",   "status": "success", "output": {...}, "error": None, "elapsed_ms": 2200},
]
```

Possible `status` values: `success`, `failure`, `timeout`.

A failed step does not prevent its independent sibling steps from running. Steps that depend on a failed step are blocked.

---

## Full Example: Research-to-Report Pipeline

```python title="agents/orchestrator.py"
import asyncio
from jarviscore import CustomAgent, Mesh
from jarviscore.orchestration.workflow_builder import WorkflowBuilder


class OrchestratorAgent(CustomAgent):
    name = "Orchestrator"
    role = "orchestrator"
    description = "Composes and executes research-to-report workflows."

    async def on_peer_request(self, msg) -> dict:
        mesh = self._mesh  # Mesh injects itself at add() time

        task = msg.data.get("task", "")

        # 1. Compose the DAG
        wf = (
            WorkflowBuilder()
            .step(
                "intel",
                "researcher",
                f"Research the following and return a structured summary: {task}",
            )
            .step(
                "analysis",
                "analyst",
                "Analyse the research and identify three key insights: {intel.result}",
                depends_on=["intel"],
            )
            .step(
                "report",
                "writer",
                "Write a 500-word executive report from these insights: {analysis.result}",
                depends_on=["analysis"],
            )
            .build(title=f"Research pipeline: {task[:60]}", team="research-ops")
        )

        # 2. Register with Redis (enables dashboard visibility)
        workflow_id = await wf.register(self._redis_store)
        self._logger.info("Workflow %s registered", workflow_id)

        # 3. Execute
        results = await wf.execute(
            mesh,
            redis_store=self._redis_store,
            timeout_per_step=600,
        )

        # 4. Return summary
        final_step = next((r for r in results if r["step_id"] == "report"), None)
        return {
            "workflow_id": workflow_id,
            "steps": len(results),
            "successes": sum(1 for r in results if r["status"] == "success"),
            "report": final_step["output"] if final_step else None,
        }
```

---

## Parallel Steps

Steps without mutual dependencies are dispatched concurrently. Use this to parallelise independent work:

```python
wf = (
    WorkflowBuilder()
    # Research and competitive scan run in parallel
    .step("market_research", "researcher", "Gather market size data for EMEA.")
    .step("competitor_scan", "researcher", "Identify top 5 competitors and their positioning.")
    # Synthesis waits for both
    .step(
        "synthesis",
        "analyst",
        "Synthesise market data and competitive landscape: {market_research.result} + {competitor_scan.result}",
        depends_on=["market_research", "competitor_scan"],
    )
    .build(title="EMEA Market Analysis")
)
```

The `market_research` and `competitor_scan` steps are dispatched simultaneously. `synthesis` begins only after both complete successfully.

---

## Accessing redis_store from an Agent

`self._redis_store` is the `RedisContextStore` instance injected by the Mesh at setup time. It is `None` if Redis is not configured. Pass it to `register()` and `execute()`:

```python
workflow_id = await wf.register(self._redis_store)
results = await wf.execute(mesh, redis_store=self._redis_store)
```

When `self._redis_store` is `None`, the workflow executes in-memory and step statuses are not written to Redis. This is fine for development.

---

## Error Handling

When a step fails, `execute()` records the error and continues with remaining steps that are unblocked:

```python
results = await wf.execute(mesh)
failures = [r for r in results if r["status"] != "success"]
for f in failures:
    logger.error("Step %s failed: %s", f["step_id"], f["error"])
```

Steps that depend on a failed step are never executed. Check for blocked steps by comparing the number of results to the number of steps in the workflow:

```python
if len(results) < len(wf.steps):
    blocked = [s.step_id for s in wf.steps if s.step_id not in {r["step_id"] for r in results}]
    logger.warning("Blocked steps: %s", blocked)
```
