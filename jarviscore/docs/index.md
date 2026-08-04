---
icon: material/home
---

<div class="jc-hero" markdown>

<img src="assets/combo-brand.svg" class="jc-hero-logo" alt="JarvisCore Logo" />

# Agents that survive production

Most frameworks get you a demo. JarvisCore gets you an operator: agents that run unattended for weeks, remember last month, fail loudly, and leave a flight record you can read. We run our own agents on it with real budgets, and every hardening release comes from those scars.

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

Agent frameworks fail in the same three places. We built against all three.

**Your agent should never lie to itself.** When context fills up, most frameworks quietly drop things: old turns, the middle of a tool result, half a summary. The agent then reasons from evidence it does not know is missing. Our rule: truncation is lossiness, not compression. Clips are labeled, originals are archived with a retrieval path, summaries say what they summarize.

**Failures must be loud.** Failed steps say so. Evaluators see full evidence before passing a verdict. Partial work survives a failed goal. Rate-limit storms are absorbed with jittered backoff instead of crashing the loop. When something breaks, the record shows where.

**Autonomy is a spectrum.** Two profiles, nothing in between. CustomAgent is a thin infrastructure shell: you bring the brain, you keep deterministic control. AutoAgent is the full cognitive stack: classification, typed routing, specialist sub-agents, sandboxed code generation with self-repair, and a registry where verified work graduates for reuse. Pick your point per agent, not per framework.

Underneath sit structural choices no glue layer gives you:

- **Self-organising mesh.** Agents discover each other over SWIM gossip with ZMQ transport. No central orchestrator to die. The same PeerClient code runs in one process or across a fleet.
- **Memory that compounds.** Set `ATHENA_URL` and every agent gains a fourth memory tier: cross-session, semantic, consolidated over time. The agent you run in week six works from what it learned in week one. Without it, three in-process tiers still cover working, episodic, and long-term context.
- **Agents that write their own integrations.** When AutoAgent lacks a capability, it writes the code, runs it in a sandbox, repairs it until it passes, and files it in a registry: candidate, verified, golden. Your agents grow a tool catalog instead of consuming one.
- **Zero-trust credentials.** With Nexus, agents never see a raw secret. Prompt injection cannot exfiltrate what the agent never had.

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
