---
icon: material/home
---

<div class="jc-hero" markdown>

<img src="assets/combo-brand.svg" class="jc-hero-logo" alt="JarvisCore Logo" />

# Agents that survive production

Most frameworks get you a demo. JarvisCore gets you an operator: agents that run unattended for weeks, remember last month, fail loudly, and leave a flight record you can read. We run our own agents on it, with real budgets. Every hardening release comes from those scars.

<div class="jc-cta-text" markdown>
[Get started](getting-started.md) [Why JarvisCore](#why-jarviscore) [Reference](reference/configuration.md)
</div>

</div>

---

<div class="jc-stats" markdown>
<div class="jc-stat" markdown>
<span class="jc-stat-value">1 key</span>
<span class="jc-stat-label">To First Agent</span>
</div>
<div class="jc-stat" markdown>
<span class="jc-stat-value">0</span>
<span class="jc-stat-label">Silent Truncations</span>
</div>
<div class="jc-stat" markdown>
<span class="jc-stat-value">24/7</span>
<span class="jc-stat-label">Unattended Operation</span>
</div>
<div class="jc-stat" markdown>
<span class="jc-stat-value">46</span>
<span class="jc-stat-label">Service Integrations</span>
</div>
</div>

---

## Why JarvisCore

Built by running our own agents unattended, with real budgets. Four rules fell out of that, and they are enforced in code, not promised in prose:

- **Honest context.** Nothing is truncated silently. Clips are labeled, originals archived, summaries say what they summarize.
- **Loud failures.** Failed steps say so. Partial work survives. Rate-limit storms are absorbed, not crashed on.
- **Two profiles, no mushy middle.** `CustomAgent`: you bring the brain. `AutoAgent`: the full cognitive stack. It writes its own integrations, repairs them in a sandbox, and banks verified work for reuse.
- **No single point of death.** Agents coordinate over a SWIM gossip mesh. Memory compounds across sessions via Athena. Credentials stay out of agent reasoning via Nexus.

---

## What JarvisCore provides

<div class="jc-grid" markdown>
<div class="jc-card" markdown>
<span class="jc-card-label">Agent Profiles</span>

### Two execution models

`AutoAgent` runs a full cognitive loop internally: observe, orient, decide, act. `CustomAgent` exposes the execution loop directly for deterministic control. Both share the same infrastructure.
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Memory</span>

### Four-tier memory

Working scratchpad, episodic ledger, LLM-compressed long-term summaries, and optional cross-session semantic memory via Athena MemOS. Wired into AutoAgent automatically when `ATHENA_URL` is set. Context that survives restarts and compounds across weeks.
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Communication</span>

### Self-organising mesh

Agents discover and message each other via a `PeerClient` API over SWIM gossip and ZMQ. No central orchestrator to die: nodes join, fail, and rejoin. Identical code on a single process or across distributed machines.
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Integrations</span>

### 46 service integrations

Slack, GitHub, Zoom, SAP, NetSuite, MS Graph, Salesforce, and 40 more. 237+ prebuilt actions your agents can call directly. No glue code, no auth wiring.

[Browse integrations →](guides/integrations.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Auth</span>

### Nexus credential layer

Agents call third-party APIs without ever touching raw credentials. OAuth2, API keys, and basic auth are all managed by Nexus and kept out of agent reasoning.

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

1. [Getting Started](getting-started.md): install, configure, and run your first agent
2. [Architecture Overview](concepts/architecture.md): the mental model for how the framework fits together
3. [Agents](concepts/agents.md): what an agent is, its identity and lifecycle
4. [Language Models](concepts/language-models.md): how JarvisCore uses multiple LLMs simultaneously
5. [Memory](concepts/memory.md): how agents maintain and recover context
6. [Agent Personas](concepts/agent-personas.md): how profiles shape autonomous behaviour

If you are evaluating for a specific use case:

- [AutoAgent Guide](guides/autoagent.md): autonomous reasoning agents
- [CustomAgent Guide](guides/customagent.md): deterministic worker agents
- [System Bundles & Integrations](guides/integrations.md): the full atom catalog
- [Configuration Reference](reference/configuration.md): all environment variables
- [JarvisCore Enterprise](infrastructure/enterprise.md): managed deployment and SLAs

---

## Explore the ecosystem

| | |
|---|---|
| **Reference** | Full API surface, configuration keys, and CLI flags: [view reference](reference/configuration.md) |
| **Source** | Browse the code, open issues, and submit PRs: [GitHub](https://github.com/Prescott-Data/jarviscore-framework){ target="_blank" rel="noopener" } |
| **Community** | Questions, showcases, and early feature previews: [Discord](https://discord.gg/jarviscore){ target="_blank" rel="noopener" } |
| **Blog** | Engineering deep-dives and architecture walkthroughs: [read the blog](https://developers.prescottdata.io/blog){ target="_blank" rel="noopener" } |

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
