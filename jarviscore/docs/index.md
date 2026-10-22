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

<p class="jc-release"><span>New in 2.3</span> Multiplayer: a team and its agents on the same work, from Slack or your own product. <a href="guides/multiplayer-agents/">Build a multiplayer agent →</a></p>

## See it in two minutes

<div class="jc-video jc-video-home" data-yt="4IOpKZgjXIw" data-title="JarvisCore Demo"><a class="jc-video-poster" href="https://www.youtube.com/watch?v=4IOpKZgjXIw" target="_blank" rel="noopener" aria-label="Play the JarvisCore demo (2:07)"><img src="https://i.ytimg.com/vi/4IOpKZgjXIw/maxresdefault.jpg" alt="JarvisCore demo: an open-source runtime for AI agents that work as a mesh of equal peers" width="1280" height="720" loading="lazy"><span class="jc-video-play"></span></a></div>

<p class="jc-caption">Agents finding each other by capability, claiming steps from a shared ledger, and calling services through Nexus.</p>

## Quickstart

One LLM provider key is the only required configuration.

<div class="jc-split" markdown>
<div markdown>

```bash title="Install & initialise"
pip install jarviscore-framework
jarviscore init
cp .env.example .env   # add your LLM key
jarviscore check        # verify dependencies
```

Then run `main.py`. The answer comes back with the evidence behind it.

The [Getting Started](getting-started.md) guide walks through it, including what comes back and how to read it.

</div>
<div markdown>

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

</div>
</div>

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

<div class="jc-rows">
<a class="jc-row" href="https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/browse_a_whole_site.py" target="_blank" rel="noopener"><code>browse_a_whole_site.py</code><span>Reads every page of a catalogue in a real browser and computes the figures</span><small>browser extra</small></a>
<a class="jc-row" href="https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/analyst_that_computes.py" target="_blank" rel="noopener"><code>analyst_that_computes.py</code><span>Figures from a 400-row CSV, computed by code the agent writes and runs</span><small>model key</small></a>
<a class="jc-row" href="https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/agent_that_remembers.py" target="_blank" rel="noopener"><code>agent_that_remembers.py</code><span>Told once, recalled by a new process given nothing</span><small>model key</small></a>
<a class="jc-row" href="https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/survives_a_crash.py" target="_blank" rel="noopener"><code>survives_a_crash.py</code><span><code>kill -9</code> mid-workflow; the rerun finishes without repeating done work</span><small>Redis</small></a>
<a class="jc-row" href="https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/research_team.py" target="_blank" rel="noopener"><code>research_team.py</code><span>A scout and an analyst deliver a cited brief from the live web</span><small>model key</small></a>
</div>

## Community

<p class="jc-community">Questions, showcases and live office hours are on <a href="https://discord.gg/B2aJV5BJmb" target="_blank" rel="noopener">Discord</a>. Code and issues are on <a href="https://github.com/Prescott-Data/jarviscore-framework" target="_blank" rel="noopener">GitHub</a>, where a star helps other developers find JarvisCore. For the overview and blog, see the <a href="https://developers.prescottdata.io/jarviscore" target="_blank" rel="noopener">developer hub</a>; for teams, <a href="infrastructure/enterprise/">Enterprise</a> and <a href="https://developers.prescottdata.io/jarviscore/pricing" target="_blank" rel="noopener">pricing</a>.</p>
