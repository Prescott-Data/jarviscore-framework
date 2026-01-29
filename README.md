# JarvisCore Framework

**Build autonomous AI agents with P2P mesh networking.**

## Features

- ✅ **AutoAgent** - LLM generates and executes code from natural language
- ✅ **CustomAgent** - Bring your own logic (LangChain, CrewAI, etc.)
- ✅ **ListenerAgent** - API-first agents with background P2P (just implement handlers)
- ✅ **P2P Mesh** - Agent discovery and communication via SWIM protocol
- ✅ **Workflow Orchestration** - Dependencies, context passing, multi-step pipelines
- ✅ **FastAPI Integration** - 3-line setup with JarvisLifespan
- ✅ **Cloud Deployment** - Self-registering agents for Docker/K8s

## Installation

```bash
pip install jarviscore-framework
```

## Setup

```bash
# Initialize project
python -m jarviscore.cli.scaffold --examples
cp .env.example .env
# Add your LLM API key to .env

# Validate
python -m jarviscore.cli.check --validate-llm
python -m jarviscore.cli.smoketest
```

## Quick Start

### AutoAgent (LLM-Powered)

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math"]
    system_prompt = "You are a math expert. Store result in 'result'."

mesh = Mesh(mode="autonomous")
mesh.add(CalculatorAgent)
await mesh.start()

results = await mesh.workflow("calc", [
    {"agent": "calculator", "task": "Calculate factorial of 10"}
])
print(results[0]["output"])  # 3628800
```

### CustomAgent (Your Code)

```python
from jarviscore import Mesh
from jarviscore.profiles import CustomAgent

class ProcessorAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def execute_task(self, task):
        data = task.get("params", {}).get("data", [])
        return {"status": "success", "output": [x * 2 for x in data]}

mesh = Mesh(mode="distributed", config={'bind_port': 7950})
mesh.add(ProcessorAgent)
await mesh.start()

results = await mesh.workflow("demo", [
    {"agent": "processor", "task": "Process", "params": {"data": [1, 2, 3]}}
])
print(results[0]["output"])  # [2, 4, 6]
```

### ListenerAgent + FastAPI (API-First)

```python
from fastapi import FastAPI
from jarviscore.profiles import ListenerAgent
from jarviscore.integrations.fastapi import JarvisLifespan

class ProcessorAgent(ListenerAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        # Handle requests from other agents
        return {"result": msg.data.get("task", "").upper()}

# That's it - 3 lines to integrate with FastAPI
app = FastAPI(lifespan=JarvisLifespan(ProcessorAgent(), mode="p2p"))
```

## Execution Modes

| Mode | Profile | Use Case |
|------|---------|----------|
| `autonomous` | AutoAgent | Single machine, LLM code generation |
| `p2p` | CustomAgent, ListenerAgent | Agent-to-agent communication, swarms |
| `distributed` | CustomAgent, ListenerAgent | Multi-node workflows + P2P |

## What's New in 0.3.0

**Developer Experience Improvements:**
- **ListenerAgent** - No more writing `run()` loops. Just implement `on_peer_request()` and `on_peer_notify()` handlers.
- **JarvisLifespan** - FastAPI integration reduced from ~100 lines to 3 lines.
- **Cognitive Discovery** - `peers.get_cognitive_context()` generates LLM-ready peer descriptions. No more hardcoded agent names in prompts.

**Cloud Deployment:**
- **Self-Registration** - `agent.join_mesh()` lets agents join existing meshes without central orchestrator.
- **Remote Visibility** - Agents on different nodes are automatically discovered and callable.

## Documentation

- [User Guide](jarviscore/docs/USER_GUIDE.md) - Complete documentation
- [Getting Started](jarviscore/docs/GETTING_STARTED.md) - 5-minute quickstart
- [AutoAgent Guide](jarviscore/docs/AUTOAGENT_GUIDE.md) - LLM-powered agents
- [CustomAgent Guide](jarviscore/docs/CUSTOMAGENT_GUIDE.md) - Bring your own code
- [API Reference](jarviscore/docs/API_REFERENCE.md) - Detailed API docs
- [Configuration](jarviscore/docs/CONFIGURATION.md) - Settings reference

## Version

**0.3.0**

## License

MIT License
