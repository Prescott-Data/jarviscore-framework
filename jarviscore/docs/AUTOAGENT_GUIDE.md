# AutoAgent Guide

AutoAgent is the **zero-config** profile where the framework handles everything:
- LLM code generation from natural language
- Sandboxed code execution
- Automatic error repair
- Result storage

You write **3 attributes**, framework does the rest.

---

## Quick Reference

| Mode | Use Case | Key Difference |
|------|----------|----------------|
| **Autonomous** | Single machine | No network, local execution |
| **Distributed** | Multi-node | P2P network + workflow orchestration |

---

## Autonomous Mode

Single-node execution. No networking required.

### Example

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculation"]
    system_prompt = """
    You are a math expert. Generate Python code to solve problems.
    Store the result in a variable named 'result'.
    """

async def main():
    mesh = Mesh(mode="autonomous")  # Default mode
    mesh.add(CalculatorAgent)

    await mesh.start()

    results = await mesh.workflow("calc-task", [
        {"agent": "calculator", "task": "Calculate factorial of 10"}
    ])

    print(results[0]["output"])  # {'result': 3628800}

    await mesh.stop()

asyncio.run(main())
```

### When to Use
- Rapid prototyping
- Single-machine deployments
- Simple task pipelines
- No need for agent-to-agent communication

---

## Distributed Mode

Multi-node execution with P2P networking. Same API, just add config.

### What Changes

| Autonomous | Distributed |
|------------|-------------|
| `mode="autonomous"` | `mode="distributed"` |
| No config needed | Add `bind_port`, `node_name` |
| Single machine | Can span multiple machines |

### Example (Single Node)

```python
import asyncio
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

class CalculatorAgent(AutoAgent):
    role = "calculator"
    capabilities = ["math", "calculation"]
    system_prompt = """
    You are a math expert. Generate Python code to solve problems.
    Store the result in a variable named 'result'.
    """

async def main():
    mesh = Mesh(
        mode="distributed",  # Enable P2P + workflow
        config={
            'bind_port': 7950,        # SWIM protocol port
            'node_name': 'calc-node', # Node identifier
        }
    )
    mesh.add(CalculatorAgent)

    await mesh.start()

    # Same API as autonomous!
    results = await mesh.workflow("calc-task", [
        {"agent": "calculator", "task": "Calculate factorial of 10"}
    ])

    print(results[0]["output"])

    await mesh.stop()

asyncio.run(main())
```

### Example (Multi-Node)

**Node 1 - Seed node with calculator:**
```python
# node1.py
mesh = Mesh(
    mode="distributed",
    config={
        'bind_host': '0.0.0.0',
        'bind_port': 7950,
        'node_name': 'node-1',
    }
)
mesh.add(CalculatorAgent)
await mesh.start()
await mesh.serve_forever()  # Keep running
```

**Node 2 - Joins cluster with analyzer:**
```python
# node2.py
mesh = Mesh(
    mode="distributed",
    config={
        'bind_host': '0.0.0.0',
        'bind_port': 7950,
        'node_name': 'node-2',
        'seed_nodes': '192.168.1.10:7950',  # Node 1's address
    }
)
mesh.add(AnalyzerAgent)
await mesh.start()
await mesh.serve_forever()
```

**Execute workflows across nodes:**
```python
# From any node
results = await mesh.workflow("cross-node", [
    {"agent": "calculator", "task": "..."},  # Runs on Node 1
    {"agent": "analyzer", "task": "...", "depends_on": [0]}  # Runs on Node 2
])
```

### When to Use
- Production multi-node systems
- Agents on different machines
- Scalable agent architectures
- Need cross-node workflow coordination

---

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `bind_host` | `127.0.0.1` | Interface to bind |
| `bind_port` | `7950` | SWIM protocol port |
| `node_name` | `jarviscore-node` | Node identifier |
| `seed_nodes` | `None` | Comma-separated seed addresses |
| `execution_timeout` | `300` | Max seconds per task |
| `max_repair_attempts` | `3` | Auto-repair retries |
| `log_directory` | `./logs` | Result storage path |

---

## Summary

```python
# Autonomous (single node)
mesh = Mesh(mode="autonomous")

# Distributed (multi-node capable)
mesh = Mesh(mode="distributed", config={'bind_port': 7950})

# Everything else stays the same!
mesh.add(MyAutoAgent)
await mesh.start()
results = await mesh.workflow(...)
```

See `examples/calculator_agent_example.py` and `examples/autoagent_distributed_example.py` for complete examples.
