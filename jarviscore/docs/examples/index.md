---
icon: material/book-open-variant
---

# Examples

Real, runnable programs that demonstrate JarvisCore in production-grade scenarios. Each example is a complete Python script (or multi-script cluster) in the [`examples/`](https://github.com/Prescott-Data/jarviscore-framework/tree/main/examples) directory of the repo — clone it, set up infra, and run.

## Prerequisites

All examples require Redis. Start it once before running any example:

```bash
docker compose -f docker-compose.infra.yml up -d  # Redis + optional infra
cp .env.example .env                               # then edit and set API keys
pip install -e ".[redis,prometheus]"
```

---

## All Examples

| Example | Profile | Infra | What it teaches |
|---------|---------|-------|-----------------|
| [Financial Pipeline](financial-pipeline.md) | `AutoAgent` | Redis | Workflow DAGs, crash recovery, blob storage |
| [Research Network](research-network.md) | `AutoAgent` | Redis + P2P | Multi-node SWIM clusters, capability-based dispatch |
| [Support Swarm](support-swarm.md) | `CustomAgent` | Redis + P2P | Mailbox routing, Nexus OSS OAuth, auth injection |
| [Content Pipeline](content-pipeline.md) | `CustomAgent` | Redis | Cross-step memory, LTM persistence, pure Python logic |
| [Investment Committee](investment-committee.md) | `AutoAgent` + `CustomAgent` | Redis | Mixed profiles, complex fan-in DAG, multi-agent deliberation |

---

## Choosing the Right Starting Point

=== "New to JarvisCore?"

    Start with **[Financial Pipeline](financial-pipeline.md)**. It's a single file, single process, and walks through the core concepts in order: define agents → build a mesh → run a workflow DAG.

=== "Building distributed systems?"

    Jump to **[Research Network](research-network.md)**. It shows how to run a multi-node cluster where each process contributes different capabilities and the mesh dispatches work automatically.

=== "Need P2P messaging?"

    **[Support Swarm](support-swarm.md)** demonstrates keyword-based routing via the mailbox system, SWIM peer discovery, and the Nexus OSS auth flow for external API calls.

=== "Want the full picture?"

    **[Investment Committee](investment-committee.md)** is the most advanced example — it mixes `AutoAgent` and `CustomAgent` profiles in a single mesh with a real multi-role deliberation pipeline.

---

## How the Mesh auto-detects infrastructure

```python
from jarviscore import Mesh

# The Mesh requires no mode= argument.
# It probes available infrastructure at start() and enables features accordingly.

mesh = Mesh()                        # Minimal — workflow engine only
mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})  # + Redis persistence
mesh = Mesh(config={"p2p_enabled": True})   # + SWIM discovery + ZMQ messaging

await mesh.start()

# Inspect what was detected
mesh.has_capability("redis")         # True when Redis is reachable
mesh.has_capability("peer_swim")     # True when P2P stack is active
mesh.has_capability("blob")          # True — LocalBlobStorage always available
mesh.has_capability("workflow")      # True — WorkflowEngine always enabled
```

> [!TIP]
> You can also set `REDIS_URL` and `P2P_ENABLED=true` in your `.env` file — the Mesh reads these automatically, so you don't need to pass them in the `config` dict.
