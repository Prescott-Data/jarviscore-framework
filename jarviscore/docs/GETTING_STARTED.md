# Getting Started with JarvisCore

Build your first AI agent in 5 minutes!

---

## Choose Your Path

### Profiles (How agents execute)

| Profile | Best For | LLM Required |
|---------|----------|--------------|
| **AutoAgent** | Rapid prototyping, LLM generates code from prompts | Yes |
| **CustomAgent** | Your own code with P2P handlers or workflow tasks | Optional |

### Execution Modes (How agents are orchestrated)

| Mode | Use Case | Start Here |
|------|----------|------------|
| **Autonomous** | Single machine, simple pipelines | This guide |
| **P2P** | Direct agent communication, swarms | [CustomAgent Guide](CUSTOMAGENT_GUIDE.md) |
| **Distributed** | Multi-node production systems | [CustomAgent Guide](CUSTOMAGENT_GUIDE.md) |

**Recommendation:**
- **New to agents?** Start with **AutoAgent + Autonomous mode** below
- **Have existing code?** Jump to **CustomAgent** section
- **Building APIs?** See **CustomAgent + FastAPI** below

---

## What You'll Build

An **AutoAgent** that takes natural language prompts and automatically:
1. Generates Python code using an LLM
2. Executes the code securely in a sandbox
3. Returns the result

**No manual coding required** - just describe what you want!

---

## Prerequisites

- Python 3.10 or higher
- An API key from one of these LLM providers:
  - [Claude (Anthropic)](https://console.anthropic.com/) - Recommended
  - [Azure OpenAI](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
  - [Google Gemini](https://ai.google.dev/)
  - Local vLLM server (free, self-hosted)

---

## Step 1: Install JarvisCore (30 seconds)

```bash
pip install jarviscore-framework
```

---

## Step 2: Configure Your LLM (2 minutes)

Initialize your project and create configuration files:

```bash
# Initialize project (creates .env.example and optionally examples)
python -m jarviscore.cli.scaffold --examples

# Copy and configure your environment
cp .env.example .env
```

Edit `.env` and add **ONE** of these API keys:

### Option 1: Claude (Recommended)
```bash
CLAUDE_API_KEY=sk-ant-your-key-here
```

### Option 2: Azure OpenAI
```bash
AZURE_API_KEY=your-key-here
AZURE_ENDPOINT=https://your-resource.openai.azure.com
AZURE_DEPLOYMENT=gpt-4o
```

### Option 3: Google Gemini
```bash
GEMINI_API_KEY=your-key-here
```

### Option 4: Local vLLM (Free, Self-Hosted)
```bash
LLM_ENDPOINT=http://localhost:8000
LLM_MODEL=Qwen/Qwen2.5-Coder-32B-Instruct
```

**Tip:** JarvisCore automatically tries providers in this order:
Claude -> Azure -> Gemini -> vLLM

---

## Step 3: Validate Your Setup (30 seconds)

Run the health check to ensure everything works:

```bash
# Basic check
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm
```

You should see:
```
 Python Version: OK
 JarvisCore Package: OK
 Dependencies: OK
 .env File: OK
 Claude/Azure/Gemini: OK
```

Run the smoke test for end-to-end validation:

```bash
python -m jarviscore.cli.smoketest
```

**If all tests pass**, you're ready to build agents!

---

## Step 4: Build Your First Agent (3 minutes)

Create a file called `my_first_agent.py`:

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent


# 1. Define your agent
class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculations"]
    system_prompt = """
    You are a math expert. Generate Python code to solve problems.
    Always store the result in a variable named 'result'.
    """


# 2. Create and run
async def main():
    # Initialize the mesh
    mesh = Mesh(mode="autonomous")

    # Add your agent
    mesh.add(CalculatorAgent)

    # Start the mesh
    await mesh.start()

    # Execute a task with a simple prompt
    results = await mesh.workflow("calc-workflow", [
        {
            "agent": "calculator",
            "task": "Calculate the factorial of 10"
        }
    ])

    # Get the result
    result = results[0]
    print(f"Status: {result['status']}")
    print(f"Output: {result['output']}")
    print(f"Execution time: {result['execution_time']:.2f}s")

    # Stop the mesh
    await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

### Run it:

```bash
python my_first_agent.py
```

### Expected Output:

```
Status: success
Output: 3628800
Execution time: 4.23s
```

**Congratulations!** You just built an AI agent with zero manual coding!

---

## Step 5: CustomAgent (Your Own Code)

If you have existing agents or don't need LLM code generation, use **CustomAgent**:

### Workflow Mode (execute_task)

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent


class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["data_processing"]

    async def execute_task(self, task):
        """Your existing logic goes here."""
        data = task.get("params", {}).get("data", [])
        result = [x * 2 for x in data]
        return {"status": "success", "output": result}


async def main():
    mesh = Mesh(mode="distributed", config={
        'bind_port': 7950,
        'node_name': 'custom-node',
    })
    mesh.add(MyAgent)
    await mesh.start()

    results = await mesh.workflow("custom-demo", [
        {"agent": "processor", "task": "Process data", "params": {"data": [1, 2, 3]}}
    ])

    print(results[0]["output"])  # [2, 4, 6]
    await mesh.stop()


asyncio.run(main())
```

### P2P Mode (on_peer_request)

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent


class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["data_processing"]

    async def on_peer_request(self, msg):
        """Handle requests from other agents."""
        data = msg.data.get("data", [])
        return {"result": [x * 2 for x in data]}


async def main():
    mesh = Mesh(mode="p2p", config={'bind_port': 7950})
    mesh.add(MyAgent)
    await mesh.start()

    # Agent listens for peer requests
    print("Agent running. Press Ctrl+C to stop.")
    await mesh.agents[0].run()

    await mesh.stop()


asyncio.run(main())
```

**Key Benefits:**
- Keep your existing logic
- Works with any framework (LangChain, CrewAI, etc.)

---

## Integrations

JarvisCore is **async-first**. Use `jarviscore.integrations` to serve agents over HTTP or integrate with existing frameworks.

### FastAPI

```python
from fastapi import FastAPI
from jarviscore.profiles import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan

class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": msg.data}

app = FastAPI(lifespan=JarvisLifespan(MyAgent(), mode="p2p", bind_port=7950))
```

### Pattern 2: Other Async Frameworks (aiohttp, Quart, Tornado)

```python
# aiohttp example
import asyncio
from aiohttp import web
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent

class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": msg.data}

mesh = None
agent = None

async def on_startup(app):
    global mesh, agent
    mesh = Mesh(mode="p2p", config={"bind_port": 7950})
    agent = mesh.add(MyAgent())
    await mesh.start()
    asyncio.create_task(agent.run())
    app['agent'] = agent

async def on_cleanup(app):
    agent.request_shutdown()
    await mesh.stop()

async def process_handler(request):
    agent = request.app['agent']
    result = await agent.peers.request("analyst", {"task": "analyze"})
    return web.json_response(result)

app = web.Application()
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)
app.router.add_post('/process', process_handler)
```

### Pattern 3: Sync Frameworks (Flask, Django)

```python
# Flask example - requires background thread
import asyncio
import threading
from flask import Flask, jsonify
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent

app = Flask(__name__)

class MyAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": msg.data}

# Global state
_loop = None
_mesh = None
_agent = None

def _start_mesh():
    """Run in background thread."""
    global _loop, _mesh, _agent
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)

    _mesh = Mesh(mode="p2p", config={"bind_port": 7950})
    _agent = _mesh.add(MyAgent())

    _loop.run_until_complete(_mesh.start())
    _loop.run_until_complete(_agent.run())

# Start mesh in background thread
_thread = threading.Thread(target=_start_mesh, daemon=True)
_thread.start()

@app.route("/process", methods=["POST"])
def process():
    future = asyncio.run_coroutine_threadsafe(
        _agent.peers.request("analyst", {"task": "analyze"}),
        _loop
    )
    result = future.result(timeout=30)
    return jsonify(result)
```

### Framework Recommendation

| Use Case | Recommended Approach |
|----------|---------------------|
| FastAPI project | FastAPI + JarvisLifespan |
| Existing async app | Manual mesh lifecycle |
| Existing Flask/Django | Background thread pattern |
| CLI tool / script | Standalone asyncio.run() |

**For more:** See [CustomAgent Guide](CUSTOMAGENT_GUIDE.md) for detailed integration examples.

---

## Key Concepts

### 1. AutoAgent Profile

The `AutoAgent` profile handles the "prompt -> code -> result" workflow automatically:

```python
class MyAgent(AutoAgent):
    role = "unique_name"              # Unique identifier
    capabilities = ["skill1", "skill2"]  # What it can do
    system_prompt = "Instructions for the LLM"  # How to generate code
```

### 2. CustomAgent Profile

The `CustomAgent` profile lets you bring your own execution logic:

```python
class MyAgent(CustomAgent):
    role = "unique_name"
    capabilities = ["skill1", "skill2"]

    # For P2P messaging - handle requests from other agents
    async def on_peer_request(self, msg):
        return {"result": ...}  # Return value sent as response

    # For P2P messaging - handle notifications (fire-and-forget)
    async def on_peer_notify(self, msg):
        await self.log(msg.data)

    # For workflow tasks
    async def execute_task(self, task):
        return {"status": "success", "output": ...}

    # Configuration
    listen_timeout = 1.0   # Seconds to wait for messages
    auto_respond = True    # Auto-send on_peer_request return value
```

### 3. Mesh

The `Mesh` is the orchestrator that manages agents and workflows:

```python
mesh = Mesh(mode="autonomous")  # Or "p2p", "distributed"
mesh.add(MyAgent)               # Register your agent
await mesh.start()              # Initialize
results = await mesh.workflow(...)  # Execute tasks
await mesh.stop()               # Cleanup
```

**Modes:**
- `autonomous`: Workflow engine only (AutoAgent)
- `p2p`: P2P coordinator for agent-to-agent communication (CustomAgent)
- `distributed`: Both workflow engine AND P2P (CustomAgent)

### 4. Workflow

A workflow is a list of tasks to execute:

```python
results = await mesh.workflow("workflow-id", [
    {
        "agent": "agent_role",     # Which agent to use
        "task": "What to do",      # Natural language prompt
        "dependencies": []         # Optional: wait for other steps
    }
])
```

### 5. Results

Each task returns a result dict:

```python
{
    "status": "success",           # success or failure
    "output": 42,                  # The actual result
    "execution_time": 3.14,        # Seconds
    "repairs": 0,                  # Auto-fix attempts
    "code": "result = 6 * 7",      # Generated code
    "agent_id": "calculator-abc123"
}
```

---

## Common Patterns

### Pattern 1: Error Handling

```python
try:
    results = await mesh.workflow("workflow-1", [
        {"agent": "calculator", "task": "Calculate 1/0"}
    ])

    if results[0]['status'] == 'failure':
        print(f"Error: {results[0]['error']}")
        print(f"Repair attempts: {results[0]['repairs']}")

except Exception as e:
    print(f"Workflow failed: {e}")
```

### Pattern 2: Dynamic Tasks

```python
user_input = "Calculate the area of a circle with radius 5"

results = await mesh.workflow("dynamic", [
    {"agent": "calculator", "task": user_input}
])

print(results[0]['output'])  # 78.54
```

### Pattern 3: Multi-Step Workflow

```python
results = await mesh.workflow("multi-step", [
    {
        "id": "step1",
        "agent": "calculator",
        "task": "Calculate 5 factorial"
    },
    {
        "id": "step2",
        "agent": "data_analyst",
        "task": "Take the result from step1 and calculate its square root",
        "dependencies": ["step1"]  # Waits for step1 to complete
    }
])

print(f"Factorial(5): {results[0]['output']}")      # 120
print(f"Square root: {results[1]['output']:.2f}")   # 10.95
```

---

## Troubleshooting

### Issue: "No LLM providers configured"

**Solution:** Check your `.env` file has a valid API key:
```bash
python -m jarviscore.cli.check --validate-llm
```

### Issue: "Task failed: Unknown error"

**Solution:** Check logs for details:
```bash
ls -la logs/
cat logs/<agent>/<latest>.json
```

### Issue: Slow execution

**Solutions:**
- Use faster models (Claude Haiku, Gemini Flash)
- Simplify prompts
- Use local vLLM for zero-latency

---

## Next Steps

1. **CustomAgent Guide**: P2P and distributed with your code -> [CUSTOMAGENT_GUIDE.md](CUSTOMAGENT_GUIDE.md)
2. **AutoAgent Guide**: Multi-node distributed mode -> [AUTOAGENT_GUIDE.md](AUTOAGENT_GUIDE.md)
3. **User Guide**: Complete documentation -> [USER_GUIDE.md](USER_GUIDE.md)
4. **API Reference**: [API_REFERENCE.md](API_REFERENCE.md)
5. **Examples**: Check out `examples/` directory

---

## Best Practices

### DO

- **Be specific in prompts**: "Calculate factorial of 10" > "Do math"
- **Test with simple tasks first**: Validate your setup works
- **Use appropriate models**: Haiku/Flash for simple tasks, Opus/GPT-4 for complex
- **Use async frameworks**: FastAPI, aiohttp for best experience

### DON'T

- **Use vague prompts**: "Do something" won't work well
- **Expect instant results**: LLM generation takes 2-5 seconds
- **Skip validation**: Always run health check after setup
- **Commit API keys**: Keep `.env` out of version control

---

**Happy building with JarvisCore!**

---

## Infrastructure Stack

JarvisCore v0.4.0 ships a full production infrastructure stack. All features are
opt-in via environment variables and degrade gracefully when not configured.

### Quick Reference

| Feature | One-line description | Enabled by |
|---------|----------------------|------------|
| Blob storage | Save / load artifacts (local or Azure) | `STORAGE_BACKEND=local` (default) |
| Context distillation | `TruthContext` / `TruthFact` / `Evidence` models | automatic |
| Telemetry / tracing | `TraceManager` (Redis + JSONL), Prometheus metrics | `PROMETHEUS_ENABLED=true` |
| Mailbox messaging | Async agent-to-agent messages via Redis Streams | `REDIS_URL` |
| Function registry | Graduated/verified agent-generated function tools (AutoAgent) | automatic (AutoAgent) |
| Kernel / SubAgent | OODA loop, coder/researcher/communicator routing | automatic (AutoAgent) |
| Distributed workflow | Redis DAG, crash recovery, remote step dispatch | `REDIS_URL` |
| Nexus OSS auth | Full OAuth flow injected via `requires_auth=True` | `NEXUS_GATEWAY_URL` |
| UnifiedMemory | EpisodicLedger, LTM, WorkingScratchpad, accessor | `REDIS_URL` |
| Auto-injection | `_redis_store`, `_blob_storage`, `mailbox` wired before `setup()` | automatic |

**Infrastructure quick-start:**

```bash
# Start Redis + Prometheus + Grafana
docker compose -f docker-compose.infra.yml up -d

# Install with extras
pip install "jarviscore-framework[redis,prometheus]"
```

---

### Auto-Injection Pattern

Before every agent's `setup()` call, the Mesh wires three infrastructure objects
directly onto the agent. No constructor boilerplate needed:

```python
from jarviscore.profiles import CustomAgent
from jarviscore.memory import UnifiedMemory

class MyAgent(CustomAgent):
    role = "worker"
    capabilities = ["processing"]

    async def setup(self):
        await super().setup()
        # All infrastructure already injected — no __init__ wiring needed
        self.memory = UnifiedMemory(
            workflow_id="my-workflow", step_id="worker",
            agent_id=self.role,
            redis_store=self._redis_store,   # auto-injected
            blob_storage=self._blob_storage, # auto-injected
        )
```

---

### Blob Storage

Save and load any artifact (string, bytes, JSON):

```python
# Save
await self._blob_storage.save("reports/output.md", markdown_text)
await self._blob_storage.save("data/result.json", json.dumps(data))

# Load
content = await self._blob_storage.load("reports/output.md")
```

Path convention: `{type}/{workflow_id}/{filename}.{ext}`

---

### Mailbox Messaging

Fire-and-forget messages between agents backed by Redis Streams:

```python
# Send to another agent (by agent_id)
self.mailbox.send(other_agent_id, {"event": "done", "workflow": "my-workflow"})

# Drain inbox
messages = self.mailbox.read(max_messages=10)
for msg in messages:
    print(msg["event"])
```

---

### UnifiedMemory + EpisodicLedger

Full memory stack per agent:

```python
from jarviscore.memory import UnifiedMemory

# In setup()
self.memory = UnifiedMemory(
    workflow_id="wf-001", step_id="my-step",
    agent_id=self.role,
    redis_store=self._redis_store,
    blob_storage=self._blob_storage,
)

# In execute_task() — append an event
await self.memory.episodic.append({"event": "task_started", "ts": time.time()})

# Load last 5 events
recent = await self.memory.episodic.tail(5)

# Long-term memory
await self.memory.ltm.save_summary("Key findings from this run...")
summary = await self.memory.ltm.load_summary()
```

---

### RedisMemoryAccessor (Cross-Step Reads)

Read any prior step's output from Redis without passing data manually:

```python
from jarviscore.memory import RedisMemoryAccessor

accessor = RedisMemoryAccessor(self._redis_store, workflow_id="wf-001")
raw = accessor.get("research")                          # reads step_output:wf-001:research
research = raw.get("output", raw) if isinstance(raw, dict) else {}
```

---

### Nexus OSS Auth Injection

Set `requires_auth = True` on any agent to receive an injected `_auth_manager`:

```python
class TechnicalAgent(CustomAgent):
    role = "technical_support"
    requires_auth = True    # → self._auth_manager injected before setup()

    async def execute_task(self, task):
        if self._auth_manager:
            result = await self._auth_manager.make_authenticated_request(
                provider="github", method="GET",
                url="https://api.github.com/user",
            )
        # Graceful degradation: _auth_manager is None when NEXUS_GATEWAY_URL not set
```

Config: `NEXUS_GATEWAY_URL`, `AUTH_MODE=production|mock`, `NEXUS_DEFAULT_USER_ID`.

---

### Production Examples

All examples require Redis. Start infrastructure first:

```bash
docker compose -f docker-compose.infra.yml up -d
cp .env.example .env   # set your LLM API key
```

| Example | Mode | Profile |
|---------|------|---------|
| Ex1 — Financial Pipeline | autonomous | AutoAgent |
| Ex2 — Research Network (4 nodes) | distributed | AutoAgent |
| Ex3 — Support Swarm | p2p | CustomAgent |
| Ex4 — Content Pipeline | distributed | CustomAgent |

```bash
# Ex1: Financial pipeline (single process, ~60s)
python examples/ex1_financial_pipeline.py

# Ex2: 4-node distributed research network (start seed first)
python examples/ex2_synthesizer.py &       # port 7949
python examples/ex2_research_node1.py &    # port 7946
python examples/ex2_research_node2.py &    # port 7947
python examples/ex2_research_node3.py &    # port 7948

# Ex3: Customer support swarm (P2P + optional Nexus OSS auth)
python examples/ex3_support_swarm.py

# Ex4: Content pipeline with LTM (~90s)
python examples/ex4_content_pipeline.py
```

**Full details:** [AUTOAGENT_GUIDE.md](AUTOAGENT_GUIDE.md) • [CUSTOMAGENT_GUIDE.md](CUSTOMAGENT_GUIDE.md) • [CONFIGURATION.md](CONFIGURATION.md)
