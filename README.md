# JarvisCore Framework

**Build autonomous AI agents in 3 lines of code. Production-ready orchestration with P2P mesh networking.**

## Features

- ✅ **Simple Agent Definition** - Write just 3 attributes, framework handles everything
- ✅ **Custom Profile** - Use your existing agents (LangChain, CrewAI, etc.) with zero migration
- ✅ **P2P Mesh Architecture** - Automatic agent discovery and task routing via SWIM protocol
- ✅ **Event-Sourced State** - Complete audit trail with crash recovery
- ✅ **Autonomous Execution** - LLM code generation with automatic repair

## Installation

```bash
pip install jarviscore-framework
```

## Setup & Validation

### 1. Initialize Project

```bash
# Create .env.example and example files in your project
python -m jarviscore.cli.scaffold --examples

# Configure your environment
cp .env.example .env
# Edit .env and add one of: CLAUDE_API_KEY, AZURE_API_KEY, GEMINI_API_KEY, or LLM_ENDPOINT
```

### 2. Validate Installation

```bash
# Check setup
python -m jarviscore.cli.check

# Test LLM connectivity
python -m jarviscore.cli.check --validate-llm

# Run smoke test (end-to-end validation)
python -m jarviscore.cli.smoketest
```

✅ **All checks pass?** You're ready to build agents!

## Quick Start

### Option 1: AutoAgent (LLM-Powered)

For rapid prototyping with automatic code generation:

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math"]
    system_prompt = "You are a math expert..."

mesh = Mesh(mode="autonomous")
mesh.add(CalculatorAgent)
await mesh.start()

results = await mesh.workflow("calc-1", [
    {"agent": "calculator", "task": "Calculate factorial of 10"}
])
```

### Option 2: Custom Profile with Decorator

For existing classes - just add a decorator:

```python
from jarviscore import Mesh, jarvis_agent, JarvisContext

@jarvis_agent(role="processor", capabilities=["data_processing"])
class DataProcessor:
    def run(self, data):
        return {"processed": [x * 2 for x in data]}

@jarvis_agent(role="aggregator", capabilities=["aggregation"])
class Aggregator:
    def run(self, task, ctx: JarvisContext):
        # Access previous step results
        previous = ctx.previous("step1")
        return {"sum": sum(previous.get("processed", []))}

mesh = Mesh(mode="autonomous")
mesh.add(DataProcessor)
mesh.add(Aggregator)
await mesh.start()

results = await mesh.workflow("pipeline", [
    {"id": "step1", "agent": "processor", "task": "Process", "params": {"data": [1,2,3]}},
    {"id": "step2", "agent": "aggregator", "task": "Aggregate", "depends_on": ["step1"]}
])
```

### Option 3: Custom Profile with wrap()

For pre-instantiated objects (LangChain, CrewAI, etc.):

```python
from jarviscore import Mesh, wrap

# Your existing agent (LangChain, CrewAI, etc.)
my_llm_agent = MyLangChainAgent(model="gpt-4")

# Wrap it for JarvisCore
wrapped = wrap(
    my_llm_agent,
    role="assistant",
    capabilities=["chat", "qa"],
    execute_method="invoke"  # LangChain uses "invoke"
)

mesh = Mesh(mode="autonomous")
mesh.add(wrapped)
await mesh.start()
```

## Architecture

JarvisCore is built on three layers:

1. **Execution Layer (20%)** - Profile-specific execution (AutoAgent, Custom Profile)
2. **Orchestration Layer (60%)** - Workflow engine, dependencies, state management
3. **P2P Layer (20%)** - Agent discovery, task routing, mesh coordination

## Agent Profiles

| Profile | Use Case | LLM Required |
|---------|----------|--------------|
| **AutoAgent** | Rapid prototyping, LLM code generation | Yes |
| **Custom Profile** | Existing agents, full control | No |
| **CustomAgent** | Manual implementation | No |

## Documentation

- [User Guide](jarviscore/docs/USER_GUIDE.md) - Complete guide for AutoAgent users
- [API Reference](jarviscore/docs/API_REFERENCE.md) - Detailed API documentation
- [Configuration Guide](jarviscore/docs/CONFIGURATION.md) - Settings and environment variables
- [Troubleshooting](jarviscore/docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Examples](examples/) - Working code examples

## Development Status

**Version:** 0.2.0 (Alpha)

## License

MIT License - see LICENSE file for details
