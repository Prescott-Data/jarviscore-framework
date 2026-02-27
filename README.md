# JarvisCore

**Orchestrate multi-agent systems with peer-to-peer coordination, unified memory, and built-in auth.**

## Features

- **Agent Profiles** — AutoAgent auto-generates and executes function tools under Kernel supervision; CustomAgent is bring-your-own-logic for advanced use cases
- **Human In the Loop (HITL)** — Pause and resume agent execution for human review and approval
- **P2P Mesh** — Agent discovery, peer-to-peer communication, and cognitive discovery via SWIM protocol + ZMQ
- **Workflow Orchestration** — Dependencies, context passing, multi-step pipelines with crash recovery
- **Distributed Autonomous Workers** — Mesh claims workflow steps without hardcoding step IDs
- **UnifiedMemory** — EpisodicLedger, LongTermMemory, RedisMemoryAccessor, WorkingScratchpad
- **Context Distillation** — TruthContext, TruthFact, Evidence models for shared agent knowledge
- **Nexus OSS Auth** — Full OAuth flow via `requires_auth=True`; no boilerplate in agents
- **Telemetry / Tracing** — TraceManager (Redis + JSONL), Prometheus step metrics
- **Integrations** — FastAPI, aiohttp, and other async frameworks via `jarviscore.integrations`

## Installation

```bash
pip install jarviscore-framework

# With Redis support (required for distributed features)
pip install "jarviscore-framework[redis]"

# With Prometheus metrics
pip install "jarviscore-framework[prometheus]"

# Everything
pip install "jarviscore-framework[redis,prometheus]"
```

## Setup

```bash
# Initialize project
python -m jarviscore.cli.scaffold --examples
cp .env.example .env
# Add your LLM API key to .env

# Start Redis (required for mailbox, memory, distributed workflows)
docker compose -f docker-compose.infra.yml up -d

# Validate
python -m jarviscore.cli.check --validate-llm
python -m jarviscore.cli.smoketest
```

## Quick Start

### AutoAgent

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

mesh = Mesh(mode="distributed", config={"bind_port": 7950, "redis_url": "redis://localhost:6379/0"})
mesh.add(ProcessorAgent)
await mesh.start()

results = await mesh.workflow("demo", [
    {"agent": "processor", "task": "Process", "params": {"data": [1, 2, 3]}}
])
print(results[0]["output"])  # [2, 4, 6]
```

## Infrastructure Stack

Every agent receives the full infrastructure stack automatically — no wiring required.

| Feature | Injected as | Enabled by |
|---------|-------------|------------|
| Blob storage | `self._blob_storage` | `STORAGE_BACKEND=local` (default) |
| Context distillation | `TruthContext`, `ContextManager` | automatic |
| Telemetry / tracing | `TraceManager` | automatic (`PROMETHEUS_ENABLED` for metrics) |
| Mailbox messaging | `self.mailbox` | `REDIS_URL` |
| Function registry | `self.code_registry` | automatic (AutoAgent) |
| Kernel OODA loop | `Kernel` (AutoAgent internals) | automatic (AutoAgent) |
| Distributed workflow | `WorkflowEngine` | `REDIS_URL` |
| Nexus OSS auth | `self._auth_manager` | `requires_auth=True` + `NEXUS_GATEWAY_URL` |
| Unified memory | `UnifiedMemory`, `EpisodicLedger`, `LTM` | `REDIS_URL` |
| Auto-injection | all of the above | automatic |

```python
class MyAgent(CustomAgent):
    requires_auth = True   # → self._auth_manager injected

    async def setup(self):
        await super().setup()
        # All infrastructure already injected — no __init__ wiring needed
        self.memory = UnifiedMemory(
            workflow_id="my-workflow", step_id="step-1",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

    async def execute_task(self, task):
        # Save artifact
        await self._blob_storage.save("results/output.json", json.dumps(result))

        # Notify another agent
        self.mailbox.send(other_agent_id, {"event": "done", "workflow": "my-workflow"})

        # Log to episodic ledger
        await self.memory.episodic.append({"event": "step_complete", "ts": time.time()})

        return {"status": "success", "output": result}
```

## Production Examples

All examples require Redis (`docker compose -f docker-compose.infra.yml up -d`).

| Example | Mode | Profile |
|---------|------|---------|
| Ex1 — Financial Pipeline | autonomous | AutoAgent |
| Ex2 — Research Network (4 nodes) | distributed | AutoAgent |
| Ex3 — Support Swarm | p2p | CustomAgent |
| Ex4 — Content Pipeline | distributed | CustomAgent |
| Investment Committee | autonomous | AutoAgent + CustomAgent |

```bash
# Ex1: Financial pipeline (single process)
python examples/ex1_financial_pipeline.py

# Ex2: 4-node distributed research network
python examples/ex2_synthesizer.py &       # Start seed first (port 7949)
python examples/ex2_research_node1.py &    # port 7946
python examples/ex2_research_node2.py &    # port 7947
python examples/ex2_research_node3.py &    # port 7948

# Ex3: Customer support swarm (P2P + optional Nexus OSS auth)
python examples/ex3_support_swarm.py

# Ex4: Content pipeline with LTM (sequential, single process)
python examples/ex4_content_pipeline.py

# Investment Committee: 7-agent workflow with web dashboard
cd examples/investment_committee
python committee.py --mode full --ticker NVDA --amount 1500000
# or: python dashboard.py  (web UI on http://localhost:8004)
```

## Profiles

| Profile | You Write | JarvisCore Handles |
|---------|-----------|-------------------|
| **AutoAgent** | System prompt (3 attributes) | Agent-generated function tools, Kernel OODA loop, sandboxed execution, repair, function registry |
| **CustomAgent** | `on_peer_request()` and/or `execute_task()` | Mesh, discovery, routing, lifecycle, full infrastructure stack |

## Execution Modes

| Mode | Use Case |
|------|----------|
| `autonomous` | Single machine, agent-generated function tools (AutoAgent) |
| `p2p` | Agent-to-agent communication, swarms (CustomAgent) |
| `distributed` | Multi-node workflows + P2P + Redis crash recovery |

## Integrations

JarvisCore is **async-first**. Best experience with async frameworks.

| Framework | Integration |
|-----------|-------------|
| **FastAPI** | `JarvisLifespan` — 3-line setup via `jarviscore.integrations.fastapi` |
| **aiohttp, Quart, Tornado** | Manual lifecycle (see docs) |
| **Flask, Django** | Background thread pattern (see docs) |

```python
from fastapi import FastAPI
from jarviscore.profiles import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan

class ProcessorAgent(CustomAgent):
    role = "processor"
    capabilities = ["processing"]

    async def on_peer_request(self, msg):
        return {"result": msg.data.get("task", "").upper()}

app = FastAPI(lifespan=JarvisLifespan(ProcessorAgent(), mode="p2p"))
```

## Documentation

**[https://jarviscore.developers.prescottdata.io/](https://jarviscore.developers.prescottdata.io/)**

| Guide | Description |
|-------|-------------|
| [Getting Started](https://jarviscore.developers.prescottdata.io/GETTING_STARTED/) | 5-minute quickstart |
| [AutoAgent](https://jarviscore.developers.prescottdata.io/AUTOAGENT_GUIDE/) | Agent profiles, Kernel, distributed research network |
| [CustomAgent](https://jarviscore.developers.prescottdata.io/CUSTOMAGENT_GUIDE/) | CustomAgent patterns, infrastructure stack, production walkthroughs |
| [User Guide](https://jarviscore.developers.prescottdata.io/USER_GUIDE/) | Complete documentation including memory and auth |
| [API Reference](https://jarviscore.developers.prescottdata.io/API_REFERENCE/) | Detailed API docs for all infrastructure classes |
| [Configuration](https://jarviscore.developers.prescottdata.io/CONFIGURATION/) | Settings reference and environment variable guide |
| [Troubleshooting](https://jarviscore.developers.prescottdata.io/TROUBLESHOOTING/) | Common issues and diagnostics |
| [Changelog](https://jarviscore.developers.prescottdata.io/CHANGELOG/) | Full release history |

Docs are also bundled with the package:

```bash
python -c "import jarviscore; print(jarviscore.__path__[0] + '/docs')"
```

## Version

**1.0.0**

## License

Apache 2.0 — see [LICENSE](https://github.com/Prescott-Data/jarviscore-framework/blob/main/LICENSE) for details.
