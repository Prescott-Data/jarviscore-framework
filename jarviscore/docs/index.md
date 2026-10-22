---
icon: material/home
hide:
  - navigation
  - toc
title: Python Multi-Agent AI Framework for Production
description: Open source Python framework for autonomous multi-agent systems with peer-to-peer orchestration, durable memory, zero-trust credentials, and observability.
videos:
  - id: 4IOpKZgjXIw
    name: "JarvisCore Demo"
    description: "Agents on JarvisCore work as a fleet of equal peers: they discover one another by capability, execute tasks from a shared ledger, and reach every external service through a zero-trust broker, never with their own keys."
    upload_date: "2026-10-02T03:11:50-07:00"
    duration: PT2M7S
---

<div class="jc-hero" markdown>

<img src="assets/combo-brand.svg" class="jc-hero-logo" alt="JarvisCore Logo" />

# JarvisCore Documentation

JarvisCore is a runtime where AI agents operate as a fleet of equal peers. Agents discover one another by capability, execute tasks from a shared ledger, and authenticate to every external service through a zero-trust broker, never with their own keys.

<div class="jc-cta-text" markdown>
[Get started](getting-started.md) [Concepts](concepts/index.md) [Reference](reference/configuration.md)
</div>

</div>

---

## See it in two minutes

<div class="jc-video" data-yt="4IOpKZgjXIw" data-title="JarvisCore Demo"><a class="jc-video-poster" href="https://www.youtube.com/watch?v=4IOpKZgjXIw" target="_blank" rel="noopener" aria-label="Play the JarvisCore demo (2:07)"><img src="https://i.ytimg.com/vi/4IOpKZgjXIw/maxresdefault.jpg" alt="JarvisCore demo: an open-source runtime for AI agents that work as a mesh of equal peers" width="1280" height="720" loading="lazy"><span class="jc-video-play"></span></a></div>

A real mesh at work: agents finding each other, claiming steps from the ledger, and calling services through Nexus.

---

## Quickstart

One LLM provider key is the only required configuration:

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
    role = "researcher"
    capabilities = ["research", "analysis"]
    system_prompt = "You are a rigorous research analyst."


async def main():
    mesh = Mesh()
    mesh.add(ResearcherAgent)
    await mesh.start()
    try:
        result = await mesh.run_task(
            agent="researcher",
            task="What are the main trade-offs in multi-agent design?",
        )
        print(result["result_summary"])   # the answer
        print(result["evidence"])         # what it read and produced
    finally:
        await mesh.stop()


asyncio.run(main())
```

The [Getting Started](getting-started.md) guide walks through it, including what comes back and how to read it.

!!! tip "New in 2.3: multiplayer"
    A team and its agents can now work on the same files from Slack or your own product: people ask in their own words, agents propose changes, and people accept them as themselves. Start with [Build a Multiplayer Agent](guides/multiplayer-agents.md), or read the [concept](concepts/multiplayer.md) first. Everything else that changed is in the [changelog](changelog.md).

---

## Find your way

<div class="jc-grid" markdown>
<div class="jc-card" markdown>
<span class="jc-card-label">Start</span>

### Getting Started

Install, add one model key, and run your first agent. About five minutes.

[Get started →](getting-started.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Understand</span>

### Concepts

Agents, the Kernel, memory, the mesh, Nexus and multiplayer: the mental model behind everything else.

[Read the concepts →](concepts/index.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Build</span>

### Guides

AutoAgent and CustomAgent, workflows, browser, search, credentials, people in the loop, testing and production.

[Browse the guides →](guides/index.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Look up</span>

### Reference

Every setting, the agent and execution APIs, the CLI, and troubleshooting.

[Open the reference →](reference/index.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Compare</span>

### Coming from another framework

How JarvisCore differs from CrewAI, LangGraph and Hermes Agent, and how to migrate.

[Compare frameworks →](compare/index.md)
</div>

<div class="jc-card" markdown>
<span class="jc-card-label">Integrations</span>

### System bundles and atoms

Prebuilt actions for the services your agents use. List the catalog in your installed version with [`jarviscore atom list`](reference/cli.md#atom-list).

[Browse integrations →](guides/integrations.md)
</div>
</div>

---

## Run the examples

Each is one short file in [`examples/showcase`](https://github.com/Prescott-Data/jarviscore-framework/tree/main/examples/showcase){ target="_blank" rel="noopener" }, verified on a real model.

| Example | What it shows | Needs |
|---|---|---|
| [`browse_a_whole_site.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/browse_a_whole_site.py){ target="_blank" rel="noopener" } | An agent reads every page of a catalogue in a real browser and computes the figures | `jarviscore-framework[browser]`, `BROWSER_ENABLED=true` |
| [`analyst_that_computes.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/analyst_that_computes.py){ target="_blank" rel="noopener" } | Figures from a 400-row CSV, computed by code the agent writes and runs | A model key |
| [`agent_that_remembers.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/agent_that_remembers.py){ target="_blank" rel="noopener" } | Told once, recalled by a new process given nothing | A model key |
| [`survives_a_crash.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/survives_a_crash.py){ target="_blank" rel="noopener" } | `kill -9` mid-workflow; the rerun finishes without repeating done work | `REDIS_URL` |
| [`research_team.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/research_team.py){ target="_blank" rel="noopener" } | A scout and an analyst deliver a cited brief from the live web | A model key; a [search provider](guides/internet-search.md) key widens results |

Longer, multi-agent examples are in [Examples](examples/index.md).

---

## More from Prescott Data

| | |
|---|---|
| **Overview and blog** | What JarvisCore is for, release stories and engineering posts: [developers.prescottdata.io/jarviscore](https://developers.prescottdata.io/jarviscore){ target="_blank" rel="noopener" } |
| **Enterprise** | Agent identity, delegated access, cost efficiency and support: [Enterprise docs](infrastructure/enterprise.md) and [pricing](https://developers.prescottdata.io/jarviscore/pricing){ target="_blank" rel="noopener" } |
| **Source** | Code, issues and pull requests: [GitHub](https://github.com/Prescott-Data/jarviscore-framework){ target="_blank" rel="noopener" } |

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
[Join Discord](https://discord.gg/B2aJV5BJmb){ .jc-btn .jc-btn-discord target="_blank" rel="noopener" }
</div>

</div>
</div>
