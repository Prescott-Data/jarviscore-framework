# JarvisCore API Reference

Complete API documentation for JarvisCore framework components.

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
   - [ListenerAgent (v0.3.0)](#listeneragent-v030)
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
6. [Utilities](#utilities)
   - [InternetSearch](#internetsearch)
   - [UnifiedLLMClient](#unifiedllmclient)

---

## Core Components

### Mesh

The central orchestrator for managing agents and workflows.

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

Zero-config autonomous agent with LLM-powered code generation.

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

Flexible agent profile for integrating external frameworks.

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

### ListenerAgent (v0.3.0)

Handler-based agent for P2P communication without manual run loops.

#### Class: `ListenerAgent(CustomAgent)`

```python
from jarviscore.profiles import ListenerAgent

class MyAgent(ListenerAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        """Handle incoming requests from peers."""
        return {"result": msg.data.get("task", "").upper()}

    async def on_peer_notify(self, msg):
        """Handle broadcast notifications."""
        print(f"Notification: {msg.data}")
```

**Class Attributes:**
- `role` (str): Agent role identifier (required)
- `capabilities` (list): List of capability strings (required)

**Handler Methods:**

#### `async on_peer_request(msg) -> dict`

Handle incoming request messages. Return value is sent back to requester.

```python
async def on_peer_request(self, msg):
    query = msg.data.get("question", "")
    result = self.process(query)
    return {"response": result, "status": "success"}
```

**Parameters:**
- `msg` (IncomingMessage): Incoming message with `data`, `sender_role`, `sender_id`

**Returns:** dict - Response sent back to requester

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

**Self-Registration Methods (v0.3.0):**

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

#### `async serve_forever()`

Run the agent until shutdown signal.

```python
await agent.serve_forever()
```

---

## P2P Communication (v0.3.0)

### PeerClient

Client for peer-to-peer communication, available as `self.peers` on agents.

#### Class: `PeerClient`

**Methods:**

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
- `data` (dict): Message payload
- `sender_role` (str): Role of sending agent
- `sender_id` (str): ID of sending agent
- `is_request` (bool): True if this is a request expecting response
- `is_notify` (bool): True if this is a notification

```python
async def on_peer_request(self, msg):
    print(f"From: {msg.sender_role}")
    print(f"Data: {msg.data}")
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
- `agent`: Agent instance (ListenerAgent or CustomAgent)
- `mode` (str): "p2p" or "distributed"
- `bind_port` (int, optional): P2P port (default: 7950)
- `seed_nodes` (str, optional): Comma-separated seed node addresses

**Example:**

```python
from fastapi import FastAPI
from jarviscore.profiles import ListenerAgent
from jarviscore.integrations.fastapi import JarvisLifespan


class ProcessorAgent(ListenerAgent):
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
- Background run loop (for ListenerAgent)
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

Safe code execution with resource limits and remote execution support.

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

## Version

API Reference for JarvisCore v0.3.0

Last Updated: 2026-01-29
