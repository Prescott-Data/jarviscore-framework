# JarvisCore Framework

**Build autonomous AI agents with P2P mesh networking.**

## Features

- **AutoAgent** - LLM generates and executes code from natural language
- **CustomAgent** - Bring your own logic with P2P message handlers
- **P2P Mesh** - Agent discovery and communication via SWIM protocol
- **Workflow Orchestration** - Dependencies, context passing, multi-step pipelines
- **FastAPI Integration** - 3-line setup with JarvisLifespan
- **Cognitive Discovery** - LLM-ready peer descriptions for autonomous delegation
- **Cloud Deployment** - Self-registering agents for Docker/K8s

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

### CustomAgent + FastAPI (Recommended)

```python
from fastapi import FastAPI
from jarviscore.profiles import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan

class ProcessorAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        # Handle requests from other agents
        return {"result": msg.data.get("task", "").upper()}

# 3 lines to integrate with FastAPI
app = FastAPI(lifespan=JarvisLifespan(ProcessorAgent(), mode="p2p"))
```

### CustomAgent (Workflow Mode)

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

## Profiles

| Profile | You Write | JarvisCore Handles |
|---------|-----------|-------------------|
| **AutoAgent** | System prompt | LLM code generation, sandboxed execution |
| **CustomAgent** | `on_peer_request()` and/or `execute_task()` | Mesh, discovery, routing, lifecycle |

## Execution Modes

| Mode | Use Case |
|------|----------|
| `autonomous` | Single machine, LLM code generation (AutoAgent) |
| `p2p` | Agent-to-agent communication, swarms (CustomAgent) |
| `distributed` | Multi-node workflows + P2P (CustomAgent) |

## Framework Integration

JarvisCore is **async-first**. Best experience with async frameworks.

| Framework | Integration |
|-----------|-------------|
| **FastAPI** | `JarvisLifespan` (3 lines) |
| **aiohttp, Quart, Tornado** | Manual lifecycle (see docs) |
| **Flask, Django** | Background thread pattern (see docs) |

## Documentation

Documentation is included with the package:

```bash
python -c "import jarviscore; print(jarviscore.__path__[0] + '/docs')"
```

**Available guides:**
- `GETTING_STARTED.md` - 5-minute quickstart
- `CUSTOMAGENT_GUIDE.md` - CustomAgent patterns and framework integration
- `AUTOAGENT_GUIDE.md` - LLM-powered agents
- `USER_GUIDE.md` - Complete documentation
- `API_REFERENCE.md` - Detailed API docs
- `CONFIGURATION.md` - Settings reference

## Version

**0.4.0**

## License

MIT License
