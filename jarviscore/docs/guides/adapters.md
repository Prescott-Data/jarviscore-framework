---
icon: material/swap-horizontal
---

# Adapters

JarvisCore's adapter layer lets you bring existing agent code, LangChain agents, CrewAI agents, raw Python objects, or any class with a callable method, into the mesh without inheriting from `AutoAgent` or `CustomAgent`. The framework provides two mechanisms: a class decorator and a function for wrapping instances.

Both are exported directly from `jarviscore`:

```python
from jarviscore import jarvis_agent, wrap
```

---

## When to use adapters

Use adapters when you have **code that already works** and you want JarvisCore to orchestrate it. They bridge existing implementations into the mesh without requiring you to refactor existing code to extend a JarvisCore base class.

If you are building a new agent from scratch, use `AutoAgent` or `CustomAgent` directly, adapters add a layer of indirection that is only worth the cost when wrapping existing code.

---

## `@jarvis_agent`, class decorator

Decorate any class to convert it into a JarvisCore agent. The decorator creates a `CustomAgent` subclass at class definition time and instantiates the original class inside `__init__`.

```python
from jarviscore import jarvis_agent, Mesh

@jarvis_agent(role="processor", capabilities=["data_processing"])
class DataProcessor:
    def run(self, data):
        return {"processed": data * 2}

mesh = Mesh(mode="autonomous")
mesh.add(DataProcessor)
await mesh.start()
```

The decorated class (`DataProcessor`) is replaced by a `CustomAgent` subclass. `mesh.add()` receives that subclass and handles the rest. No changes to the original class definition are required.

### Parameters

| Parameter | Required | Description |
|---|---|---|
| `role` | Yes | Role slug for peer discovery and workflow routing. |
| `capabilities` | Yes | List of capability tags. |
| `execute_method` | No | Method name to call for task execution. Auto-detected from the list below if not provided. |

### Auto-detection order

If `execute_method` is not specified, the decorator inspects the class's MRO and tries these method names in order, stopping at the first callable it finds:

```
run → invoke → execute → call → __call__ → process → handle
```

If none are found, a `ValueError` is raised at decoration time.

### Method signatures

The adapter bridges the JarvisCore task dict to your method's parameters by inspecting the method signature. The following parameter names are mapped automatically:

| Your parameter name | Receives |
|---|---|
| `task` | `task["task"]`, the natural language task string |
| `data` | `task["params"]["data"]` or `task["params"]` |
| `params` | `task["params"]` dict |
| `input`, `query`, `text`, `message` | `task["task"]` string |
| `ctx` or `context` | A `JarvisContext` object (see below) |
| Any other name | `task["params"][name]` or `task["params"]` as fallback |

Methods can be synchronous or `async`, both are supported:

```python
@jarvis_agent(role="analyst", capabilities=["analysis"])
class Analyst:
    async def run(self, task: str):
        result = await some_async_call(task)
        return {"status": "success", "output": result}
```

### Accessing prior step results

If your method accepts `ctx` or `context`, the adapter injects a `JarvisContext` object that provides access to results from earlier workflow steps:

```python
@jarvis_agent(role="aggregator", capabilities=["aggregation"])
class Aggregator:
    def run(self, task: str, ctx):
        step1_result = ctx.previous("enrich")   # result from step with id="enrich"
        step2_result = ctx.previous("classify") # result from step with id="classify"
        return {"merged": {**step1_result, **step2_result}}
```

### Result normalisation

The adapter normalises whatever your method returns into the standard result envelope. If your method returns a plain value or a dict without a `status` key, the adapter wraps it:

```python
# Your method returns: {"name": "Alice", "score": 0.91}
# Adapter produces:   {"status": "success", "output": {"name": "Alice", "score": 0.91}, "agent": "aggregator-a3f2b1c9"}
```

If your method already returns a dict with `status`, it is passed through unchanged (with `agent` added if missing).

### Lifecycle hooks

If your class defines `setup()` or `teardown()` methods, they will be called by the adapter at the right times, both synchronous and async variants are supported:

```python
@jarvis_agent(role="db-reader", capabilities=["database"])
class DatabaseReader:
    async def setup(self):
        self.conn = await connect_to_db()

    def run(self, task: str):
        return self.conn.query(task)

    async def teardown(self):
        await self.conn.close()
```

### Custom execute method name

Use `execute_method` when your class uses a non-standard method name:

```python
@jarvis_agent(
    role="researcher",
    capabilities=["research"],
    execute_method="invoke"
)
class LangChainResearcher:
    def invoke(self, query: str):
        return self.agent.run(query)
```

---

## `wrap()`, instance wrapper

Use `wrap()` when you already have an instantiated object and want to add it to the mesh. The difference from `@jarvis_agent` is purely about timing: the decorator works at class definition time, `wrap()` works on an existing instance.

```python
from jarviscore import wrap, Mesh
from langchain.agents import AgentExecutor

# Build your existing agent however you normally would
langchain_agent = AgentExecutor(agent=my_agent, tools=my_tools)

# Wrap it
wrapped = wrap(
    langchain_agent,
    role="assistant",
    capabilities=["chat", "tools"],
    execute_method="invoke"
)

mesh = Mesh(mode="autonomous")
mesh.add(wrapped)
await mesh.start()
```

### Parameters

| Parameter | Required | Description |
|---|---|---|
| `instance` | Yes | The already-instantiated object to wrap. |
| `role` | Yes | Role slug for peer discovery and workflow routing. |
| `capabilities` | Yes | List of capability tags. |
| `execute_method` | No | Method name to call. Auto-detected from the same list as the decorator if not provided. |

`wrap()` returns a `CustomAgent` instance. `mesh.add()` accepts it directly.

### Auto-detection on instances

Detection for `wrap()` works on the instance rather than the class, it checks for callable attributes via `hasattr`, so dynamically added methods on instances are also found.

---

## Choosing between the two

| Scenario | Use |
|---|---|
| You control the class definition | `@jarvis_agent` |
| You instantiate the object yourself (constructor args, factory) | `wrap()` |
| Third-party class you cannot decorate | `wrap()` |
| You want the cleanest code at the call site | `@jarvis_agent` |

---

## What adapters do not provide

Adapters do not give your wrapped class access to `self._redis_store`, `self.peers`, or other infrastructure attributes injected by the Mesh into native `CustomAgent` subclasses. The adapter creates a thin `CustomAgent` wrapper that handles the routing, but `self` inside your original class's methods still refers to the original instance, not the wrapper.

If you need Redis, P2P, or Nexus access inside the wrapped code, subclass `CustomAgent` directly instead.

---

## Further Reading

- [Agents](../concepts/agents.md), the two native execution models: AutoAgent and CustomAgent
- [CustomAgent Guide](./customagent.md), building agents with full infrastructure access
- [Workflow DAGs](./workflows.md), wiring adapted agents into multi-step workflows
