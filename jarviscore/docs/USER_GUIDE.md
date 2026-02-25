# JarvisCore User Guide

Practical guide to building agent systems with JarvisCore.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Basic Concepts](#basic-concepts)
3. [AutoAgent Tutorial](#autoagent-tutorial)
4. [Custom Profile Tutorial](#custom-profile-tutorial)
5. [CustomAgent Tutorial](#customagent-tutorial)
6. [Multi-Agent Workflows](#multi-agent-workflows)
7. [Infrastructure & Memory (v0.4.0)](#infrastructure--memory) — blob, mailbox, memory, auth, telemetry
8. [Internet Search](#internet-search)
9. [Remote Sandbox](#remote-sandbox)
10. [Result Storage](#result-storage)
11. [Code Registry](#code-registry)
12. [FastAPI Integration (v0.3.0)](#fastapi-integration-v030)
13. [Cloud Deployment (v0.3.0)](#cloud-deployment-v030)
14. [Cognitive Discovery (v0.3.0)](#cognitive-discovery-v030)
15. [Session Context (v0.3.2)](#session-context-v032)
16. [Async Requests (v0.3.2)](#async-requests-v032)
17. [Load Balancing (v0.3.2)](#load-balancing-v032)
18. [Mesh Diagnostics (v0.3.2)](#mesh-diagnostics-v032)
19. [Testing with MockMesh (v0.3.2)](#testing-with-mockmesh-v032)
20. [Best Practices](#best-practices)
21. [Common Patterns](#common-patterns)
22. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Step 1: Installation (1 minute)

```bash
pip install jarviscore-framework
```

### Step 2: Configuration (2 minutes)

JarvisCore needs an LLM provider to generate code for AutoAgent. Initialize your project:

```bash
# Initialize project (creates .env.example and examples)
python -m jarviscore.cli.scaffold --examples

# Copy and configure your environment
cp .env.example .env
```

Edit `.env` and add **one** of these API keys:

```bash
# Option 1: Claude (Recommended)
CLAUDE_API_KEY=sk-ant-your-key-here

# Option 2: Azure OpenAI
AZURE_API_KEY=your-key-here
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o

# Option 3: Google Gemini
GEMINI_API_KEY=your-key-here

# Option 4: Local vLLM
LLM_ENDPOINT=http://localhost:8000
```

### Step 3: Validate Setup (30 seconds)

Run the health check to ensure everything works:

```bash
# Basic check
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm
```

Run the smoke test to validate end-to-end:

```bash
python -m jarviscore.cli.smoketest
```

### Step 4: Your First Agent (30 seconds)

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculation"]
    system_prompt = "You are a math expert. Store results in 'result' variable."

async def main():
    mesh = Mesh(mode="autonomous")
    mesh.add(CalculatorAgent)
    await mesh.start()

    results = await mesh.workflow("calc", [
        {"agent": "calculator", "task": "Calculate the factorial of 10"}
    ])

    print(results[0]['output'])  # 3628800
    await mesh.stop()

asyncio.run(main())
```

**That's it!** Three steps:
1. Define agent class
2. Add to mesh
3. Run workflow

---

## Basic Concepts

### The Mesh

The **Mesh** is the runtime that wires everything together. You create one Mesh per process, configure its mode, register agent classes with `mesh.add()`, then call `await mesh.start()` to initialise them. The Mesh routes each workflow step to the right agent, injects infrastructure (Redis store, blob storage, mailbox) before `setup()` runs, and manages the full agent lifecycle — from startup through teardown.

```python
# Autonomous mode (single machine, workflow engine only)
mesh = Mesh(mode="autonomous")

# P2P mode (agent-to-agent communication via SWIM/ZMQ)
mesh = Mesh(mode="p2p", config={'bind_port': 7950})

# Distributed mode (both workflow engine AND P2P networking)
mesh = Mesh(mode="distributed", config={'bind_port': 7950})
```

**Mode Selection:**
| Mode | Use Case | Components |
|------|----------|------------|
| `autonomous` | Single machine, simple pipelines | Workflow Engine |
| `p2p` | Agent swarms, real-time coordination | P2P Coordinator |
| `distributed` | Multi-node production systems | Both |

### Agents

**Agents** are workers that execute tasks. Each agent has a `role` (a unique string identifier), a list of `capabilities`, and belongs to a Profile that determines how it runs.

A **Profile** is the execution contract an agent fulfills. You subclass a Profile, set its class attributes, and pass the class to `mesh.add()` — the Mesh instantiates and manages it. JarvisCore offers two profiles:

| Profile | Best For | How It Works |
|---------|----------|--------------|
| **AutoAgent** | Rapid prototyping | LLM generates + executes code from prompts |
| **CustomAgent** | Your own code | Implement `on_peer_request()` for P2P or `execute_task()` for workflows |

See [AutoAgent Guide](AUTOAGENT_GUIDE.md) and [CustomAgent Guide](CUSTOMAGENT_GUIDE.md) for details.

### Workflows

A **Workflow** is a list of steps — each step names an agent by role or capability, plus a task description. Steps that declare `depends_on` wait for those dependencies to complete before starting; independent steps run in parallel. Each completed step's output is forwarded automatically to dependent steps via `task['context']['previous_step_results']`, so agents can build on each other's work without manual wiring.

```python
await mesh.workflow("pipeline-id", [
    {"agent": "scraper", "task": "Scrape data"},
    {"agent": "processor", "task": "Clean data", "depends_on": [0]},
    {"agent": "storage", "task": "Save data", "depends_on": [1]}
])
```

---

## AutoAgent Tutorial

AutoAgent handles the "prompt → code → result" workflow automatically. See [AutoAgent Guide](AUTOAGENT_GUIDE.md) for distributed mode.

### Example 1: Simple Calculator

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculation"]
    system_prompt = "You are a mathematical calculation expert. Store results in 'result'."

async def calculator_demo():
    mesh = Mesh(mode="autonomous")
    mesh.add(CalculatorAgent)
    await mesh.start()

    result = await mesh.workflow("calc", [
        {"agent": "calculator", "task": "Calculate 15!"}
    ])

    print(f"15! = {result[0]['output']}")
    await mesh.stop()

asyncio.run(calculator_demo())
```

### Example 2: Data Analyst

```python
class AnalystAgent(AutoAgent):
    role = "analyst"
    capabilities = ["data_analysis", "statistics"]
    system_prompt = "You are a data analyst expert. Store results in 'result'."

async def data_analyst_demo():
    mesh = Mesh(mode="autonomous")
    mesh.add(AnalystAgent)
    await mesh.start()

    result = await mesh.workflow("analysis", [{
        "agent": "analyst",
        "task": """
        Given this data: [23, 45, 12, 67, 89, 34, 56, 78, 90, 11]
        Calculate: mean, median, mode, standard deviation, and min/max
        """
    }])

    print(result[0]['output'])
    await mesh.stop()

asyncio.run(data_analyst_demo())
```

---

## Custom Profile Tutorial

Use **CustomAgent** profile.

See [CustomAgent Guide](CUSTOMAGENT_GUIDE.md) for:
- Converting standalone agents to JarvisCore
- P2P mode for agent-to-agent communication
- Distributed mode for multi-node systems

---

## CustomAgent Tutorial

CustomAgent gives you full control over execution logic. See [CustomAgent Guide](CUSTOMAGENT_GUIDE.md) for P2P and distributed modes.

### Quick Example

```python
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent

class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["data_processing"]

    async def setup(self):
        """Initialize resources (DB connections, API clients, etc.)."""
        await super().setup()
        self.data = []

    async def execute_task(self, task):
        """Called by workflow engine for each task."""
        task_desc = task.get("task", "")
        context = task.get("context", {})  # From depends_on steps

        # Your logic here
        result = {"processed": task_desc.upper()}

        return {
            "status": "success",
            "output": result,
            "agent_id": self.agent_id
        }

async def main():
    mesh = Mesh(mode="autonomous")
    mesh.add(MyAgent)
    await mesh.start()

    results = await mesh.workflow("demo", [
        {"agent": "processor", "task": "hello world"}
    ])

    print(results[0]["output"])  # {"processed": "HELLO WORLD"}
    await mesh.stop()
```

### Key Methods

| Method | Purpose | Mode |
|--------|---------|------|
| `setup()` | Initialize resources | All |
| `execute_task(task)` | Handle workflow steps | Autonomous/Distributed |
| `run()` | Continuous loop | P2P |
| `teardown()` | Cleanup resources | All |

---

## Multi-Agent Workflows

### Example: Data Pipeline

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class ScraperAgent(AutoAgent):
    role = "scraper"
    capabilities = ["web_scraping", "data_collection"]
    system_prompt = "You are a web scraping expert. Store results in 'result'."

class ProcessorAgent(AutoAgent):
    role = "processor"
    capabilities = ["data_processing", "cleaning"]
    system_prompt = "You are a data cleaning expert. Store results in 'result'."

class AnalyzerAgent(AutoAgent):
    role = "analyzer"
    capabilities = ["analysis", "statistics"]
    system_prompt = "You are a data analysis expert. Store results in 'result'."

async def data_pipeline():
    mesh = Mesh(mode="autonomous")
    mesh.add(ScraperAgent)
    mesh.add(ProcessorAgent)
    mesh.add(AnalyzerAgent)
    await mesh.start()

    results = await mesh.workflow("pipeline", [
        {
            "id": "scrape",
            "agent": "scraper",
            "task": "Generate sample e-commerce data (10 products with prices)"
        },
        {
            "id": "clean",
            "agent": "processor",
            "task": "Clean and normalize the product data",
            "depends_on": ["scrape"]
        },
        {
            "id": "analyze",
            "agent": "analyzer",
            "task": "Calculate price statistics (mean, median, range)",
            "depends_on": ["clean"]
        }
    ])

    print("Scrape:", results[0]['output'])
    print("Clean:", results[1]['output'])
    print("Analysis:", results[2]['output'])
    await mesh.stop()

asyncio.run(data_pipeline())
```

---

## Infrastructure & Memory

JarvisCore v1.0.0 ships a full production infrastructure stack. All features degrade
gracefully when not configured.

### Auto-Injection Quick Reference

Before every agent's `setup()`, the Mesh injects:

| Attribute | What it is | Requires |
|-----------|-----------|---------|
| `self._redis_store` | `RedisContextStore` — step outputs, workflow graph, mailbox, checkpoints | `REDIS_URL` |
| `self._blob_storage` | `LocalBlobStorage` \| `AzureBlobStorage` — artifact I/O | always present |
| `self.mailbox` | `MailboxManager` — async inter-agent messaging via Redis Streams | `REDIS_URL` |

```python
class MyAgent(CustomAgent):
    async def setup(self):
        await super().setup()
        # All injected — use directly, no constructor wiring
        print(self._redis_store, self._blob_storage, self.mailbox)
```

---

### Blob Storage

Save and load any artifact — string, bytes, or JSON:

```bash
STORAGE_BACKEND=local          # default: ./blob_storage/
STORAGE_BASE_PATH=./blob_storage
# or: STORAGE_BACKEND=azure with AZURE_STORAGE_CONNECTION_STRING
```

```python
# Save
await self._blob_storage.save("reports/daily-001.md", markdown_text)
await self._blob_storage.save("data/result.json", json.dumps(data))

# Load
content = await self._blob_storage.load("reports/daily-001.md")
data = json.loads(content) if content else {}
```

Path convention: `{type}/{workflow_id}/{filename}.{ext}`

---

### Mailbox Messaging

Fire-and-forget inter-agent messages via Redis Streams. Messages survive process restarts.

```python
# Send (fire-and-forget)
self.mailbox.send(other_agent_id, {"event": "done", "workflow": "wf-001"})

# Drain inbox
messages = self.mailbox.read(max_messages=10)
for msg in messages:
    print(msg["event"])
```

---

### Prometheus Telemetry

Prometheus support is **optional**. If `prometheus-client` is not installed, all metric
calls are silent no-ops — nothing fails and no configuration is required. Install it
only when you want to scrape metrics:

```bash
pip install "jarviscore[prometheus]"
```

Enable and configure via `.env`:

```bash
PROMETHEUS_ENABLED=true   # default: false
PROMETHEUS_PORT=9090      # default: 9090
```

When `PROMETHEUS_ENABLED=true`, the Mesh automatically starts an HTTP metrics server
on the configured port at `mesh.start()`. No code changes are needed — all built-in
metrics are collected automatically.

#### Metrics exposed

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `jarviscore_llm_tokens_input_total` | Counter | `provider`, `model` | Total input tokens consumed |
| `jarviscore_llm_tokens_output_total` | Counter | `provider`, `model` | Total output tokens generated |
| `jarviscore_llm_cost_dollars_total` | Counter | `provider`, `model` | Total LLM cost in USD |
| `jarviscore_llm_request_duration_seconds` | Histogram | `provider`, `model` | LLM API call duration |
| `jarviscore_llm_requests_total` | Counter | `provider`, `model`, `status` | Total LLM requests (success/error) |
| `jarviscore_workflow_steps_total` | Counter | `status` | Steps completed, labelled by outcome |
| `jarviscore_step_execution_duration_seconds` | Histogram | `status` | Per-step execution time |
| `jarviscore_active_workflows` | Gauge | — | Workflows currently running |
| `jarviscore_active_steps` | Gauge | — | Steps currently executing |
| `jarviscore_events_emitted_total` | Counter | `event_type` | Trace events emitted |

LLM metrics (`tokens`, `cost`, `duration`) are recorded automatically by the AutoAgent
code-generation pipeline. Workflow metrics (`steps_total`, `active_workflows`) are
recorded automatically by the WorkflowEngine.

#### Recording step metrics in CustomAgent

AutoAgent records step metrics automatically. For CustomAgent, call
`record_step_execution` manually:

```python
import time
from jarviscore.telemetry.metrics import record_step_execution

class MyAgent(CustomAgent):
    async def execute_task(self, task):
        start = time.time()
        result = self._do_work(task)
        record_step_execution(time.time() - start, "completed")
        return {"status": "success", "output": result}
```

#### Viewing metrics

```bash
# Raw metrics endpoint
curl -s http://localhost:9090/metrics | grep jarviscore

# Check active workflows during a run
curl -s http://localhost:9090/metrics | grep active_workflows

# Token usage by provider
curl -s http://localhost:9090/metrics | grep llm_tokens
```

Metrics are in the standard Prometheus text format and can be scraped by any
Prometheus-compatible system (Prometheus server, Grafana, Datadog Agent, etc.).

---

### Distributed WorkflowEngine

```python
mesh = Mesh(mode="distributed", config={"redis_url": "redis://localhost:6379/0"})
results = await mesh.workflow("wf-001", [
    {"id": "fetch",   "agent": "fetcher",  "task": "Fetch data"},
    {"id": "analyse", "agent": "analyst",  "task": "Analyse", "depends_on": ["fetch"]},
])
```

- DAG persisted to Redis hash `workflow_graph:{wf_id}` — crash recovery on restart
- Distributed nodes autonomously claim matching steps via atomic SETNX
- `_wait_remote_step()` polls Redis every 2s until a remote step is `"completed"`

---

### Auth Injection (Nexus OSS)

```bash
NEXUS_GATEWAY_URL=https://your-dromos-gateway.example.com
AUTH_MODE=production    # or "mock" for local dev
```

```python
class SecureAgent(CustomAgent):
    requires_auth = True   # → self._auth_manager injected before setup()

    async def execute_task(self, task):
        if self._auth_manager:
            result = await self._auth_manager.make_authenticated_request(
                provider="github", method="GET",
                url="https://api.github.com/user",
            )
```

Full Nexus OSS flow: `request_connection → browser OAuth → poll ACTIVE → resolve_strategy → apply header`.
`_auth_manager` is `None` when `NEXUS_GATEWAY_URL` is not set (graceful degradation).

---

### UnifiedMemory

```python
from jarviscore.memory import UnifiedMemory, RedisMemoryAccessor

# In setup()
self.memory = UnifiedMemory(
    workflow_id="wf-001", step_id="analyst", agent_id=self.role,
    redis_store=self._redis_store, blob_storage=self._blob_storage,
)

# EpisodicLedger
await self.memory.episodic.append({"event": "started", "ts": time.time()})
recent = await self.memory.episodic.tail(5)

# LongTermMemory
await self.memory.ltm.save_summary("Key findings: ...")
summary = await self.memory.ltm.load_summary()

# Cross-step accessor — read prior step output without explicit passing
accessor = RedisMemoryAccessor(self._redis_store, workflow_id="wf-001")
raw = accessor.get("fetch")
data = raw.get("output", raw) if isinstance(raw, dict) else {}
```

---

### Production Examples

All examples require Redis: `docker compose -f docker-compose.infra.yml up -d`

| Example | Mode | Profile |
|---------|------|---------|
| Ex1 — Financial Pipeline | autonomous | AutoAgent |
| Ex2 — Research Network (4 nodes) | distributed | AutoAgent |
| Ex3 — Support Swarm | p2p | CustomAgent |
| Ex4 — Content Pipeline | distributed | CustomAgent |

```bash
python examples/ex1_financial_pipeline.py
python examples/ex2_synthesizer.py &  # then start nodes 1-3
python examples/ex3_support_swarm.py
python examples/ex4_content_pipeline.py
```

Full walkthroughs: [AUTOAGENT_GUIDE.md](AUTOAGENT_GUIDE.md) • [CUSTOMAGENT_GUIDE.md](CUSTOMAGENT_GUIDE.md)

---

## Internet Search

Enable web search for research tasks:

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class ResearcherAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "web_search"]
    system_prompt = "You are an expert researcher. Store results in 'result'."
    enable_search = True  # ← Enable internet search

async def search_demo():
    mesh = Mesh(mode="autonomous")
    mesh.add(ResearcherAgent)
    await mesh.start()

    result = await mesh.workflow("search", [{
        "agent": "researcher",
        "task": "Search for 'Python asyncio best practices' and summarize top 3 results"
    }])

    print(result[0]['output'])
    await mesh.stop()

asyncio.run(search_demo())
```

**Search Capabilities:**
- DuckDuckGo web search
- Content extraction from URLs
- Automatic summarization
- No API keys required

---

## Remote Sandbox

Use remote code execution for better security:

### Enable Remote Sandbox

```bash
# .env file
SANDBOX_MODE=remote
SANDBOX_SERVICE_URL=https://browser-task-executor.bravesea-3f5f7e75.eastus.azurecontainerapps.io
```

### Test Remote Execution

```python
from jarviscore.execution import create_sandbox_executor

async def test_remote():
    executor = create_sandbox_executor(
        timeout=30,
        config={
            'sandbox_mode': 'remote',
            'sandbox_service_url': 'https://...'
        }
    )

    code = "result = 2 + 2"
    result = await executor.execute(code)

    print(f"Mode: {result['mode']}")  # "remote"
    print(f"Output: {result['output']}")  # 4
    print(f"Time: {result['execution_time']}s")

asyncio.run(test_remote())
```

**Benefits:**
- Full process isolation
- Better security
- Azure Container Apps hosting
- Automatic fallback to local

**When to use:**
- Production deployments
- Untrusted code execution
- Multi-tenant systems
- High security requirements

---

## Result Storage

All execution results are automatically stored:

### Access Result Storage

```python
from jarviscore.execution import create_result_handler

handler = create_result_handler()

# Get specific result
result = handler.get_result("calculator-abc123_2026-01-12T12-00-00_123456")

# Get agent's recent results
recent = handler.get_agent_results("calculator-abc123", limit=10)

for r in recent:
    print(f"{r['task']}: {r['output']}")
```

### Storage Location

```
logs/
├── calculator-abc123/
│   ├── calculator-abc123_2026-01-12T12-00-00_123456.json
│   └── calculator-abc123_2026-01-12T12-05-30_789012.json
├── analyzer-def456/
│   └── analyzer-def456_2026-01-12T12-10-00_345678.json
└── code_registry/
    ├── index.json
    └── functions/
        ├── calculator-abc123_3a5b2f76.py
        └── analyzer-def456_8b2c4d91.py
```

**What's Stored:**
- Task description
- Generated code
- Execution output
- Status (success/failure)
- Execution time
- Token usage
- Cost (if tracked)
- Repair attempts
- Timestamp

---

## Code Registry

Reuse successful code across agents:

### Search Registry

```python
from jarviscore.execution import create_code_registry

registry = create_code_registry()

# Search for math functions
matches = registry.search(
    query="factorial calculation",
    capabilities=["math"],
    limit=3
)

for match in matches:
    print(f"Function: {match['function_id']}")
    print(f"Task: {match['task']}")
    print(f"Output sample: {match['output_sample']}")
```

### Get Function Code

```python
# Get specific function
func = registry.get("calculator-abc123_3a5b2f76")

print("Code:")
print(func['code'])

print("\nMetadata:")
print(f"Agent: {func['agent_id']}")
print(f"Capabilities: {func['capabilities']}")
print(f"Registered: {func['registered_at']}")
```

**Use Cases:**
- Share functions between agents
- Build function library
- Audit generated code
- Performance analysis

---

## FastAPI Integration (v0.3.0)

Deploy agents as FastAPI services with minimal boilerplate:

### JarvisLifespan

```python
from fastapi import FastAPI, Request
from jarviscore.profiles import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan

class ProcessorAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": msg.data.get("task", "").upper()}

# 3 lines to integrate
agent = ProcessorAgent()
app = FastAPI(lifespan=JarvisLifespan(agent, mode="p2p", bind_port=7950))

@app.get("/peers")
async def list_peers(request: Request):
    agent = request.app.state.jarvis_agents["processor"]
    return {"peers": agent.peers.list_peers()}
```

**What JarvisLifespan handles:**
- Mesh startup/shutdown
- Background task management for agent run() loops
- Graceful shutdown with timeouts
- State injection into FastAPI app

---

## Cloud Deployment (v0.3.0)

Deploy agents to containers without a central orchestrator:

### Self-Registration Pattern

```python
# In your container entrypoint
import asyncio
from jarviscore.profiles import CustomAgent

class MyAgent(CustomAgent):
    role = "worker"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"processed": msg.data}

async def main():
    agent = MyAgent()

    # Join existing mesh (uses JARVISCORE_SEED_NODES env var)
    await agent.join_mesh()

    print(f"Joined as {agent.role}, discovered: {agent.peers.list_peers()}")

    # Run until shutdown, auto-leaves mesh on exit
    await agent.run_standalone()

asyncio.run(main())
```

### Docker/Kubernetes

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install jarviscore-framework

# Point to existing mesh
ENV JARVISCORE_SEED_NODES=mesh-service:7946

CMD ["python", "-m", "myapp.agent"]
```

**Environment Variables:**
- `JARVISCORE_SEED_NODES` - Comma-separated list of seed nodes
- `JARVISCORE_MESH_ENDPOINT` - Single endpoint to join

---

## Cognitive Discovery (v0.3.0)

Let LLMs dynamically discover mesh peers instead of hardcoding agent names:

### The Problem

```python
# Before: Hardcoded peer names in prompts
system_prompt = """
You can delegate to:
- analyst for data analysis
- scout for research
"""
# Breaks when mesh composition changes!
```

### The Solution

```python
# After: Dynamic discovery
system_prompt = self.peers.build_system_prompt(
    "You are a coordinator agent."
)
# Automatically includes all available peers!
```

### get_cognitive_context()

```python
# Get prompt-ready peer descriptions
context = self.peers.get_cognitive_context(format="markdown")
```

**Output:**
```markdown
## AVAILABLE MESH PEERS

You are part of a multi-agent mesh. The following peers are available:

- **analyst** (`agent-analyst-abc123`)
  - Capabilities: analysis, charting, reporting
  - Description: Analyzes data and generates insights

- **scout** (`agent-scout-def456`)
  - Capabilities: research, reconnaissance
  - Description: Gathers information

Use the `ask_peer` tool to delegate tasks to these specialists.
```

**Formats:** `markdown`, `json`, `text`

---

## Session Context (v0.3.2)

Pass metadata through your message flows for tracing, priority, and session tracking:

### Basic Usage

```python
# Send request with context
response = await self.peers.request(
    "analyst",
    {"query": "analyze sales data"},
    context={"mission_id": "m-123", "priority": "high", "user_id": "u-456"}
)

# Context is available in the handler
async def on_peer_request(self, msg):
    mission_id = msg.context.get("mission_id")  # "m-123"
    print(f"Processing request for mission: {mission_id}")
    return {"result": "analysis complete"}
```

### Auto-Propagation

When you `respond()`, context automatically propagates from the request:

```python
async def on_peer_request(self, msg):
    # msg.context = {"mission_id": "m-123", ...}
    result = process(msg.data)

    # Context auto-propagates - no need to pass it!
    await self.peers.respond(msg, {"result": result})

    # Or override with custom context
    await self.peers.respond(msg, {"result": result},
                            context={"status": "completed"})
```

### All Methods Support Context

```python
# notify
await self.peers.notify("logger", {"event": "started"}, context={"trace_id": "t-1"})

# request
response = await self.peers.request("worker", {"task": "..."}, context={"priority": "low"})

# broadcast
await self.peers.broadcast({"alert": "system ready"}, context={"source": "coordinator"})

# ask_async
req_id = await self.peers.ask_async("analyst", {"q": "..."}, context={"batch_id": "b-1"})
```

---

## Async Requests (v0.3.2)

Fire-and-collect pattern for parallel requests without blocking:

### Basic Pattern

```python
# Fire off multiple requests (non-blocking)
request_ids = []
for analyst in self.peers.discover(role="analyst"):
    req_id = await self.peers.ask_async(analyst.agent_id, {"task": "analyze"})
    request_ids.append(req_id)

# Do other work while analysts process...
await self.do_other_work()

# Collect responses
results = []
for req_id in request_ids:
    response = await self.peers.check_inbox(req_id, timeout=10)
    if response:
        results.append(response)
```

### API Reference

```python
# Send async request - returns immediately
req_id = await self.peers.ask_async(target, message, timeout=120, context=None)

# Check for response (non-blocking if timeout=0)
response = await self.peers.check_inbox(req_id, timeout=0)

# Check with wait
response = await self.peers.check_inbox(req_id, timeout=5)

# List pending requests
pending = self.peers.get_pending_async_requests()
# [{"request_id": "...", "target": "analyst", "sent_at": 1234567890.0}]

# Clear inbox
self.peers.clear_inbox(req_id)  # Specific
self.peers.clear_inbox()        # All
```

---

## Load Balancing (v0.3.2)

Distribute requests across multiple peers with discovery strategies:

### Strategies

```python
# Default: first in discovery order
peers = self.peers.discover(role="worker", strategy="first")

# Random: shuffle for basic load distribution
peers = self.peers.discover(role="worker", strategy="random")

# Round-robin: rotate through peers on each call
peers = self.peers.discover(role="worker", strategy="round_robin")

# Least-recent: prefer peers not used recently
peers = self.peers.discover(role="worker", strategy="least_recent")
```

### Convenience Method

```python
# Get single peer with strategy
worker = self.peers.discover_one(role="worker", strategy="round_robin")
if worker:
    await self.peers.request(worker.agent_id, {"task": "..."})
```

### Track Usage for least_recent

```python
peer = self.peers.discover_one(role="worker", strategy="least_recent")
response = await self.peers.request(peer.agent_id, {"task": "..."})

# Update usage timestamp after successful communication
self.peers.record_peer_usage(peer.agent_id)
```

### Example: Round-Robin Work Distribution

```python
async def distribute_tasks(self, tasks):
    results = []
    for task in tasks:
        # Each call rotates to next worker
        worker = self.peers.discover_one(role="worker", strategy="round_robin")
        if worker:
            response = await self.peers.request(worker.agent_id, {"task": task})
            results.append(response)
    return results
```

---

## Mesh Diagnostics (v0.3.2)

Monitor mesh health and debug connectivity issues:

### Get Diagnostics

```python
diag = mesh.get_diagnostics()

print(f"Mode: {diag['local_node']['mode']}")
print(f"Status: {diag['connectivity_status']}")
print(f"Agents: {diag['local_node']['agent_count']}")

for agent in diag['local_agents']:
    print(f"  - {agent['role']}: {agent['capabilities']}")

for peer in diag['known_peers']:
    print(f"  - {peer['role']} @ {peer['node_id']}: {peer['status']}")
```

### Connectivity Status Values

| Status | Meaning |
|--------|---------|
| `healthy` | P2P active with connected peers |
| `isolated` | P2P active but no peers found |
| `degraded` | Some connectivity issues |
| `not_started` | Mesh not yet started |
| `local_only` | Autonomous mode (no P2P) |

### FastAPI Health Endpoint

```python
@app.get("/health")
async def health(request: Request):
    mesh = request.app.state.jarvis_mesh
    diag = mesh.get_diagnostics()
    return {
        "status": diag["connectivity_status"],
        "agents": diag["local_node"]["agent_count"],
        "peers": len(diag["known_peers"])
    }
```

---

## Testing with MockMesh (v0.3.2)

Unit test your agents without real P2P infrastructure:

### Basic Setup

```python
import pytest
from jarviscore.testing import MockMesh
from jarviscore.profiles import CustomAgent

class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        # Delegate to analyst
        analysis = await self.peers.request("analyst", {"data": msg.data})
        return {"processed": True, "analysis": analysis}

@pytest.mark.asyncio
async def test_processor_delegates():
    mesh = MockMesh()
    mesh.add(MyAgent)
    await mesh.start()

    agent = mesh.get_agent("processor")

    # Configure mock response for analyst
    agent.peers.set_mock_response("analyst", {"result": "analyzed"})

    # Test the agent
    response = await agent.peers.request("analyst", {"test": "data"})

    # Verify
    assert response["result"] == "analyzed"
    agent.peers.assert_requested("analyst")

    await mesh.stop()
```

### MockPeerClient Features

```python
# Configure responses
agent.peers.set_mock_response("analyst", {"result": "..."})
agent.peers.set_default_response({"status": "ok"})

# Custom handler for dynamic responses
async def handler(target, message, context):
    return {"echo": message, "target": target}
agent.peers.set_request_handler(handler)

# Inject messages for handler testing
from jarviscore.p2p.messages import MessageType
agent.peers.inject_message("sender", MessageType.REQUEST, {"data": "test"})

# Assertions
agent.peers.assert_notified("target")
agent.peers.assert_requested("analyst", message_contains={"query": "test"})
agent.peers.assert_broadcasted()

# Track what was sent
notifications = agent.peers.get_sent_notifications()
requests = agent.peers.get_sent_requests()

# Reset between tests
agent.peers.reset()
```

---

## Best Practices

### 1. Always Use Context Managers

```python
# Good
async with Mesh() as mesh:
    mesh.add_agent(AutoAgent, ...)
    await mesh.start()
    results = await mesh.run_workflow([...])
    # Automatic cleanup

# Manual (also works)
mesh = Mesh()
try:
    await mesh.start()
    results = await mesh.run_workflow([...])
finally:
    await mesh.stop()
```

### 2. Handle Errors Gracefully

```python
try:
    results = await mesh.run_workflow([...])

    for i, result in enumerate(results):
        if result['status'] == 'failure':
            print(f"Step {i} failed: {result['error']}")
        else:
            print(f"Step {i} succeeded: {result['output']}")

except TimeoutError:
    print("Workflow timed out")
except RuntimeError as e:
    print(f"Runtime error: {e}")
```

### 3. Use Clear System Prompts

```python
# Good
system_prompt = """
You are a financial data analyst expert.
Your task is to analyze stock data and provide insights.
Always return results as structured JSON.
"""

# Bad
system_prompt = "You are helpful"
```

### 4. Set Appropriate Timeouts

```python
# Short tasks
mesh.add_agent(AutoAgent, ..., max_repair_attempts=1)

# Long-running tasks
config = {'execution_timeout': 600}  # 10 minutes
mesh = Mesh(config=config)
```

### 5. Monitor Costs

```python
class MyAgent(CustomAgent):
    async def execute_task(self, task):
        # ... do work ...

        # Track costs
        self.track_cost(
            input_tokens=500,
            output_tokens=200,
            cost_usd=0.015
        )

        return result
```

---

## Common Patterns

### Pattern 1: Fan-Out, Fan-In

```python
# Process multiple items in parallel, then aggregate
results = await mesh.run_workflow([
    # Fan-out: Process items
    {"id": "item1", "agent": "processor", "task": "Process item 1"},
    {"id": "item2", "agent": "processor", "task": "Process item 2"},
    {"id": "item3", "agent": "processor", "task": "Process item 3"},

    # Fan-in: Aggregate results
    {
        "id": "aggregate",
        "agent": "aggregator",
        "task": "Combine all processed items",
        "depends_on": ["item1", "item2", "item3"]
    }
])
```

### Pattern 2: Conditional Execution

```python
# Execute step 1
results = await mesh.run_workflow([
    {"id": "check", "agent": "validator", "task": "Validate input data"}
])

# Decide next step based on result
if results[0]['output']['valid']:
    results = await mesh.run_workflow([
        {"agent": "processor", "task": "Process valid data"}
    ])
else:
    print("Validation failed, skipping processing")
```

### Pattern 3: Retry with Different Agent

```python
try:
    # Try primary agent
    result = await mesh.run_workflow([
        {"agent": "primary_scraper", "task": "Scrape website"}
    ])
except Exception:
    # Fallback to backup agent
    result = await mesh.run_workflow([
        {"agent": "backup_scraper", "task": "Scrape website"}
    ])
```

---

## Troubleshooting

### Issue: Agent not found

```python
# Error: No agent found for step
# Solution: Check role/capability spelling
mesh.add_agent(AutoAgent, role="calculator", capabilities=["math"])

# This will fail
await mesh.run_workflow([
    {"agent": "calcul", "task": "..."}  # Typo!
])

# This works
await mesh.run_workflow([
    {"agent": "calculator", "task": "..."}  # Correct role
])

# This also works
await mesh.run_workflow([
    {"agent": "math", "task": "..."}  # Uses capability
])
```

### Issue: Mesh not started

```python
# Error: RuntimeError: Workflow engine not started
# Solution: Call mesh.start() before run_workflow()

mesh = Mesh()
mesh.add_agent(...)
await mesh.start()  # ← Don't forget this!
await mesh.run_workflow([...])
```

### Issue: Timeout

```python
# Error: TimeoutError: Execution exceeded 300 seconds
# Solution: Increase timeout

config = {'execution_timeout': 600}  # 10 minutes
mesh = Mesh(config=config)
```

### Issue: No LLM provider configured

```python
# Error: RuntimeError: No LLM provider configured
# Solution: Set environment variables

# .env file
CLAUDE_API_KEY=your-key
# or
AZURE_API_KEY=your-key
AZURE_ENDPOINT=https://...
```

### Issue: Code execution fails

```python
# Check logs for details
import logging
logging.basicConfig(level=logging.DEBUG)

# Enable verbose output
config = {'log_level': 'DEBUG'}
mesh = Mesh(config=config)
```

---

## Next Steps

1. **[AutoAgent Guide](AUTOAGENT_GUIDE.md)** - Multi-node distributed mode
2. **[CustomAgent Guide](CUSTOMAGENT_GUIDE.md)** - P2P and distributed with your code
3. **[API Reference](API_REFERENCE.md)** - Detailed component documentation
4. **[Configuration Guide](CONFIGURATION.md)** - Environment setup
5. **Explore `examples/`** directory for more code samples

---

## Version

User Guide for JarvisCore v1.0.0

Last Updated: 2026-02-03
