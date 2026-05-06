# JarvisCore API Reference

Complete API documentation for JarvisCore components.

---

## Table of Contents

1. [Core Components](#core-components)
   - [Mesh](#mesh)
   - [Agent](#agent)
   - [Profile](#profile)
2. [Agent Profiles](#agent-profiles)
   - [AutoAgent](#autoagent)
   - [Custom Profile](#custom-profile)
   - [CustomAgent](#customagent)
3. [P2P Communication (v0.3.0)](#p2p-communication-v030)
   - [PeerClient](#peerclient)
   - [IncomingMessage](#incomingmessage)
   - [Cognitive Discovery](#cognitive-discovery)
4. [Integrations (v0.3.0)](#integrations-v030)
   - [JarvisLifespan](#jarvislifespan)
5. [Execution Components](#execution-components)
   - [CodeGenerator](#codegenerator)
   - [SandboxExecutor](#sandboxexecutor)
   - [AutoRepair](#autorepair)
4. [Storage Components](#storage-components)
   - [ResultHandler](#resulthandler)
   - [CodeRegistry](#coderegistry)
5. [Orchestration](#orchestration)
   - [WorkflowEngine](#workflowengine)
6. [Infrastructure & Memory API (v0.4.0)](#infrastructure--memory-api-v040)
   - [BlobStorage](#blobstorage)
   - [MailboxManager](#mailboxmanager)
   - [UnifiedMemory](#unifiedmemory)
   - [EpisodicLedger](#episodicledger)
   - [LongTermMemory](#longtermemory)
   - [WorkingScratchpad](#workingscratchpad)
   - [RedisMemoryAccessor](#redismemoryaccessor)
   - [AuthenticationManager](#authenticationmanager)
   - [record_step_execution](#record_step_execution)
7. [Utilities](#utilities)
   - [InternetSearch](#internetsearch)
   - [UnifiedLLMClient](#unifiedllmclient)

---

## Core Components

### Mesh

The central orchestrator for managing agents and workflows. Every JarvisCore application creates exactly one Mesh per process. It is responsible for starting and stopping agents, injecting infrastructure (Redis store, blob storage, mailbox) before each agent's `setup()` runs, routing workflow steps to the correct agent by role or capability, and optionally activating the P2P coordinator for multi-node communication.

#### Class: `Mesh`

```python
from jarviscore import Mesh

mesh = Mesh(mode="autonomous")  # or "p2p" or "distributed"
```

**Parameters:**
- `mode` (str): Execution mode
  - `"autonomous"` - Workflow Engine only (single-node)
  - `"p2p"` - P2P Coordinator only (SWIM protocol, ZMQ messaging)
  - `"distributed"` - Both Workflow Engine AND P2P Coordinator
- `config` (dict, optional): Configuration dictionary

**Modes Comparison:**

| Mode | Workflow Engine | P2P Coordinator | Use Case |
|------|-----------------|-----------------|----------|
| `autonomous` | ✅ | ❌ | Single machine, simple pipelines |
| `p2p` | ❌ | ✅ | Agent swarms, real-time coordination |
| `distributed` | ✅ | ✅ | Multi-node production systems |

**Methods:**

#### `add(agent_class)`

Register an agent class in the mesh.

```python
from jarviscore.profiles import AutoAgent

class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculation"]
    system_prompt = "You are a math expert"

mesh.add(CalculatorAgent)
```

**Parameters:**
- `agent_class`: Agent class (AutoAgent or CustomAgent subclass)

**Returns:** Agent instance

---

#### `async start()`

Start the mesh and initialize all agents.

```python
await mesh.start()
```

**Raises:** `RuntimeError` if no agents registered or already started

---

#### `async stop()`

Stop the mesh and cleanup all agents.

```python
await mesh.stop()
```

---

#### `async workflow(workflow_id, steps)`

Execute a multi-step workflow with dependency management.

```python
results = await mesh.workflow("pipeline-id", [
    {"agent": "scraper", "task": "Scrape data from URL"},
    {"agent": "processor", "task": "Clean the data", "depends_on": [0]},
    {"agent": "storage", "task": "Save to database", "depends_on": [1]}
])
```

**Parameters:**
- `workflow_id` (str): Unique workflow identifier
- `steps` (list): List of step dictionaries with keys:
  - `agent` (str): Role or capability of target agent
  - `task` (str): Task description
  - `depends_on` (list, optional): List of step indices/IDs this step depends on
  - `id` (str, optional): Custom step identifier

**Returns:** List of result dictionaries

**Note:** Only available in `autonomous` and `distributed` modes.

---

#### `async run_forever()`

Keep the mesh running until shutdown signal (P2P and distributed modes).

```python
await mesh.run_forever()  # Blocks until SIGINT/SIGTERM
```

**Note:** Only available in `p2p` and `distributed` modes.

---

#### `get_diagnostics() -> dict` (v0.3.2)

Get diagnostic information about mesh health and P2P connectivity.

```python
diag = mesh.get_diagnostics()
print(f"Status: {diag['connectivity_status']}")
print(f"Agents: {len(diag['local_agents'])}")

for peer in diag['known_peers']:
    print(f"  {peer['role']} at {peer['node_id']}: {peer['status']}")
```

**Returns:**
```python
{
    "local_node": {
        "mode": "p2p",           # Current mesh mode
        "started": True,         # Whether mesh is started
        "agent_count": 3,        # Number of local agents
        "bind_address": "127.0.0.1:7950"  # P2P bind address (if P2P)
    },
    "known_peers": [             # Remote peers (if P2P enabled)
        {"role": "analyst", "node_id": "10.0.0.2:7950", "status": "alive"}
    ],
    "local_agents": [            # Local agent info
        {"role": "scout", "agent_id": "scout-abc", "capabilities": ["research"]}
    ],
    "connectivity_status": "healthy",  # Overall health
    "keepalive_status": {...},   # Keepalive manager status (P2P only)
    "swim_status": {...},        # SWIM protocol status (P2P only)
    "capability_map": {...}      # Capability to agent mapping (P2P only)
}
```

**Connectivity Status Values:**
- `"healthy"` - P2P active with connected peers
- `"isolated"` - P2P active but no peers found
- `"degraded"` - Some connectivity issues detected
- `"not_started"` - Mesh not yet started
- `"local_only"` - Autonomous mode (no P2P)

---

### Agent

Base class for all agents. Inherit from this to create custom agents.

#### Class: `Agent`

```python
from jarviscore.core import Agent

class MyAgent(Agent):
    async def execute_task(self, task):
        # Your implementation
        return {"status": "success", "output": result}
```

**Attributes:**
- `agent_id` (str): Unique agent identifier
- `role` (str): Agent role
- `capabilities` (list): List of capabilities
- `mesh`: Reference to parent mesh (set automatically)

**Methods:**

#### `can_handle(task)`

Check if agent can handle a task.

```python
if agent.can_handle({"agent": "calculator"}):
    result = await agent.execute_task(task)
```

**Parameters:**
- `task` (dict): Task dictionary with `agent` or `capability` key

**Returns:** bool

---

#### `async execute_task(task)`

Execute a task (must be implemented by subclasses).

```python
async def execute_task(self, task):
    task_desc = task.get('task', '')
    # Process task
    return {
        "status": "success",
        "output": result,
        "agent": self.agent_id
    }
```

**Parameters:**
- `task` (dict): Task dictionary with `task` key

**Returns:** Result dictionary with `status`, `output`, `agent` keys

---

### Profile

Base class for agent profiles (AutoAgent, CustomAgent).

#### Class: `Profile(Agent)`

```python
from jarviscore.core import Profile

class MyProfile(Profile):
    async def setup(self):
        # Initialize components
        pass
```

**Methods:**

#### `async setup()`

Initialize agent components (called during mesh.start()).

```python
async def setup(self):
    self.llm_client = create_llm_client()
    self.my_tool = MyTool()
```

---

#### `async teardown()`

Cleanup agent resources (called during mesh.stop()).

```python
async def teardown(self):
    await self.llm_client.close()
```

---

## Agent Profiles

### AutoAgent

Autonomous agent profile that auto-generates and executes function tools under Kernel supervision. You define three class attributes — `role`, `capabilities`, and `system_prompt` — and the framework handles the rest: calling the LLM to write code, executing it in a sandboxed environment, auto-repairing failures, and storing results. No manual code generation or sandbox management needed.

#### Class: `AutoAgent(Profile)`

```python
from jarviscore.profiles import AutoAgent

agent = AutoAgent(
    role="researcher",
    capabilities=["research", "web_search"],
    system_prompt="You are a research expert",
    enable_search=True
)
```

**Parameters:**
- `role` (str): Agent role identifier
- `capabilities` (list): List of capability strings
- `system_prompt` (str): LLM system prompt defining agent expertise
- `enable_search` (bool, optional): Enable internet search (default: False)
- `max_repair_attempts` (int, optional): Max code repair attempts (default: 3)

**Features:**
- Automatic LLM-based code generation
- Autonomous code repair (up to 3 attempts)
- Internet search integration (DuckDuckGo)
- Result storage with file-based persistence
- Code registry for function reuse
- Local and remote sandbox execution

**Example:**

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

mesh = Mesh(mode="autonomous")

# Add research agent with internet access
mesh.add_agent(
    AutoAgent,
    role="researcher",
    capabilities=["research", "web_search"],
    system_prompt="You are an expert researcher",
    enable_search=True
)

await mesh.start()

# Execute task
results = await mesh.run_workflow([
    {"agent": "researcher", "task": "Search for Python async tutorials"}
])
```

**AutoAgent Components:**
- `codegen`: CodeGenerator instance
- `sandbox`: SandboxExecutor instance
- `repair`: AutoRepair instance
- `result_handler`: ResultHandler instance
- `code_registry`: CodeRegistry instance
- `search`: InternetSearch instance (if enabled)

---

### Custom Profile

The Custom Profile enables integration of existing agents without modification.

#### Decorator: `@jarvis_agent`

Convert any Python class into a JarvisCore agent:

```python
from jarviscore import jarvis_agent, JarvisContext

@jarvis_agent(role="processor", capabilities=["data_processing"])
class DataProcessor:
    def run(self, data):
        return {"processed": [x * 2 for x in data]}
```

**Parameters:**
- `role` (str): Agent role identifier
- `capabilities` (list): List of capability strings
- `execute_method` (str, optional): Method name to call (default: auto-detect)

**Auto-detected Methods:** `run`, `execute`, `invoke`, `call`, `process`

**Context-Aware Methods:**

If your method has a parameter named `ctx` or `context`, JarvisContext is automatically injected:

```python
@jarvis_agent(role="aggregator", capabilities=["aggregation"])
class Aggregator:
    def run(self, task, ctx: JarvisContext):
        previous = ctx.previous("step1")
        return {"result": previous}
```

---

#### Function: `wrap()`

Wrap an existing instance as a JarvisCore agent:

```python
from jarviscore import wrap

wrapped = wrap(
    instance=my_langchain_agent,
    role="assistant",
    capabilities=["chat", "qa"],
    execute_method="invoke"
)
```

**Parameters:**
- `instance` (Any): Pre-instantiated object to wrap
- `role` (str): Agent role identifier
- `capabilities` (list): List of capability strings
- `execute_method` (str, optional): Method name to call (default: auto-detect)

**Returns:** `CustomAgent` instance ready for `mesh.add()`

**Example:**

```python
from jarviscore import Mesh, wrap

# Your existing LangChain agent
my_agent = MyLangChainAgent(model="gpt-4")

# Wrap it
wrapped = wrap(
    my_agent,
    role="assistant",
    capabilities=["chat"],
    execute_method="invoke"
)

mesh = Mesh(mode="autonomous")
mesh.add(wrapped)  # Add directly to mesh
await mesh.start()
```

---

#### Class: `JarvisContext`

Provides workflow context access for Custom Profile agents:

```python
from jarviscore import JarvisContext

def run(self, task, ctx: JarvisContext):
    # Access previous step outputs
    step1_output = ctx.previous("step1")

    # Get all previous outputs
    all_outputs = ctx.all_previous()

    # Access shared memory
    ctx.memory["key"] = "value"
    value = ctx.memory.get("key")

    return {"result": "..."}
```

**Attributes:**
- `workflow_id` (str): Current workflow identifier
- `step_id` (str): Current step identifier
- `task` (str): Task description
- `params` (dict): Task parameters
- `memory` (MemoryAccessor): Shared workflow memory

**Methods:**

#### `previous(step_id: str) -> Optional[Any]`

Get output from a specific previous step.

```python
step1_output = ctx.previous("step1")
if step1_output:
    data = step1_output.get("processed", [])
```

**Parameters:**
- `step_id` (str): ID of the step to retrieve

**Returns:** Step output or None if not found

---

#### `all_previous() -> Dict[str, Any]`

Get outputs from all previous steps.

```python
all_outputs = ctx.all_previous()
# {"step1": {...}, "step2": {...}}

for step_id, output in all_outputs.items():
    print(f"{step_id}: {output}")
```

**Returns:** Dictionary mapping step IDs to their outputs

---

#### Class: `MemoryAccessor`

Dictionary-like interface for shared workflow memory:

```python
# Set value
ctx.memory["key"] = "value"

# Get value
value = ctx.memory.get("key", "default")

# Check existence
if "key" in ctx.memory:
    ...

# Get all memory
all_memory = ctx.memory.all()
```

**Methods:**
- `get(key, default=None)` - Get value with optional default
- `set(key, value)` - Set value
- `all()` - Get entire memory dictionary
- `__getitem__`, `__setitem__`, `__contains__` - Dict-like access

---

### CustomAgent

Flexible agent profile for integrating existing code, frameworks, or deterministic logic. You implement `execute_task()` for workflow steps, `on_peer_request()` for P2P messaging, or both. No LLM or sandbox is required — CustomAgent simply calls the methods you define and returns whatever you return. Infrastructure (Redis store, blob storage, mailbox) is auto-injected before `setup()` runs.

#### Class: `CustomAgent(Profile)`

```python
from jarviscore.profiles import CustomAgent

class MyAgent(CustomAgent):
    role = "my_role"
    capabilities = ["my_capability"]

    async def setup(self):
        await super().setup()
        # Initialize your resources

    async def execute_task(self, task):
        """Called by workflow engine (autonomous/distributed modes)."""
        return {"status": "success", "output": result}

    async def run(self):
        """Called in P2P mode - continuous run loop."""
        while not self.shutdown_requested:
            msg = await self.peers.receive(timeout=0.5)
            if msg and msg.is_request:
                await self.peers.respond(msg, {"response": "..."})
```

**Class Attributes:**
- `role` (str): Agent role identifier (required)
- `capabilities` (list): List of capability strings (required)

**Instance Attributes:**
- `agent_id` (str): Unique agent identifier
- `peers` (PeerTool): P2P communication tool (distributed/p2p modes)
- `shutdown_requested` (bool): Set to True when shutdown requested

**Key Methods:**

| Method | Purpose | Mode |
|--------|---------|------|
| `setup()` | Initialize resources | All |
| `execute_task(task)` | Handle workflow steps | Autonomous/Distributed |
| `run()` | Continuous loop | P2P |
| `teardown()` | Cleanup resources | All |

**P2P Communication (distributed/p2p modes):**

```python
async def run(self):
    while not self.shutdown_requested:
        # Receive messages
        msg = await self.peers.receive(timeout=0.5)
        if msg and msg.is_request:
            # Process and respond
            await self.peers.respond(msg, {"response": result})

async def ask_another_agent(self, question):
    # Ask another agent via peer tools
    result = await self.peers.as_tool().execute(
        "ask_peer",
        {"role": "researcher", "question": question}
    )
    return result
```

See [CustomAgent Guide](CUSTOMAGENT_GUIDE.md) for P2P and distributed mode details.

---

#### P2P Message Handlers

CustomAgent includes built-in P2P message handlers:

#### `async on_peer_request(msg) -> dict`

Handle incoming request messages. Return value is sent back to requester.

```python
async def on_peer_request(self, msg):
    query = msg.data.get("question", "")
    result = self.process(query)
    return {"response": result, "status": "success"}
```

**Parameters:**
- `msg` (IncomingMessage): Incoming message with `data`, `sender`, `correlation_id`

**Returns:** dict - Response sent back to requester (if `auto_respond=True`)

---

#### `async on_peer_notify(msg) -> None`

Handle broadcast notifications. No return value needed.

```python
async def on_peer_notify(self, msg):
    event_type = msg.data.get("type")
    if event_type == "status_update":
        self.handle_status(msg.data)
```

**Parameters:**
- `msg` (IncomingMessage): Incoming notification message

**Returns:** None

---

#### `async on_error(error, msg) -> None`

Handle errors during message processing.

```python
async def on_error(self, error, msg):
    self._logger.error(f"Error processing message: {error}")
```

**Parameters:**
- `error` (Exception): The exception that occurred
- `msg` (IncomingMessage, optional): The message being processed

---

#### Configuration Attributes

- `listen_timeout` (float): Seconds to wait for messages in run loop (default: 1.0)
- `auto_respond` (bool): Automatically send on_peer_request return value (default: True)

---

#### Self-Registration Methods

#### `async join_mesh(seed_nodes, advertise_endpoint=None)`

Join an existing mesh without central orchestrator.

```python
await agent.join_mesh(
    seed_nodes="10.0.0.1:7950,10.0.0.2:7950",
    advertise_endpoint="my-pod:7950"
)
```

**Parameters:**
- `seed_nodes` (str): Comma-separated list of seed node addresses
- `advertise_endpoint` (str, optional): Address for other nodes to reach this agent

---

#### `async leave_mesh()`

Gracefully leave the mesh network.

```python
await agent.leave_mesh()
```

---

## P2P Communication (v0.3.0)

### PeerClient

Client for peer-to-peer communication, available as `self.peers` on agents.

#### Class: `PeerClient`

**Methods:**

---

### Discovery Methods (v0.3.2)

#### `discover(capability=None, role=None, strategy="first") -> List[PeerInfo]`

Discover peers with optional load balancing strategy.

```python
# Default: return in discovery order
peers = self.peers.discover(role="worker")

# Random: shuffle for load distribution
peers = self.peers.discover(role="worker", strategy="random")

# Round robin: rotate through peers on each call
peers = self.peers.discover(role="worker", strategy="round_robin")

# Least recent: return least recently used peers first
peers = self.peers.discover(role="worker", strategy="least_recent")
```

**Parameters:**
- `capability` (str, optional): Filter by capability
- `role` (str, optional): Filter by role
- `strategy` (str): Selection strategy - `"first"`, `"random"`, `"round_robin"`, `"least_recent"`

**Returns:** List of PeerInfo objects ordered by strategy

---

#### `discover_one(capability=None, role=None, strategy="first") -> Optional[PeerInfo]`

Discover a single peer (convenience wrapper for discover).

```python
worker = self.peers.discover_one(role="worker", strategy="round_robin")
if worker:
    await self.peers.request(worker.agent_id, {"task": "..."})
```

**Returns:** Single PeerInfo or None if no match

---

#### `record_peer_usage(peer_id: str)`

Record that a peer was used (for `least_recent` strategy tracking).

```python
peer = self.peers.discover_one(role="worker", strategy="least_recent")
response = await self.peers.request(peer.agent_id, {"task": "..."})
self.peers.record_peer_usage(peer.agent_id)  # Update usage timestamp
```

---

### Messaging Methods (v0.3.2 - Context Support)

#### `async notify(target, message, context=None) -> bool`

Send a fire-and-forget notification with optional context.

```python
await self.peers.notify("analyst", {
    "event": "task_complete",
    "data": result
}, context={"mission_id": "m-123", "priority": "high"})
```

**Parameters:**
- `target` (str): Target agent role or agent_id
- `message` (dict): Message payload
- `context` (dict, optional): Metadata (mission_id, priority, trace_id, etc.)

---

#### `async request(target, message, timeout=30.0, context=None) -> Optional[dict]`

Send request and wait for response with optional context.

```python
response = await self.peers.request("analyst", {
    "query": "analyze this data"
}, timeout=10, context={"mission_id": "m-123"})
```

**Parameters:**
- `target` (str): Target agent role or agent_id
- `message` (dict): Request payload
- `timeout` (float): Max seconds to wait (default: 30)
- `context` (dict, optional): Metadata propagated with request

---

#### `async respond(message, response, context=None) -> bool`

Respond to an incoming request. Auto-propagates context if not overridden.

```python
async def on_peer_request(self, msg):
    result = process(msg.data)
    # Context auto-propagated from msg.context
    await self.peers.respond(msg, {"result": result})

    # Or override with custom context
    await self.peers.respond(msg, {"result": result},
                            context={"status": "completed"})
```

**Parameters:**
- `message` (IncomingMessage): The incoming request
- `response` (dict): Response data
- `context` (dict, optional): Override context (defaults to request's context)

---

#### `async broadcast(message, context=None) -> int`

Broadcast notification to all peers with optional context.

```python
count = await self.peers.broadcast({
    "event": "status_update",
    "status": "ready"
}, context={"broadcast_id": "bc-123"})
```

**Returns:** Number of peers notified

---

### Async Request Pattern (v0.3.2)

#### `async ask_async(target, message, timeout=120.0, context=None) -> str`

Send request without blocking for response. Returns request_id immediately.

```python
# Fire off multiple requests in parallel
request_ids = []
for analyst in analysts:
    req_id = await self.peers.ask_async(analyst, {"task": "analyze"})
    request_ids.append(req_id)

# Do other work while waiting...
await process_other_tasks()

# Collect responses later
for req_id in request_ids:
    response = await self.peers.check_inbox(req_id, timeout=5)
```

**Parameters:**
- `target` (str): Target agent role or agent_id
- `message` (dict): Request payload
- `timeout` (float): Max time to keep request active (default: 120s)
- `context` (dict, optional): Request context

**Returns:** Request ID string for use with `check_inbox()`

**Raises:** `ValueError` if target not found or send fails

---

#### `async check_inbox(request_id, timeout=0.0, remove=True) -> Optional[dict]`

Check for response to an async request.

```python
# Non-blocking check
response = await self.peers.check_inbox(req_id)

# Wait up to 5 seconds
response = await self.peers.check_inbox(req_id, timeout=5)

# Peek without removing
response = await self.peers.check_inbox(req_id, remove=False)
```

**Parameters:**
- `request_id` (str): ID returned by `ask_async()`
- `timeout` (float): Seconds to wait (0 = immediate return)
- `remove` (bool): Remove from inbox after reading (default: True)

**Returns:** Response dict if available, None if not ready or timed out

---

#### `get_pending_async_requests() -> List[dict]`

Get list of pending async requests.

```python
pending = self.peers.get_pending_async_requests()
for req in pending:
    print(f"Waiting for {req['target']} since {req['sent_at']}")
```

**Returns:** List of dicts with `request_id`, `target`, `sent_at`, `timeout`

---

#### `clear_inbox(request_id=None)`

Clear async request inbox.

```python
# Clear specific request
self.peers.clear_inbox(req_id)

# Clear all
self.peers.clear_inbox()
```

---

#### `get_cognitive_context() -> str`

Generate LLM-ready text describing available peers.

```python
if self.peers:
    context = self.peers.get_cognitive_context()
    # Returns:
    # "Available Peers:
    # - analyst (capabilities: analysis, data_interpretation)
    #   Use ask_peer with role="analyst" for analysis tasks
    # - researcher (capabilities: research, web_search)
    #   Use ask_peer with role="researcher" for research tasks"
```

**Returns:** str - Human-readable peer descriptions for LLM prompts

---

#### `list() -> List[PeerInfo]`

Get list of connected peers.

```python
peers = self.peers.list()
for peer in peers:
    print(f"{peer.role}: {peer.capabilities}")
```

**Returns:** List of PeerInfo objects

---

#### `as_tool() -> PeerTool`

Get peer tools for LLM tool use.

```python
tools = self.peers.as_tool()
result = await tools.execute("ask_peer", {"role": "analyst", "question": "..."})
```

**Available Tools:**
- `ask_peer` - Send request and wait for response
- `broadcast` - Send notification to all peers
- `list_peers` - List available peers

---

#### `async receive(timeout) -> IncomingMessage`

Receive next message (for CustomAgent manual loops).

```python
msg = await self.peers.receive(timeout=0.5)
if msg and msg.is_request:
    await self.peers.respond(msg, {"result": "..."})
```

---

#### `async respond(msg, data) -> None`

Respond to a request message.

```python
await self.peers.respond(msg, {"status": "success", "result": data})
```

---

### IncomingMessage

Message received from a peer.

#### Class: `IncomingMessage`

**Attributes:**
- `sender` (str): Agent ID of the sender
- `sender_node` (str): P2P node ID of the sender
- `type` (MessageType): Message type (NOTIFY, REQUEST, RESPONSE)
- `data` (dict): Message payload
- `correlation_id` (str, optional): ID linking request to response
- `timestamp` (float): When the message was sent
- `context` (dict, optional): Metadata (mission_id, priority, trace_id, etc.) - *v0.3.2*

**Properties:**
- `is_request` (bool): True if this is a request expecting response
- `is_notify` (bool): True if this is a notification

```python
async def on_peer_request(self, msg):
    print(f"From: {msg.sender}")
    print(f"Data: {msg.data}")

    # Access context metadata (v0.3.2)
    if msg.context:
        mission_id = msg.context.get("mission_id")
        priority = msg.context.get("priority")

    return {"received": True}
```

---

### Cognitive Discovery

Dynamic peer awareness for LLM prompts.

**Pattern:**

```python
class MyAgent(CustomAgent):
    def get_system_prompt(self) -> str:
        base = "You are a helpful assistant."

        # Dynamically add peer context
        if self.peers:
            peer_context = self.peers.get_cognitive_context()
            return f"{base}\n\n{peer_context}"

        return base
```

**Benefits:**
- No hardcoded agent names in prompts
- Automatically updates when peers join/leave
- LLM always knows current capabilities

---

## Integrations (v0.3.0)

### JarvisLifespan

FastAPI lifespan context manager for automatic agent lifecycle management.

#### Class: `JarvisLifespan`

```python
from jarviscore.integrations.fastapi import JarvisLifespan

app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p"))
```

**Parameters:**
- `agent`: CustomAgent instance (or list of agents)
- `mode` (str): "p2p" or "distributed"
- `bind_port` (int, optional): P2P port (default: 7950)
- `seed_nodes` (str, optional): Comma-separated seed node addresses

**Example:**

```python
from fastapi import FastAPI
from jarviscore.profiles import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan


class ProcessorAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": "processed"}


agent = ProcessorAgent()
app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p", bind_port=7950))


@app.post("/process")
async def process(data: dict):
    # Agent is already running and connected to mesh
    return {"status": "ok"}
```

**Handles:**
- Agent setup and teardown
- Mesh initialization
- Background run loop (runs agent.run())
- Graceful shutdown

---

## Execution Components

### CodeGenerator

LLM-based Python code generation from natural language.

#### Class: `CodeGenerator`

```python
from jarviscore.execution import create_code_generator

codegen = create_code_generator(llm_client, search_client)
```

**Parameters:**
- `llm_client`: UnifiedLLMClient instance
- `search_client` (optional): InternetSearch instance

**Methods:**

#### `async generate(task, system_prompt, context=None, enable_search=True)`

Generate Python code for a task.

```python
code = await codegen.generate(
    task={"task": "Calculate factorial of 10"},
    system_prompt="You are a math expert",
    enable_search=False
)
```

**Parameters:**
- `task` (dict): Task dictionary with `task` key
- `system_prompt` (str): Agent's system prompt
- `context` (dict, optional): Context from previous steps
- `enable_search` (bool): Auto-inject search tools if available

**Returns:** Python code string

**Features:**
- Automatic syntax validation
- Code cleaning (removes markdown, comments)
- Search tool auto-injection for research tasks
- Context-aware code generation

---

### SandboxExecutor

The sandbox is the isolated Python environment where AutoAgent-generated code runs. It restricts available builtins and imports, injects workflow context as namespace variables, and captures the `result` variable as the step's output. It supports two modes: `local` (in-process, fast, for development) and `remote` (Azure Container Apps, full process isolation for production).

#### Class: `SandboxExecutor`

```python
from jarviscore.execution import create_sandbox_executor

executor = create_sandbox_executor(
    timeout=300,
    search_client=None,
    config={
        'sandbox_mode': 'remote',
        'sandbox_service_url': 'https://...'
    }
)
```

**Parameters:**
- `timeout` (int): Max execution time in seconds (default: 300)
- `search_client` (optional): InternetSearch for web access
- `config` (dict, optional): Configuration with:
  - `sandbox_mode`: "local" or "remote"
  - `sandbox_service_url`: URL for remote sandbox

**Methods:**

#### `async execute(code, timeout=None, context=None)`

Execute Python code in isolated sandbox.

```python
result = await executor.execute(
    code="result = 2 + 2",
    timeout=10,
    context={"previous_result": 42}
)
```

**Parameters:**
- `code` (str): Python code to execute
- `timeout` (int, optional): Override default timeout
- `context` (dict, optional): Variables to inject into namespace

**Returns:**
```python
{
    "status": "success" | "failure",
    "output": Any,  # Value of 'result' variable
    "error": str,  # Error message if failed
    "error_type": str,  # Exception type
    "execution_time": float,  # Seconds
    "mode": "local" | "remote"
}
```

**Execution Modes:**

**Local Mode** (default):
- In-process execution with isolated namespace
- Fast, no network latency
- Perfect for development

**Remote Mode** (production):
- Azure Container Apps sandbox
- Full isolation, better security
- Automatic fallback to local on failure

**Example:**
```python
# Async code execution
code = """
async def main():
    results = await search.search("Python tutorials")
    return results
"""

result = await executor.execute(code, timeout=30)
print(result['output'])  # Search results
```

---

### AutoRepair

Autonomous code repair with LLM-guided error fixing.

#### Class: `AutoRepair`

```python
from jarviscore.execution import create_auto_repair

repair = create_auto_repair(llm_client, max_attempts=3)
```

**Parameters:**
- `llm_client`: UnifiedLLMClient instance
- `max_attempts` (int): Maximum repair attempts (default: 3)

**Methods:**

#### `async repair(code, error_msg, error_type, task, system_prompt)`

Attempt to fix broken code.

```python
fixed_code = await repair.repair(
    code=broken_code,
    error_msg="NameError: name 'x' is not defined",
    error_type="NameError",
    task="Calculate sum of numbers",
    system_prompt="You are a Python expert"
)
```

**Parameters:**
- `code` (str): Broken code
- `error_msg` (str): Error message from execution
- `error_type` (str): Exception type
- `task` (str): Original task description
- `system_prompt` (str): Agent's system prompt

**Returns:** Fixed code string or raises exception

---

## Storage Components

### ResultHandler

File-based storage for execution results with in-memory caching.

#### Class: `ResultHandler`

```python
from jarviscore.execution import create_result_handler

handler = create_result_handler(log_directory="./logs")
```

**Parameters:**
- `log_directory` (str): Base directory for result storage (default: "./logs")
- `cache_size` (int): Max results in memory cache (default: 1000)

**Methods:**

#### `process_result(...)`

Store execution result.

```python
stored = handler.process_result(
    agent_id="calculator-abc123",
    task="Calculate factorial",
    code="result = math.factorial(10)",
    output=3628800,
    status="success",
    execution_time=0.001,
    repairs=0
)
```

**Parameters:**
- `agent_id` (str): Agent identifier
- `task` (str): Task description
- `code` (str): Executed code
- `output` (Any): Execution output
- `status` (str): "success" or "failure"
- `error` (str, optional): Error message
- `execution_time` (float, optional): Execution time in seconds
- `tokens` (dict, optional): Token usage `{input, output, total}`
- `cost_usd` (float, optional): Cost in USD
- `repairs` (int, optional): Number of repair attempts
- `metadata` (dict, optional): Additional metadata

**Returns:**
```python
{
    "result_id": "calculator-abc123_2026-01-12T12-00-00_123456",
    "agent_id": "calculator-abc123",
    "task": "Calculate factorial",
    "output": 3628800,
    "status": "success",
    "timestamp": "2026-01-12T12:00:00.123456",
    # ... more fields
}
```

**Storage:**
- File: `./logs/{agent_id}/{result_id}.json`
- Cache: In-memory LRU cache (1000 results)

---

#### `get_result(result_id)`

Retrieve a specific result (checks cache first, then file).

```python
result = handler.get_result("calculator-abc123_2026-01-12T12-00-00_123456")
```

---

#### `get_agent_results(agent_id, limit=10)`

Get recent results for an agent.

```python
recent = handler.get_agent_results("calculator-abc123", limit=5)
```

---

### CodeRegistry

Searchable storage for generated code functions.

#### Class: `CodeRegistry`

```python
from jarviscore.execution import create_code_registry

registry = create_code_registry(registry_directory="./logs/code_registry")
```

**Parameters:**
- `registry_directory` (str): Directory for registry storage

**Methods:**

#### `register(code, agent_id, task, capabilities, output, result_id=None)`

Register generated code in the registry.

```python
function_id = registry.register(
    code="result = math.factorial(10)",
    agent_id="calculator-abc123",
    task="Calculate factorial of 10",
    capabilities=["math", "calculation"],
    output=3628800,
    result_id="calculator-abc123_2026-01-12T12-00-00_123456"
)
```

**Parameters:**
- `code` (str): Python code
- `agent_id` (str): Agent identifier
- `task` (str): Task description
- `capabilities` (list): Agent capabilities
- `output` (Any): Sample output
- `result_id` (str, optional): Associated result ID

**Returns:** function_id string

**Storage:**
- Index: `./logs/code_registry/index.json`
- Code: `./logs/code_registry/functions/{function_id}.py`

---

#### `search(query, capabilities=None, limit=5)`

Search for registered functions.

```python
matches = registry.search(
    query="factorial calculation",
    capabilities=["math"],
    limit=3
)
```

**Parameters:**
- `query` (str): Search keywords
- `capabilities` (list, optional): Filter by capabilities
- `limit` (int): Max results (default: 5)

**Returns:** List of matching function metadata

---

#### `get(function_id)`

Get function details including code.

```python
func = registry.get("calculator-abc123_3a5b2f76")
print(func['code'])  # Print the code
```

---

## Orchestration

### WorkflowEngine

Multi-step workflow execution with dependency management.

#### Class: `WorkflowEngine`

```python
from jarviscore.orchestration import WorkflowEngine

engine = WorkflowEngine(mesh, p2p_coordinator=None)
```

**Parameters:**
- `mesh`: Mesh instance
- `p2p_coordinator` (optional): P2P coordinator for distributed execution
- `config` (dict, optional): Configuration

**Methods:**

#### `async execute(workflow_id, steps)`

Execute workflow with dependency resolution.

```python
results = await engine.execute(
    workflow_id="pipeline-1",
    steps=[
        {"id": "fetch", "agent": "scraper", "task": "Fetch data"},
        {"id": "process", "agent": "processor", "task": "Process data", "depends_on": ["fetch"]},
        {"id": "save", "agent": "storage", "task": "Save results", "depends_on": ["process"]}
    ]
)
```

**Parameters:**
- `workflow_id` (str): Unique workflow identifier
- `steps` (list): List of step dictionaries

**Step Format:**
```python
{
    "id": "step_id",  # Optional, auto-generated if missing
    "agent": "role_or_capability",
    "task": "Task description",
    "depends_on": ["step1", "step2"]  # Optional dependencies
}
```

**Dependency Injection:**

Dependent steps automatically receive context:
```python
task['context'] = {
    'previous_step_results': {
        'step1': <output from step1>,
        'step2': <output from step2>
    },
    'workflow_id': 'pipeline-1',
    'step_id': 'current_step'
}
```

---

## Infrastructure & Memory API (v0.4.0)

### BlobStorage

Save and load arbitrary artifacts (string, bytes, JSON) to local filesystem or Azure Blob.

```python
from jarviscore.storage import LocalBlobStorage, AzureBlobStorage

# LocalBlobStorage — default, writes to STORAGE_BASE_PATH (default: ./blob_storage/)
storage = LocalBlobStorage(base_path="./blob_storage")

# Auto-injected as agent._blob_storage before setup()
```

#### `async save(path, data)`

```python
await agent._blob_storage.save("reports/wf-001/summary.md", markdown_text)
await agent._blob_storage.save("data/wf-001/result.json", json.dumps(data))
```

**Parameters:**
- `path` (str): Relative path within blob storage. Convention: `{type}/{workflow_id}/{filename}.{ext}`
- `data` (str | bytes): Content to save

#### `async load(path)`

```python
content = await agent._blob_storage.load("reports/wf-001/summary.md")
# Returns str | bytes | None (None if path does not exist)
```

**Config:**

| Env var | Default | Description |
|---------|---------|-------------|
| `STORAGE_BACKEND` | `local` | `local` or `azure` |
| `STORAGE_BASE_PATH` | `./blob_storage` | Root directory for local storage |

---

### MailboxManager

Async inter-agent messaging via Redis Streams. Auto-injected as `agent.mailbox`.

```python
# Auto-injected before setup() when REDIS_URL is set
# agent.mailbox : MailboxManager
```

#### `send(target_id, message)`

Fire-and-forget message to any agent by its `agent_id`:

```python
agent.mailbox.send("technical_support-a1b2c3d4", {"query": "API down", "customer_id": "cust-42"})
```

**Parameters:**
- `target_id` (str): Recipient's `agent_id` (e.g. `"{role}-{uuid8}"`)
- `message` (dict): Arbitrary payload

#### `read(max_messages=10)`

Drain the agent's inbox:

```python
messages = agent.mailbox.read(max_messages=10)
for msg in messages:
    # msg is the dict passed to send()
    print(msg["query"])
```

**Returns:** `List[dict]`

**Requires:** `REDIS_URL`

---

### UnifiedMemory

Unified memory stack per agent step: episodic ledger + long-term memory + working scratchpad.

```python
from jarviscore.memory import UnifiedMemory

memory = UnifiedMemory(
    workflow_id="wf-001",
    step_id="analyst",
    agent_id="analyst",
    redis_store=agent._redis_store,
    blob_storage=agent._blob_storage,
)
```

**Attributes:**
- `.episodic` → `EpisodicLedger`
- `.ltm` → `LongTermMemory`
- `.scratch` → `WorkingScratchpad`

---

### EpisodicLedger

Redis Streams-backed event log per workflow.

```python
memory.episodic  # EpisodicLedger instance
```

#### `async append(event)`

```python
await memory.episodic.append({"event": "task_started", "step": "analyst", "ts": time.time()})
```

**Parameters:**
- `event` (dict): Arbitrary event payload. Stored in Redis stream `ledgers:{workflow_id}`

#### `async tail(count)`

```python
recent = await memory.episodic.tail(5)
# Returns list of dicts, most-recent first
```

**Returns:** `List[dict]`

**Redis key:** `ledgers:{workflow_id}` (Redis Stream, XADD / XREVRANGE)

---

### LongTermMemory

Single-key Redis summary per workflow — persists across runs.

```python
memory.ltm  # LongTermMemory instance
```

#### `async save_summary(text)`

```python
await memory.ltm.save_summary("Key findings: AI chip demand up 40% QoQ.")
```

#### `async load_summary()`

```python
summary = await memory.ltm.load_summary()  # str | None
```

**Redis key:** `ltm:{workflow_id}`

---

### WorkingScratchpad

In-memory key/value store (not persisted):

```python
memory.scratch.set("draft", article_text)
draft = memory.scratch.get("draft", default="")
memory.scratch.clear()
```

---

### RedisMemoryAccessor

Read any prior step's output from Redis without explicit data passing.

```python
from jarviscore.memory import RedisMemoryAccessor

accessor = RedisMemoryAccessor(agent._redis_store, workflow_id="wf-001")
```

#### `get(step_id)`

```python
raw = accessor.get("fetch")
# raw is the dict stored by WorkflowEngine after the "fetch" step completed
# Unwrap pattern:
data = raw.get("output", raw) if isinstance(raw, dict) else {}
```

**Returns:** `dict | None`

**Redis key read:** `step_output:{workflow_id}:{step_id}`

---

### AuthenticationManager

Injected as `agent._auth_manager` when `agent.requires_auth = True` and
`NEXUS_GATEWAY_URL` is set. `None` otherwise (graceful degradation).

```python
class SecureAgent(CustomAgent):
    requires_auth = True  # triggers injection
```

#### `async make_authenticated_request(provider, method, url, **kwargs)`

```python
result = await agent._auth_manager.make_authenticated_request(
    provider="github",
    method="GET",
    url="https://api.github.com/user",
)
# result: dict with status_code, headers, body
```

**Full Nexus flow (first call per provider):**
1. `request_connection(provider, user_id, scopes)` → POST `/v1/request-connection`
2. `CLIFlowHandler.present_auth_url(auth_url)` → opens browser or prints URL
3. `wait_for_completion()` → polls `GET /v1/check-connection/{id}` every 2s until `ACTIVE`
4. `resolve_strategy(connection_id)` → `GET /v1/token/{id}` → `DynamicStrategy`
5. `apply_strategy_to_request(strategy, method, url)` → injects `Authorization` header

**Config:**

| Key | Description |
|-----|-------------|
| `auth_mode` | `"production"` \| `"mock"` |
| `nexus_gateway_url` | URL of deployed Dromos gateway |
| `nexus_default_user_id` | User ID sent in connection requests |
| `auth_open_browser` | `True` (default) — open browser for OAuth consent |

---

### record_step_execution

```python
from jarviscore.telemetry.metrics import record_step_execution

record_step_execution(duration: float, status: str) -> None
```

**Parameters:**
- `duration` (float): Step execution time in seconds
- `status` (str): `"success"` or `"failure"`

**Metrics emitted:**
- `jarviscore_step_duration_seconds` — Histogram, labelled by `status`
- `jarviscore_steps_total` — Counter, labelled by `status`

**Enable:** `PROMETHEUS_ENABLED=true`, `PROMETHEUS_PORT=9090`

**Guard (when prometheus-client not installed):**
```python
try:
    from prometheus_client import Counter, Histogram
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
```

---

## Utilities

### InternetSearch

Web search integration using DuckDuckGo.

#### Class: `InternetSearch`

```python
from jarviscore.tools import create_internet_search

search = create_internet_search()
```

**Methods:**

#### `async search(query, max_results=5)`

Search the web.

```python
results = await search.search("Python asyncio tutorial", max_results=3)
```

**Returns:**
```python
[
    {
        "title": "Page title",
        "snippet": "Description...",
        "url": "https://..."
    },
    ...
]
```

---

#### `async extract_content(url, max_length=10000)`

Extract text content from URL.

```python
content = await search.extract_content("https://example.com")
```

**Returns:**
```python
{
    "title": "Page title",
    "content": "Extracted text...",
    "success": true
}
```

---

#### `async search_and_extract(query, num_results=3)`

Combined search and content extraction.

```python
results = await search.search_and_extract("Python tutorials", num_results=2)
```

---

### UnifiedLLMClient

Multi-provider LLM client with automatic fallback.

#### Class: `UnifiedLLMClient`

```python
from jarviscore.execution import create_llm_client

llm = create_llm_client(config)
```

**Supported Providers:**
1. Claude (Anthropic)
2. vLLM (self-hosted)
3. Azure OpenAI
4. Google Gemini

**Methods:**

#### `async generate(prompt, system_msg=None, temperature=0.7, max_tokens=4000)`

Generate text from prompt.

```python
response = await llm.generate(
    prompt="Write Python code to calculate factorial",
    system_msg="You are a Python expert",
    temperature=0.3,
    max_tokens=2000
)
```

**Returns:**
```python
{
    "content": "Generated text",
    "provider": "claude",
    "model": "claude-sonnet-4",
    "tokens": {"input": 100, "output": 50, "total": 150},
    "cost_usd": 0.05
}
```

**Automatic Fallback:**
- Tries providers in order: Claude → vLLM → Azure → Gemini
- Switches on API errors or rate limits
- Logs provider switches

---

## Configuration

See [Configuration Guide](CONFIGURATION.md) for environment variable reference.

---

## Error Handling

All async methods may raise:
- `RuntimeError`: Component not initialized or configuration error
- `ValueError`: Invalid parameters or data
- `TimeoutError`: Operation exceeded timeout
- `ExecutionTimeout`: Code execution timeout (sandbox)

**Example:**
```python
try:
    result = await agent.execute_task(task)
except TimeoutError:
    print("Task timed out")
except RuntimeError as e:
    print(f"Runtime error: {e}")
```

---

## Type Hints

JarvisCore uses Python type hints for better IDE support:

```python
from typing import Dict, List, Any, Optional

async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
    ...
```

---

## Best Practices

1. **Always use async/await**: JarvisCore is fully async
2. **Call mesh.start() before execution**: Initializes all agents
3. **Call mesh.stop() on shutdown**: Cleanup resources
4. **Use context managers where possible**: Automatic cleanup
5. **Handle errors gracefully**: Operations may fail
6. **Set reasonable timeouts**: Prevent hanging operations
7. **Monitor costs**: Track LLM token usage and costs
8. **Use AutoAgent for quick prototypes**: Zero-config
9. **Use CustomAgent for production**: Full control
10. **Enable remote sandbox in production**: Better isolation

---

## Testing Utilities (v0.3.2)

### MockMesh

Simplified mesh for unit testing without real P2P infrastructure.

#### Class: `MockMesh`

```python
from jarviscore.testing import MockMesh

mesh = MockMesh(mode="p2p")
mesh.add(MyAgent)
await mesh.start()

agent = mesh.get_agent("my_role")
# Test agent behavior...

await mesh.stop()
```

**Methods:**

#### `add(agent_class_or_instance, agent_id=None) -> Agent`

Register an agent with the mock mesh.

```python
mesh.add(MyAgent)  # Add class
mesh.add(my_instance)  # Add instance
```

---

#### `async start()`

Start the mock mesh. Runs agent setup and injects MockPeerClient into each agent.

---

#### `async stop()`

Stop the mock mesh and run agent teardown.

---

#### `get_agent(role) -> Optional[Agent]`

Get agent by role.

```python
agent = mesh.get_agent("analyst")
```

---

#### `get_diagnostics() -> dict`

Get mock diagnostics (compatible structure with real Mesh).

```python
diag = mesh.get_diagnostics()
assert diag["connectivity_status"] == "mock"
```

---

### MockPeerClient

Full mock replacement for PeerClient with test configuration and assertions.

#### Class: `MockPeerClient`

```python
from jarviscore.testing import MockPeerClient

client = MockPeerClient(
    agent_id="test-agent",
    agent_role="tester",
    mock_peers=[
        {"role": "analyst", "capabilities": ["analysis"]},
        {"role": "scout", "capabilities": ["research"]}
    ],
    auto_respond=True
)
```

**Parameters:**
- `agent_id` (str): ID for the mock agent
- `agent_role` (str): Role for the mock agent
- `mock_peers` (list): List of peer definitions with role, capabilities
- `auto_respond` (bool): Auto-respond to requests with mock data (default: True)

---

#### Configuration Methods

#### `set_mock_response(target, response)`

Configure response for a specific target.

```python
client.set_mock_response("analyst", {"result": "analysis complete", "score": 95})
response = await client.request("analyst", {"query": "test"})
assert response["score"] == 95
```

---

#### `set_default_response(response)`

Set default response for unconfigured targets.

```python
client.set_default_response({"status": "success", "mock": True})
```

---

#### `set_request_handler(handler)`

Set custom async handler for dynamic responses.

```python
async def custom_handler(target, message, context):
    return {"echo": message.get("query"), "target": target}

client.set_request_handler(custom_handler)
```

---

#### `add_mock_peer(role, capabilities=None, **kwargs)`

Add a mock peer dynamically.

```python
client.add_mock_peer("reporter", capabilities=["reporting", "formatting"])
```

---

#### `inject_message(sender, message_type, data, correlation_id=None, context=None)`

Inject a message into the receive queue for testing message handlers.

```python
from jarviscore.p2p.messages import MessageType

client.inject_message(
    sender="external_agent",
    message_type=MessageType.NOTIFY,
    data={"event": "test_event", "value": 42},
    context={"mission_id": "m-123"}
)

msg = await client.receive(timeout=1)
assert msg.data["value"] == 42
```

---

#### Assertion Helpers

#### `assert_notified(target, message_contains=None)`

Assert a notification was sent to target.

```python
await client.notify("analyst", {"event": "done"})
client.assert_notified("analyst")
client.assert_notified("analyst", message_contains={"event": "done"})
```

---

#### `assert_requested(target, message_contains=None)`

Assert a request was sent to target.

```python
await client.request("analyst", {"query": "test"})
client.assert_requested("analyst")
```

---

#### `assert_broadcasted(message_contains=None)`

Assert a broadcast was sent.

```python
await client.broadcast({"alert": "important"})
client.assert_broadcasted()
client.assert_broadcasted(message_contains={"alert": "important"})
```

---

#### Tracking Methods

#### `get_sent_notifications() -> List[dict]`

Get all notifications sent during test.

---

#### `get_sent_requests() -> List[dict]`

Get all requests sent during test.

---

#### `get_sent_broadcasts() -> List[dict]`

Get all broadcasts sent during test.

---

#### `reset()`

Clear all tracking state (notifications, requests, broadcasts, mock responses).

```python
client.reset()
assert len(client.get_sent_notifications()) == 0
```

---

### Testing Pattern Example

```python
import pytest
from jarviscore.testing import MockMesh
from jarviscore.profiles import CustomAgent

class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        # Ask analyst for help
        analysis = await self.peers.request("analyst", {"data": msg.data})
        return {"processed": True, "analysis": analysis}

@pytest.mark.asyncio
async def test_processor_delegates_to_analyst():
    mesh = MockMesh()
    mesh.add(MyAgent)
    await mesh.start()

    processor = mesh.get_agent("processor")

    # Configure mock response
    processor.peers.set_mock_response("analyst", {"result": "analyzed"})

    # Test the flow
    response = await processor.peers.request("analyst", {"test": "data"})

    # Verify
    assert response["result"] == "analyzed"
    processor.peers.assert_requested("analyst")

    await mesh.stop()
```

---

## Version

API Reference for JarvisCore v1.0.2

Last Updated: 2026-03-04
