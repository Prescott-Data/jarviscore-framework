---
icon: material/robot-outline
---

# Agents

An agent in JarvisCore is a Python class with two things: an **identity** and an **execution model**. The identity tells the mesh *who* the agent is and *what* it can do. The execution model defines *how* it processes work.

Every other concept in the framework — memory, model routing, personas, peer communication — operates on top of this foundation. Read this page before any of the others.

---

## Identity

Agent identity is defined by class attributes set directly on the class body. The framework reads them at startup; you do not pass them as constructor arguments.

```python title="agents/researcher.py"
from jarviscore import AutoAgent

class ResearcherAgent(AutoAgent):
    name         = "Researcher"
    role         = "researcher"
    description  = "Synthesises web research into structured intelligence reports."
    capabilities = ["research", "synthesis", "web-search"]
    system_prompt = """
    You are a rigorous research analyst. Prioritise primary sources,
    cross-reference findings, and structure outputs as actionable intelligence.
    Always store your final output in a variable named `result`.
    """
```

The framework raises `ValueError` at startup if `role`, `capabilities`, or `system_prompt` are absent.

### Identity attributes

| Attribute | Required | What it does |
|---|---|---|
| `role` | Yes | The agent's role slug. Used as the lookup key for peer discovery, profile loading, and workflow routing. Must be unique within a mesh. |
| `capabilities` | Yes | A list of capability tags. Other agents use these for capability-based discovery (`peers.discover(capability="research")`). |
| `system_prompt` | Yes (AutoAgent) | The base LLM instruction set for every task this agent handles. |
| `name` | No | Human-readable display name shown in traces and dashboards. Defaults to the class name. |
| `description` | No | One-sentence purpose statement used by peer agents when making routing decisions. |

### Agent ID

Every agent instance is assigned a unique `agent_id` at construction time:

```
agent_id = f"{role}-{uuid4().hex[:8]}"
# e.g.  researcher-a3f2b1c9
```

You can override it by passing `agent_id=` to the constructor, but this is rarely needed. The `agent_id` is what appears in trace events, Redis keys, and P2P membership tables. The `role` is what peers use to discover and address messages.

---

## The Two Execution Models

The `role` and `capabilities` are common to all agents. What differs is how each agent processes work. JarvisCore provides two execution model profiles that sit between the `Agent` base class and your code.

### AutoAgent

`AutoAgent` gives the agent an internal OODA reasoning loop. You provide the system prompt and optional configuration; the framework handles the rest — LLM calls, tool selection, code generation, web search, sandboxed execution, autonomous repair, and replanning.

```python
class ResearcherAgent(AutoAgent):
    role         = "researcher"
    capabilities = ["research", "synthesis"]
    system_prompt = "You are a research analyst. Store results in `result`."
```

The Kernel inside `AutoAgent` decides which sub-agent to route each task to (Coder, Researcher, Communicator, or Browser), executes it through the OODA loop, and returns a structured result. You do not write the execution logic.

Use `AutoAgent` when the steps needed to complete a task are not known in advance — when the agent needs to reason about what to do next.

### CustomAgent

`CustomAgent` exposes the execution loop directly. You implement `on_peer_request()` (for P2P messages) and optionally `execute_task()` (for workflow tasks). The framework still provides memory, peer communication, and credential injection — you control what runs.

```python
from jarviscore import CustomAgent

class DataTransformerAgent(CustomAgent):
    role         = "transformer"
    capabilities = ["etl", "normalisation"]

    async def on_peer_request(self, msg):
        data   = msg.data["payload"]
        result = await self.normalise(data)
        return {"status": "success", "result": result}
```

Use `CustomAgent` when the execution sequence is deterministic and known in advance — pipelines, formatters, gateways, or wrappers around existing code.

---

## Lifecycle

Every agent goes through the same lifecycle regardless of execution model:

```
Mesh.add(AgentClass)
    │
    ▼
Mesh.start()
    ├── Agent.__init__()              # role, capabilities validated; agent_id assigned
    ├── Agent.setup()                 # infrastructure injected; one-time init runs
    │       ├── self._redis_store     # injected when REDIS_URL is set
    │       ├── self._blob_storage    # always injected (local filesystem default)
    │       ├── self.peers            # injected when P2P_ENABLED=true
    │       ├── self.mailbox          # injected when REDIS_URL is set
    │       └── self._auth_manager   # injected when requires_auth=True + NEXUS_GATEWAY_URL set
    │
    ▼
Running — processes tasks and/or peer messages
    │
    ▼
Mesh.stop()
    └── Agent.teardown()             # release resources, close connections
```

Override `setup()` for one-time initialisation and `teardown()` for cleanup:

```python
async def setup(self):
    await super().setup()            # always call super first
    self.db = await MyDB.connect()

async def teardown(self):
    await self.db.close()
    await super().teardown()         # always call super last
```

Do not do expensive work in `__init__` — the Mesh injects infrastructure *after* construction and *before* `setup()`. Anything that requires `self._redis_store` or `self.peers` belongs in `setup()`.

---

## Infrastructure Injection

The Mesh injects infrastructure stores into every agent between `__init__` and `setup()`. They are available inside `setup()` and all subsequent method calls.

| Attribute | Type | Available when |
|---|---|---|
| `self._redis_store` | `RedisStore` | `REDIS_URL` is set |
| `self._blob_storage` | `BlobStorage` | Always — local filesystem by default |
| `self.peers` | `PeerClient` | `P2P_ENABLED=true` |
| `self.mailbox` | `MailboxManager` | `REDIS_URL` is set |
| `self._auth_manager` | `AuthenticationManager` | `requires_auth = True` on the class and `NEXUS_GATEWAY_URL` is set |
| `self._athena_client` | `AthenaClient` | `ATHENA_URL` is set |

None of these are required. Every injected attribute is `None` when its infrastructure is not configured. Always guard with `if self._redis_store:` before accessing optional infrastructure.

---

## How Identity Drives Everything

The `role` and `capabilities` you set on the class are not just labels — they actively control how the framework routes and connects your agent.

| What it controls | Driven by |
|---|---|
| Peer discovery (`peers.get_peer(role="analyst")`) | `role` |
| Capability-based routing (`peers.discover(capability="research")`) | `capabilities` |
| YAML profile loading (expertise, SOPs, escalation targets) | `role` |
| Model tier selection (coder → `CODING_MODEL`, others → `TASK_MODEL_*`) | `role` |
| Workflow step routing (`{"agent": "researcher", "task": "..."}`) | `role` |
| HITL escalation targets | Defined in the agent's YAML profile |

The `role` is the primary key for the entire mesh. Choose it deliberately — it should be a stable slug that reflects the agent's function, not its implementation.

---

## Containerised Deployment

For distributed deployments where each container runs a single agent, agents can join an existing mesh without a central `Mesh()` orchestrator:

```python title="entrypoint.py"
import asyncio
from agents import ProcessorAgent

async def main():
    agent = ProcessorAgent()
    await agent.join_mesh()          # discovers peers via JARVISCORE_SEED_NODES
    await agent.run_standalone()     # blocks until shutdown signal, leaves mesh on exit

asyncio.run(main())
```

`join_mesh()` reads `JARVISCORE_MESH_ENDPOINT` or `JARVISCORE_SEED_NODES` from the environment, starts a SWIM gossip node, and announces the agent's capabilities to the mesh. `run_standalone()` calls `run()` and ensures `leave_mesh()` is called on exit regardless of how the process terminates.

---

## Further Reading

- [Architecture Overview](./architecture.md) — the Mesh, Kernel, and OODA loop
- [Agent Personas](./agent-personas.md) — how YAML profiles add domain intelligence to identity
- [Model Routing](./model-routing.md) — how `role` determines which LLM tier is used
- [P2P Communication](./p2p.md) — how agents discover and message each other
- [AutoAgent Guide](../guides/autoagent.md) — full reference for autonomous reasoning agents
- [CustomAgent Guide](../guides/customagent.md) — full reference for deterministic worker agents
