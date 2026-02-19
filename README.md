# JarvisCore Framework

**Build autonomous AI agents with P2P mesh networking and full infrastructure stack.**

## Features

- **AutoAgent** — LLM generates and executes code from natural language; supervised by Kernel OODA loop
- **CustomAgent** — Bring your own logic with P2P message handlers and workflow steps
- **P2P Mesh** — Agent discovery and communication via SWIM protocol + ZMQ
- **Workflow Orchestration** — Dependencies, context passing, multi-step pipelines with crash recovery
- **Kernel / SubAgent** — OODA loop supervisor with coder / researcher / communicator roles, lease budgets, HITL
- **Infrastructure Stack** — Blob storage, mailbox, memory, auth — auto-injected before every agent starts
- **Distributed Autonomous Workers** — Mesh claims workflow steps without hardcoding STEP_ID
- **UnifiedMemory** — EpisodicLedger, LongTermMemory, RedisMemoryAccessor, WorkingScratchpad
- **Context Distillation** — TruthContext, TruthFact, Evidence models for shared agent knowledge
- **Nexus Auth Injection** — Full OAuth flow via `requires_auth=True`; no boilerplate in agents
- **Telemetry / Tracing** — TraceManager (Redis + JSONL), Prometheus step metrics
- **FastAPI Integration** — 3-line setup with JarvisLifespan
- **Cognitive Discovery** — LLM-ready peer descriptions for autonomous delegation
- **Cloud Deployment** — Self-registering agents for Docker/K8s

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

mesh = Mesh(mode="distributed", config={"bind_port": 7950, "redis_url": "redis://localhost:6379/0"})
mesh.add(ProcessorAgent)
await mesh.start()

results = await mesh.workflow("demo", [
    {"agent": "processor", "task": "Process", "params": {"data": [1, 2, 3]}}
])
print(results[0]["output"])  # [2, 4, 6]
```

## Infrastructure Stack (Phases 1–9)

Every agent receives the full infrastructure stack automatically — no wiring required.

| Phase | Feature | Injected as | Enabled by |
|-------|---------|-------------|------------|
| 1 | Blob storage | `self._blob_storage` | `STORAGE_BACKEND=local` (default) |
| 2 | Context distillation | `TruthContext`, `ContextManager` | automatic |
| 3 | Telemetry / tracing | `TraceManager` | automatic (`PROMETHEUS_ENABLED` for metrics) |
| 4 | Mailbox messaging | `self.mailbox` | `REDIS_URL` |
| 5 | Function registry | `self.code_registry` | automatic (AutoAgent) |
| 6 | Kernel OODA loop | `Kernel` (AutoAgent internals) | automatic (AutoAgent) |
| 7 | Distributed workflow | `WorkflowEngine` | `REDIS_URL` |
| 7D | Nexus auth | `self._auth_manager` | `requires_auth=True` + `NEXUS_GATEWAY_URL` |
| 8 | Unified memory | `UnifiedMemory`, `EpisodicLedger`, `LTM` | `REDIS_URL` |
| 9 | Auto-injection | all of the above | automatic |

```python
class MyAgent(CustomAgent):
    requires_auth = True   # → self._auth_manager injected

    async def setup(self):
        await super().setup()
        # Phase 9: already injected — no __init__ wiring needed
        self.memory = UnifiedMemory(
            workflow_id="my-workflow", step_id="step-1",
            agent_id=self.role,
            redis_store=self._redis_store,    # Phase 9
            blob_storage=self._blob_storage,  # Phase 9
        )

    async def execute_task(self, task):
        # Phase 1: save artifact
        await self._blob_storage.save("results/output.json", json.dumps(result))

        # Phase 4: notify another agent
        self.mailbox.send(other_agent_id, {"event": "done", "workflow": "my-workflow"})

        # Phase 8: log to episodic ledger
        await self.memory.episodic.append({"event": "step_complete", "ts": time.time()})

        return {"status": "success", "output": result}
```

## Production Examples

All four examples require Redis (`docker compose -f docker-compose.infra.yml up -d`).

| Example | Mode | Profile | Phases exercised |
|---------|------|---------|-----------------|
| Ex1 — Financial Pipeline | autonomous | AutoAgent | 1, 3, 4, 5, 6, 8, 9 |
| Ex2 — Research Network (4 nodes) | distributed SWIM | AutoAgent | 4, 7, 8, 9 |
| Ex3 — Support Swarm | p2p | CustomAgent | 1, 4, 7D, 8, 9 |
| Ex4 — Content Pipeline | distributed | CustomAgent | 1, 4, 5, 7, 8, 9 |

```bash
# Ex1: Financial pipeline (single process)
python examples/ex1_financial_pipeline.py

# Ex2: 4-node distributed research network
python examples/ex2_synthesizer.py &       # Start seed first (port 7949)
python examples/ex2_research_node1.py &    # port 7946
python examples/ex2_research_node2.py &    # port 7947
python examples/ex2_research_node3.py &    # port 7948

# Ex3: Customer support swarm (P2P + optional Nexus auth)
python examples/ex3_support_swarm.py

# Ex4: Content pipeline with LTM (sequential, single process)
python examples/ex4_content_pipeline.py
```

## Profiles

| Profile | You Write | JarvisCore Handles |
|---------|-----------|-------------------|
| **AutoAgent** | System prompt (3 attributes) | LLM code generation, Kernel OODA loop, sandboxed execution, repair, function registry |
| **CustomAgent** | `on_peer_request()` and/or `execute_task()` | Mesh, discovery, routing, lifecycle, all Phase 1–9 infrastructure |

## Execution Modes

| Mode | Use Case |
|------|----------|
| `autonomous` | Single machine, LLM code generation (AutoAgent) |
| `p2p` | Agent-to-agent communication, swarms (CustomAgent) |
| `distributed` | Multi-node workflows + P2P + Redis crash recovery |

## Framework Integration

JarvisCore is **async-first**. Best experience with async frameworks.

| Framework | Integration |
|-----------|-------------|
| **FastAPI** | `JarvisLifespan` (3 lines) |
| **aiohttp, Quart, Tornado** | Manual lifecycle (see docs) |
| **Flask, Django** | Background thread pattern (see docs) |

## Documentation

**[https://prescott-data.github.io/jarviscore-framework/](https://prescott-data.github.io/jarviscore-framework/)**

| Guide | Description |
|-------|-------------|
| [Getting Started](https://prescott-data.github.io/jarviscore-framework/GETTING_STARTED/) | 5-minute quickstart |
| [AutoAgent Guide](https://prescott-data.github.io/jarviscore-framework/AUTOAGENT_GUIDE/) | LLM-powered agents, Kernel, distributed research network |
| [CustomAgent Guide](https://prescott-data.github.io/jarviscore-framework/CUSTOMAGENT_GUIDE/) | CustomAgent patterns, all phases, production example walkthroughs |
| [User Guide](https://prescott-data.github.io/jarviscore-framework/USER_GUIDE/) | Complete documentation including Infrastructure & Memory chapter |
| [API Reference](https://prescott-data.github.io/jarviscore-framework/API_REFERENCE/) | Detailed API docs including Phase 1–9 infrastructure classes |
| [Configuration](https://prescott-data.github.io/jarviscore-framework/CONFIGURATION/) | Settings reference with phase → env var mapping |
| [Troubleshooting](https://prescott-data.github.io/jarviscore-framework/TROUBLESHOOTING/) | Common issues and diagnostics |
| [Changelog](https://prescott-data.github.io/jarviscore-framework/CHANGELOG/) | Full release history |

Docs are also bundled with the package:

```bash
python -c "import jarviscore; print(jarviscore.__path__[0] + '/docs')"
```

## Version

**0.4.0**

## License

MIT License
