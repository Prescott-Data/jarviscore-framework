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

!!! tip "New in 2.3: multiplayer"
    A team and its agents can now work on the same files from Slack or your own product: people ask in their own words, agents propose changes, and people accept them as themselves. Start with [Build a Multiplayer Agent](guides/multiplayer-agents.md), or read the [concept](concepts/multiplayer.md) first. Everything else that changed is in the [changelog](changelog.md).

## See it in two minutes

<div class="jc-video jc-video-home" data-yt="4IOpKZgjXIw" data-title="JarvisCore Demo"><a class="jc-video-poster" href="https://www.youtube.com/watch?v=4IOpKZgjXIw" target="_blank" rel="noopener" aria-label="Play the JarvisCore demo (2:07)"><img src="https://i.ytimg.com/vi/4IOpKZgjXIw/maxresdefault.jpg" alt="JarvisCore demo: an open-source runtime for AI agents that work as a mesh of equal peers" width="1280" height="720" loading="lazy"><span class="jc-video-play"></span></a></div>

<p class="jc-caption">Agents finding each other by capability, claiming steps from a shared ledger, and calling services through Nexus.</p>

## Quickstart

One LLM provider key is the only required configuration.

```bash title="Install & initialise"
pip install jarviscore-framework
jarviscore init
cp .env.example .env   # add your LLM key
jarviscore check        # verify dependencies
```

The [Getting Started](getting-started.md) guide takes it from here: your first agent, what comes back, and how to read it.

## Explore the docs

<div class="jc-tiles" markdown>

<a class="jc-tile" href="getting-started/">:material-rocket-launch-outline:<strong>Getting Started</strong><span>Install, add one model key, and run your first agent.</span></a>

<a class="jc-tile" href="concepts/">:material-cube-outline:<strong>Concepts</strong><span>Agents, the Kernel, memory, the mesh, Nexus and multiplayer.</span></a>

<a class="jc-tile" href="guides/">:material-map-marker-path:<strong>Guides</strong><span>Workflows, browser, search, credentials, people in the loop, production.</span></a>

<a class="jc-tile" href="reference/">:material-code-braces:<strong>Reference</strong><span>Every setting, the APIs, the CLI and troubleshooting.</span></a>

<a class="jc-tile" href="compare/">:material-scale-balance:<strong>Compare</strong><span>How JarvisCore differs from CrewAI, LangGraph and Hermes Agent.</span></a>

<a class="jc-tile" href="guides/integrations/">:material-puzzle-outline:<strong>Integrations</strong><span>Prebuilt actions for the services your agents use.</span></a>

</div>

The integration catalog for your installed version is one command away: [`jarviscore atom list`](reference/cli.md#atom-list).

## Run the examples

Each is one short file in [`examples/showcase`](https://github.com/Prescott-Data/jarviscore-framework/tree/main/examples/showcase){ target="_blank" rel="noopener" }, verified on a real model. Longer, multi-agent examples are in [Examples](examples/index.md).

| Example | What it shows | Needs |
|---|---|---|
| [Read a whole website](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/browse_a_whole_site.py){ target="_blank" rel="noopener" } | An agent works a real browser through every page of a catalogue and computes the figures. | `jarviscore-framework[browser]` |
| [Compute, never estimate](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/analyst_that_computes.py){ target="_blank" rel="noopener" } | Figures from a 400-row CSV, computed by code the agent writes and runs. | A model key |
| [Remember across runs](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/agent_that_remembers.py){ target="_blank" rel="noopener" } | Told once; a new process, given nothing, still knows. | A model key |
| [Survive kill -9](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/survives_a_crash.py){ target="_blank" rel="noopener" } | Kill it mid-workflow; the rerun finishes without repeating done work. | `REDIS_URL` |
| [A research team](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/research_team.py){ target="_blank" rel="noopener" } | A scout and an analyst deliver a cited brief from the live web. | A model key |
| [Work as a team](guides/multiplayer-agents.md) | A room in Slack where people ask, agents propose, and people decide. | New in 2.3 |

## Community

<p class="jc-community">Questions, showcases and live office hours are on <a href="https://discord.gg/B2aJV5BJmb" target="_blank" rel="noopener">Discord</a>. Code and issues are on <a href="https://github.com/Prescott-Data/jarviscore-framework" target="_blank" rel="noopener">GitHub</a>, where a star helps other developers find JarvisCore. For the overview and blog, see the <a href="https://developers.prescottdata.io/jarviscore" target="_blank" rel="noopener">developer hub</a>; for teams, <a href="infrastructure/enterprise/">Enterprise</a> and <a href="https://developers.prescottdata.io/jarviscore/pricing" target="_blank" rel="noopener">pricing</a>.</p>
