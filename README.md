# JarvisCore Framework

**Build autonomous AI agents with P2P mesh networking.**

## Features

- ✅ **AutoAgent** - LLM generates and executes code from natural language
- ✅ **CustomAgent** - Bring your own logic (LangChain, CrewAI, etc.)
- ✅ **P2P Mesh** - Agent discovery and communication via SWIM protocol
- ✅ **Workflow Orchestration** - Dependencies, context passing, multi-step pipelines

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

## Execution Modes

| Mode | Profile | Use Case |
|------|---------|----------|
| `autonomous` | AutoAgent | Single machine, LLM code generation |
| `p2p` | CustomAgent | Agent-to-agent communication, swarms |
| `distributed` | CustomAgent | Multi-node workflows + P2P |

## Documentation

- [User Guide](jarviscore/docs/USER_GUIDE.md) - Complete documentation
- [Getting Started](jarviscore/docs/GETTING_STARTED.md) - 5-minute quickstart
- [AutoAgent Guide](jarviscore/docs/AUTOAGENT_GUIDE.md) - LLM-powered agents
- [CustomAgent Guide](jarviscore/docs/CUSTOMAGENT_GUIDE.md) - Bring your own code
- [API Reference](jarviscore/docs/API_REFERENCE.md) - Detailed API docs
- [Configuration](jarviscore/docs/CONFIGURATION.md) - Settings reference

## Version

**0.2.0**

## License

MIT License
