---
icon: material/robot-outline
---

# Agent API Reference

This is the complete API reference for the two agent profiles and the Mesh orchestrator. All signatures, attribute names, parameter types, and return shapes are sourced from the framework source code.

---

## AutoAgent

```python
from jarviscore.profiles import AutoAgent
```

`AutoAgent` is the framework-managed execution profile. You define three class attributes; the framework handles code generation, sandboxed execution, autonomous repair, and model routing.

### Required class attributes

| Attribute | Type | Description |
|---|---|---|
| `role` | `str` | Agent role identifier. Used by the Mesh for routing and by the Kernel as the fallback sub-agent role. Example: `"researcher"` |
| `capabilities` | `List[str]` | List of capability strings this agent provides. Used by the Mesh workflow engine for task routing. Example: `["research", "analysis"]` |
| `system_prompt` | `str` | System prompt prepended to every Kernel call. Omitting this raises `ValueError` at instantiation. |

### Optional class attributes

| Attribute | Type | Default | Description |
|---|---|---|---|
| `goal_oriented` | `bool` | `False` | When `True`, every `execute_task()` call is routed through the `Plan → Execute → Evaluate` loop. See [Planning](../concepts/planning.md). |
| `default_kernel_role` | `str` | `None` | Fallback sub-agent role when the Planner emits `subagent_hint: null`. Valid values: `"coder"`, `"researcher"`, `"communicator"`, `"browser"`. Leave `None` for generalist agents. |
| `requires_auth` | `bool` | `False` | When `True`, the Mesh creates an `AuthenticationManager` from the Nexus gateway config and injects it as `self._auth_manager` after `setup()`. Requires `NEXUS_GATEWAY_URL` in the environment. |

### Optional environment overrides

| Variable | Default | Description |
|---|---|---|
| `HITL_ENABLED` | `false` | Enable `AdaptiveHITLPolicy`. Escalates on low-confidence or high-risk Kernel actions. |
| `BROWSER_ENABLED` | `false` | Activate `BrowserSubAgent` for web automation tasks. |
| `MAX_GOAL_STEPS` | `30` | Hard step ceiling for goal-oriented agents. |
| `MAX_REPLAN_ATTEMPTS` | `8` | Maximum replanning cycles before the goal is marked failed. |

### execute_task

```python
async def execute_task(task: Dict[str, Any]) -> Dict[str, Any]
```

The primary entry point called by the Mesh workflow engine. You never call this directly.

**Input:**

| Key | Type | Description |
|---|---|---|
| `task` | `str` | Natural language task description |
| `context` | `dict` | Optional context forwarded to the Kernel |

**Return value (standard Kernel path):**

| Key | Type | Description |
|---|---|---|
| `status` | `str` | `"success"`, `"failure"`, or `"yield"` |
| `output` | `Any` | Task result payload |
| `error` | `str \| None` | Error message when status is not `"success"` |
| `tokens` | `dict` | Token usage: `{"input": int, "output": int, "total": int}` |
| `cost_usd` | `float` | Estimated cost in USD |
| `agent_id` | `str` | The agent's unique identifier |
| `role` | `str` | The agent's role |
| `function_id` | `str \| None` | FunctionRegistry atom ID if the task was registered |
| `dispatches` | `list` | Sub-agent dispatch log from the Kernel |
| `result_id` | `str` | Result identifier from the ResultHandler |

**Additional keys when `goal_oriented = True`:**

| Key | Type | Description |
|---|---|---|
| `goal_execution` | `dict` | Summary of the planning loop: `steps`, `facts`, `elapsed_ms`, and plan revision count |

**Return value (legacy fallback path):**

The legacy pipeline is used only if the Kernel raises an unhandled exception. It adds:

| Key | Type | Description |
|---|---|---|
| `code` | `str` | The generated code that was executed |
| `repairs` | `int` | Number of autonomous repair attempts made |

### setup

```python
async def setup() -> None
```

Called by the Mesh before the agent receives any tasks. Initialises the LLM client, search client, code generator, sandbox executor, autonomous repair system, result handler, function registry, and Kernel. Override to add custom initialisation, but always call `await super().setup()` first.

### teardown

```python
async def teardown() -> None
```

Called by the Mesh on shutdown. Override to release resources such as database connections or open file handles.

---

## CustomAgent

```python
from jarviscore.profiles import CustomAgent
```

`CustomAgent` is the user-controlled execution profile. You own the execution logic entirely by implementing `on_peer_request()`. The framework provides P2P message routing, FastAPI lifecycle integration, and Mesh registration.

### Required class attributes

| Attribute | Type | Description |
|---|---|---|
| `role` | `str` | Agent role identifier |
| `capabilities` | `List[str]` | List of capability strings |

### Configuration attributes

| Attribute | Type | Default | Description |
|---|---|---|---|
| `listen_timeout` | `float` | `1.0` | Seconds to wait for a P2P message before looping. Allows periodic `shutdown_requested` checks. |
| `auto_respond` | `bool` | `True` | When `True`, the return value of `on_peer_request()` is automatically sent as the response to the caller. Set to `False` to manage responses manually. |

### on_peer_request

```python
async def on_peer_request(msg) -> Any
```

Primary handler for request-response P2P messages. Override this to implement your agent's logic.

`msg` attributes:

| Attribute | Type | Description |
|---|---|---|
| `msg.sender` | `str` | Sender agent ID or role |
| `msg.data` | `dict` | Request payload |
| `msg.correlation_id` | `str` | Used by the framework for response matching; handled automatically |

Return any value. When `auto_respond = True`, the return value is sent back to the sender automatically. Return `None` to skip the automatic response.

### on_peer_notify

```python
async def on_peer_notify(msg) -> None
```

Handler for fire-and-forget P2P notifications. No response is sent. Override to process events from other agents.

### on_error

```python
async def on_error(error: Exception, msg=None) -> None
```

Called when message processing raises an exception. Default implementation logs the error and continues. Override to add alerting, error tracking, or custom recovery logic.

### execute_task

```python
async def execute_task(task: Dict[str, Any]) -> Dict[str, Any]
```

Called by the Mesh workflow engine. The default implementation wraps the task dict in a synthetic `IncomingMessage` and calls `on_peer_request()`. Override this directly if you need different workflow integration behaviour.

Raises `NotImplementedError` if `on_peer_request()` returns `None` and `execute_task()` has not been overridden.

### run

```python
async def run() -> None
```

The P2P listener loop. Runs continuously in the background when the agent is started via `JarvisLifespan`. Dispatches incoming messages to `on_peer_request()` or `on_peer_notify()` based on message type. You do not need to override this.

---

## Mesh

```python
from jarviscore import Mesh
```

The central orchestrator. Manages agent lifecycle, workflow execution, and infrastructure detection.

### Constructor

```python
Mesh(config: Optional[Dict[str, Any]] = None)
```

| Config key | Type | Default | Description |
|---|---|---|---|
| `redis_url` | `str` | from `REDIS_URL` env | Redis connection string |
| `p2p_enabled` | `bool` | from `P2P_ENABLED` env | Enable SWIM/ZMQ peer transport |
| `checkpoint_interval` | `int` | `1` | Save workflow checkpoints every N steps |
| `max_parallel` | `int` | `5` | Maximum parallel step execution |

The Mesh auto-detects available infrastructure at `start()` time. Do not pass `mode=` — that argument is deprecated and has no effect.

### Methods

#### add

```python
def add(agent_class_or_instance, agent_id: Optional[str] = None, **kwargs) -> Agent
```

Register an agent with the Mesh. Accepts a class (which will be instantiated) or a pre-instantiated agent. Returns the `Agent` instance.

Raises `ValueError` if an agent with the same `agent_id` is already registered, or if a class-based agent with the same `role` is added without an explicit `agent_id`. Raises `TypeError` if the class does not inherit from `Agent`.

#### start

```python
async def start() -> None
```

Probe infrastructure, call `setup()` on all registered agents, inject infrastructure references, and start the workflow engine. Must be called before `workflow()` or `serve_forever()`.

Raises `RuntimeError` if no agents are registered or if `start()` has already been called.

#### workflow

```python
async def workflow(workflow_id: str, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]
```

Execute a multi-step workflow. Returns a list of step results in execution order.

Each step dict:

| Key | Type | Required | Description |
|---|---|---|---|
| `agent` | `str` | Yes | Agent role or capability that should execute this step |
| `task` | `str` | Yes | Natural language task description |
| `depends_on` | `List[int]` | No | Zero-based indices of steps this step depends on |
| `context` | `dict` | No | Additional context passed to `execute_task()` |
| `complexity` | `str` | No | Model tier hint: `"nano"`, `"standard"`, or `"heavy"` |

Raises `RuntimeError` if `start()` has not been called or if the workflow engine is unavailable.

#### stop

```python
async def stop() -> None
```

Request shutdown for all agents, call `teardown()` on each, stop the P2P coordinator and workflow engine, and close all infrastructure connections.

#### has_capability

```python
def has_capability(cap: str) -> bool
```

Check whether an infrastructure capability is active. Capabilities are populated at `start()` time.

| Value | Active when |
|---|---|
| `"workflow"` | Always (workflow engine always starts) |
| `"peer_local"` | Always (in-process routing always available) |
| `"redis"` | `REDIS_URL` is set and reachable |
| `"peer_distributed"` | Redis is active |
| `"peer_swim"` | `P2P_ENABLED=true` and SWIM coordinator started |
| `"blob"` | BlobStorage initialised (local backend always active) |
| `"nexus"` | NexusLocalStore initialised (always active, zero dep) |
| `"athena"` | `ATHENA_URL` is set and reachable |
| `"auth"` | `auth_mode` is set in the Mesh config |
| `"prometheus"` | `PROMETHEUS_ENABLED=true` and metrics server started |

#### serve_forever

```python
async def serve_forever() -> None
```

Block indefinitely, processing incoming tasks from the P2P network. For distributed mode deployments. Handles graceful shutdown on `KeyboardInterrupt`.

---

## JarvisLifespan

```python
from jarviscore.integrations.fastapi import JarvisLifespan
```

FastAPI lifespan manager for JarvisCore agents. Handles Mesh startup, background task management, graceful shutdown, and state injection.

### Constructor

```python
JarvisLifespan(
    agents: Union[Agent, List[Agent]],
    **mesh_config
)
```

| Parameter | Type | Description |
|---|---|---|
| `agents` | `Agent \| List[Agent]` | Single agent or list of agents to register with the Mesh |
| `**mesh_config` | `Any` | Forwarded to `Mesh(config=mesh_config)`. Common keys: `redis_url`, `p2p_enabled`, `bind_port` |

On startup, injects into `app.state`:

| Key | Value |
|---|---|
| `app.state.jarvis_mesh` | The `Mesh` instance |
| `app.state.jarvis_agents` | `Dict[str, Agent]` mapping `role → agent` |

### create_jarvis_app

```python
from jarviscore.integrations.fastapi import create_jarvis_app

def create_jarvis_app(
    agent: Agent,
    title: str = "JarvisCore Agent",
    description: str = "API powered by JarvisCore",
    version: str = "1.0.0",
    **mesh_config
) -> FastAPI
```

Convenience wrapper for single-agent deployments. Creates a `FastAPI` app with `JarvisLifespan` pre-configured. The Mesh auto-detects its operational mode from available infrastructure at startup — no `mode` argument is accepted. For multi-agent deployments or more control, use `JarvisLifespan` directly.

---

## Further Reading

- [AutoAgent guide](../guides/autoagent.md) — usage walkthrough with examples
- [CustomAgent guide](../guides/customagent.md) — usage walkthrough with examples
- [Planning](../concepts/planning.md) — goal-oriented mode for `AutoAgent`
- [Configuration Reference](configuration.md) — all environment variables
- [Chat API Reference](chat-api.md) — HTTP chat endpoint contract
