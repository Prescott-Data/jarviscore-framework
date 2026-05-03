---
icon: material/magnify
---

# Distributed Research Network

[:fontawesome-brands-github: View full source](https://github.com/Prescott-Data/jarviscore-framework/tree/main/examples){ .md-button }

| | |
|---|---|
| **Profile** | `AutoAgent` |
| **Infra required** | Redis + P2P (`p2p_enabled: True`) |
| **Processes** | 4 terminals (1 synthesizer + 3 research nodes) |
| **Run** | See run order below |

---

## What it does

A four-node cluster where each process runs a single specialist researcher. The `Synthesizer` acts as the workflow coordinator and SWIM seed — it submits a 4-step research workflow to Redis and then all nodes race to claim matching steps based on their declared `capabilities`.

```
Terminal A: Synthesizer    → Submits workflow, waits for results
Terminal B: Node 1         → tech_researcher      claims "tech" step
Terminal C: Node 2         → market_researcher    claims "market" step  
Terminal D: Node 3         → policy_researcher    claims "policy" step
                           → Synthesizer also claims "synthesize" step
```

No manual wiring. Each node declares its capabilities and the mesh's distributed worker loop atomically claims matching pending steps from Redis.

---

## Run order

```bash
# Terminal A — start synthesizer FIRST (it is the SWIM seed)
python examples/ex2_synthesizer.py

# Then start nodes in any order
python examples/ex2_research_node1.py   # Terminal B
python examples/ex2_research_node2.py   # Terminal C  
python examples/ex2_research_node3.py   # Terminal D
```

Wait for the synthesizer to print `Research synthesis complete`.

---

## Key pattern: P2P mesh setup

```python
from jarviscore import Mesh

# On the synthesizer / coordinator node
mesh = Mesh(config={
    "redis_url": REDIS_URL,
    "p2p_enabled": True,        # (1)! enables SWIM discovery + ZMQ messaging
})
mesh.add(SynthesizerAgent)
await mesh.start()

# Check what the Mesh detected
print(mesh.has_capability("redis"))         # True — Redis connected
print(mesh.has_capability("peer_swim"))     # True — SWIM/ZMQ active
```

1. Set `p2p_enabled: True` (or `P2P_ENABLED=true` in `.env`) to activate the SWIM peer transport. The Mesh detects Redis automatically from `REDIS_URL`.

---

## Key pattern: capability-based dispatch

```python
class TechResearchAgent(AutoAgent):
    role = "tech_researcher"
    capabilities = ["tech_research", "ai_hardware", "research"]  # (1)!
    system_prompt = "..."

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id="ai-landscape-q1",
            step_id="tech",       # (2)!
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
```

1. The distributed worker loop scans for pending workflow steps whose `agent` field matches any string in `capabilities`. No explicit routing needed.
2. `step_id` must match the `id` field in the workflow definition — this is how the worker claims the step atomically via Redis `SETNX`.

---

## Key pattern: node mesh config

Each node connects via the synthesizer's address as the SWIM seed:

```python
mesh = Mesh(config={
    "redis_url": REDIS_URL,
    "p2p_enabled": True,
    "bind_host": "127.0.0.1",
    "bind_port": 7946,                   # unique per node
    "seed_nodes": "127.0.0.1:7949",      # synthesizer address
    "node_name": "research-node-1",
})
mesh.add(TechResearchAgent)
await mesh.start()  # (1)!
```

1. `mesh.start()` joins the SWIM ring, injects `_redis_store` / `_blob_storage` / `mailbox` into every registered agent, calls each agent's `setup()`, then starts the distributed worker loop.

---

## Success criteria

- [ ] Synthesizer prints `mesh stabilised, peers=3` (or similar)
- [ ] Each node claims and completes its assigned step
- [ ] Synthesizer receives all 3 research outputs and synthesizes them
- [ ] Final report printed to console by the synthesizer
