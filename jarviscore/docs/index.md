---
icon: material/home
---

<div class="jc-hero" markdown>

<img src="assets/combo-brand.svg" class="jc-hero-logo" alt="JarvisCore Logo" />

# Build autonomous multi-agent systems

JarvisCore is a Python framework for production multi-agent AI. Peer-to-peer coordination, composable memory, 19 built-in integration bundles, and full observability — from a single agent to a fleet.

<div class="jc-cta-text" markdown>
[Get started](getting-started.md) [Reference](reference/configuration.md) [View Changelog](CHANGELOG.md)
</div>

</div>

---

<div class="jc-stats" markdown>
<div class="jc-stat" markdown>
<span class="jc-stat-value">46</span>
<span class="jc-stat-label">Service Integrations</span>
</div>
<div class="jc-stat" markdown>
<span class="jc-stat-value">237+</span>
<span class="jc-stat-label">Prebuilt Actions</span>
</div>
<div class="jc-stat" markdown>
<span class="jc-stat-value">4-tier</span>
<span class="jc-stat-label">Agent Memory</span>
</div>
<div class="jc-stat" markdown>
<span class="jc-stat-value">P2P</span>
<span class="jc-stat-label">Agent Mesh</span>
</div>
</div>

---

## What JarvisCore provides

<div class="jc-grid" markdown>
<div class="jc-card" markdown>
<span class="jc-card-label">Agent Profiles</span>

### Two execution models

`AutoAgent` runs a full OODA loop internally — observe, orient, decide, act. `CustomAgent` exposes the execution loop directly for deterministic control. Both share the same infrastructure.
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Memory</span>

### Four-tier memory

Working scratchpad → episodic ledger → LLM-compressed long-term summaries → optional cross-session semantic memory via Athena MemOS. Context that survives restarts, scales across steps.
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Communication</span>

### Peer-to-peer mesh

Agents discover and message each other via a `PeerClient` API. Routing, request-response, and broadcast work identically on a single process or across distributed machines.
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Integrations</span>

### 46 service integrations

Slack, GitHub, Zoom, SAP, NetSuite, MS Graph, Salesforce, and 40 more. 237+ prebuilt actions your agents can call directly — no glue code, no auth wiring.

[Browse integrations →](guides/integrations.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Auth</span>

### Nexus credential layer

Agents call third-party APIs without ever touching raw credentials. OAuth2, API keys, and basic auth — all managed by Nexus and kept out of agent reasoning.

[Nexus guide →](guides/nexus.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Observability</span>

### Full-stack tracing

Every agent turn, tool call, and LLM request is traced automatically. Redis PubSub for live streams, JSONL for compliance, Prometheus for operational dashboards.

[Observability guide →](guides/observability.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Control</span>

### Human-in-the-loop

`HITLQueue` intercepts decisions that exceed confidence thresholds, routes them to a review inbox, and resumes execution once a human responds. First-class, not an afterthought.

[HITL guide →](guides/hitl.md)
</div>
</div>

---

## Quickstart

```bash title="Install & initialise"
pip install jarviscore-framework
jarviscore init
cp .env.example .env   # add your LLM key
jarviscore check        # verify dependencies
```

```python title="main.py"
import asyncio
from jarviscore import Mesh, AutoAgent


class ResearcherAgent(AutoAgent):
    name = "Researcher"
    role = "researcher"
    system_prompt = "You are a rigorous research analyst."


async def main():
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    await mesh.start()
    result = await mesh.run_task(
        agent="researcher",
        task="What are the key architectural trade-offs in multi-agent systems?",
    )
    print(result)


asyncio.run(main())
```

---

## Where to start

If you are new to JarvisCore, read in this order:

1. [Getting Started](getting-started.md) — install, configure, and run your first agent
2. [Architecture Overview](concepts/architecture.md) — the mental model for how the framework fits together
3. [Agents](concepts/agents.md) — what an agent is, its identity and lifecycle
4. [Language Models](concepts/language-models.md) — how JarvisCore uses multiple LLMs simultaneously
5. [Memory](concepts/memory.md) — how agents maintain and recover context
6. [Agent Personas](concepts/agent-personas.md) — how profiles shape autonomous behaviour

If you are evaluating for a specific use case:

- [AutoAgent Guide](guides/autoagent.md) — autonomous reasoning agents
- [CustomAgent Guide](guides/customagent.md) — deterministic worker agents
- [System Bundles & Integrations](guides/integrations.md) — the full atom catalog
- [Configuration Reference](reference/configuration.md) — all environment variables
- [JarvisCore Enterprise](infrastructure/enterprise.md) — managed deployment and SLAs

---

## Explore the ecosystem

| | |
|---|---|
| **Reference** | Full API surface, configuration keys, and CLI flags — [view reference](reference/configuration.md) |
| **Source** | Browse the code, open issues, and submit PRs — [GitHub](https://github.com/Prescott-Data/jarviscore-framework){ target="_blank" rel="noopener" } |
| **Community** | Questions, showcases, and early feature previews — [Discord](https://discord.gg/jarviscore){ target="_blank" rel="noopener" } |
| **Blog** | Engineering deep-dives and architecture walkthroughs — [read the blog](https://developers.prescottdata.io/blog){ target="_blank" rel="noopener" } |

---

<div class="jc-ecosystem" markdown>
<div class="jc-ecosystem-card" markdown>

### Star us on GitHub

Help more developers discover JarvisCore. Every star makes us easier to find and keeps the project growing.

<div class="jc-cta" markdown>
[Star on GitHub](https://github.com/Prescott-Data/jarviscore-framework){ .jc-btn .jc-btn-github target="_blank" rel="noopener" }
</div>

</div>
<div class="jc-ecosystem-card" markdown>

### Join the community

Ask questions, share what you're building, and get early previews of new features. Come say hi.

<div class="jc-cta" markdown>
[Join Discord](https://discord.gg/jarviscore){ .jc-btn .jc-btn-discord target="_blank" rel="noopener" }
</div>

</div>
</div>
