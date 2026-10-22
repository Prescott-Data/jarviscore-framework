---
icon: material/home
title: "JarvisCore: Open Source Python Framework for AI Agents"
description: "Python framework for AI agents that browse, run code, remember and survive crashes, with evidence for every answer. Multi-agent, multiplayer, Apache 2.0."
hide:
  - navigation
  - toc
videos:
  - id: 4IOpKZgjXIw
    name: "JarvisCore Demo"
    description: "Agents on JarvisCore work as a fleet of equal peers: they discover one another by capability, execute tasks from a shared ledger, and reach every external service through a zero-trust broker, never with their own keys."
    upload_date: "2026-10-02T03:11:50-07:00"
    duration: PT2M7S
---

<section class="jcx-hero" markdown>
<div class="jcx-hero-copy" markdown>

<span class="jcx-eyebrow">Open source · Apache 2.0 · Python 3.10+</span>

<h1>Describe an agent.<br><span class="jcx-grad">It does the work.</span></h1>

<p class="jcx-lede">JarvisCore is a Python runtime for AI agents that act. They read the live web, run code in a sandbox, work a browser, remember what they were told, and pick up where they left off after <code>kill -9</code>. Every answer comes back with the evidence behind it.</p>

<div class="jcx-actions">
<a class="jcx-btn jcx-btn-primary" href="getting-started/">Build your first agent →</a>
<a class="jcx-btn jcx-btn-ghost" href="#see-it-work">See it work</a>
<a class="jcx-btn jcx-btn-ghost" href="https://github.com/Prescott-Data/jarviscore-framework" target="_blank" rel="noopener">GitHub</a>
</div>

<div class="jcx-install"><span>$</span>pip install jarviscore-framework</div>

</div>
<div class="jcx-hero-media">
<div class="jcx-video" data-yt="4IOpKZgjXIw" data-title="JarvisCore Demo">
<a class="jcx-video-poster" href="https://www.youtube.com/watch?v=4IOpKZgjXIw" target="_blank" rel="noopener" aria-label="Play the JarvisCore demo, 2 minutes">
<img src="https://i.ytimg.com/vi/4IOpKZgjXIw/maxresdefault.jpg" alt="JarvisCore demo: an open-source runtime for AI agents that work as a mesh of equal peers" width="1280" height="720" fetchpriority="high">
<span class="jcx-play"></span>
</a>
<div class="jcx-video-meta"><span>▶ Demo</span><span>2:07</span></div>
</div>
</div>
</section>

<div class="jcx-proof" markdown>
<div markdown>:material-check-decagram:{ .lg }<strong>Answers with evidence</strong><span>The answer, what each tool actually saw, and an honest status.</span></div>
<div markdown>:material-restart:{ .lg }<strong>Survives kill -9</strong><span>Finished steps come back; only unfinished work runs again.</span></div>
<div markdown>:material-brain:{ .lg }<strong>Remembers across runs</strong><span>Tell it once. A new process, given nothing, still knows.</span></div>
<div markdown>:material-key-chain:{ .lg }<strong>No keys in prompts</strong><span>Credentials are placed at the call, never in the model's context.</span></div>
<div markdown>:material-account-check:{ .lg }<strong>People approve</strong><span>Anything irreversible waits for the person it affects.</span></div>
</div>

<section class="jcx-section jcx-showcase" id="see-it-work" markdown>

<span class="jcx-kicker">See it work</span>

## Real runs, not slideware

<p class="jcx-sub">Each of these is a short Python file in <a href="https://github.com/Prescott-Data/jarviscore-framework/tree/main/examples/showcase" target="_blank" rel="noopener">examples/showcase</a>, recorded on a real model with idle time trimmed. Run them yourself.</p>

=== "A research team"

    <div class="jcx-demo" markdown>
    <div class="jcx-window"><div class="jcx-window-bar"><i></i><i></i><i></i>JarvisCore Desk · research mesh</div><video src="assets/readme/desk-research-team.mp4" autoplay muted loop playsinline preload="none" aria-label="Three agents on one mesh in the JarvisCore Desk: a scout reads official docs on the live web, an analyst compares the options, and a writer delivers a decision brief with its sources."></video></div>
    <div markdown>

    ### Three agents, one mesh, a cited brief

    A scout reads official docs on the live web, an analyst compares the options on that evidence alone, and a writer delivers a decision brief with every source linked. The whole team is about 30 lines of Python.

    <div class="jcx-chips"><span>3 agents</span><span>live web</span><span>sources cited</span></div>

    [Read the code →](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/desk/research_desk.py){ target="_blank" rel="noopener" }

    </div>
    </div>

=== "Read a whole website"

    <div class="jcx-demo" markdown>
    <div class="jcx-window"><div class="jcx-window-bar"><i></i><i></i><i></i>browse_a_whole_site.py</div><div class="jcx-crop"><img src="assets/readme/browse.gif" alt="An agent collects all 32 books in the Mystery category of books.toscrape.com across both pages, reports the count per rating, the average price of £31.72 and the three most expensive books, and saves mystery_report.md." loading="lazy" width="983" height="1008"></div></div>
    <div markdown>

    ### Every page, every figure correct

    One agent with a goal opens the catalogue in a real browser, walks every page, computes the figures with code and saves a report: 32 books across 2 pages, every figure matching a hand check.

    <div class="jcx-chips"><span>real browser</span><span>1m 56s</span><span>report saved</span></div>

    [Browser automation guide →](guides/browser-automation.md)

    </div>
    </div>

=== "Compute, never estimate"

    <div class="jcx-demo" markdown>
    <div class="jcx-window"><div class="jcx-window-bar"><i></i><i></i><i></i>analyst_that_computes.py</div><div class="jcx-crop"><img src="assets/readme/analyst.gif" alt="An agent reads a 400-row sales CSV, writes and runs Python, and reports exact revenue per region and Q1 to Q2 growth, with South growing most at 28.64%." loading="lazy" width="983" height="1008"></div></div>
    <div markdown>

    ### Numbers come from code

    Revenue and quarter-on-quarter growth for four regions from a 400-row CSV, computed by Python the agent writes and runs in a sandbox. No figure is guessed by the model.

    <div class="jcx-chips"><span>sandboxed Python</span><span>54s</span><span>exact figures</span></div>

    [AutoAgent guide →](guides/autoagent.md)

    </div>
    </div>

=== "Remember across runs"

    <div class="jcx-demo" markdown>
    <div class="jcx-window"><div class="jcx-window-bar"><i></i><i></i><i></i>agent_that_remembers.py</div><div class="jcx-crop"><img src="assets/readme/memory.gif" alt="The first run is told Acme renews on 3 March 2027 with Jane Mwangi as contact; a second process, given nothing, answers with the date and the contact." loading="lazy" width="983" height="1008"></div></div>
    <div markdown>

    ### Tell it once

    The first run is told a renewal date and a contact. A brand-new process, given nothing, answers with both. Memory works out of the box on disk; point it at Athena to share semantic memory across machines.

    <div class="jcx-chips"><span>nothing to install</span><span>.jarviscore/memory</span><span>Athena optional</span></div>

    [Memory concepts →](concepts/memory.md)

    </div>
    </div>

=== "Survive kill -9"

    <div class="jcx-demo" markdown>
    <div class="jcx-window"><div class="jcx-window-bar"><i></i><i></i><i></i>survives_a_crash.py</div><div class="jcx-crop"><img src="assets/readme/crash.gif" alt="A two-step workflow is started, the process is killed with kill -9 once step 1 is saved, and the same command in a new process recovers step 1 from Redis and finishes step 2." loading="lazy" width="983" height="1008"></div></div>
    <div markdown>

    ### Kill it mid-run. Run it again.

    Finished steps come back from Redis and only the unfinished work runs. Long jobs, flaky hosts and deploys stop costing you hours of repeated work.

    <div class="jcx-chips"><span>Redis</span><span>durable steps</span><span>no re-runs</span></div>

    [Durable goal execution →](guides/goal-execution.md)

    </div>
    </div>

</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">A few lines of Python</span>

## You write the role. The runtime does the rest.

<div class="jcx-split" markdown>
<div markdown>

```python title="analyst.py"
import asyncio
from jarviscore import AutoAgent, Mesh


class Analyst(AutoAgent):
    role = "analyst"
    capabilities = ["web_research", "data_analysis"]
    system_prompt = "Collect complete data; compute with code."
    goal_oriented = True


async def main():
    mesh = Mesh()
    mesh.add(Analyst)
    await mesh.start()
    result = await mesh.run_task(
        agent="analyst",
        task="Which three Mystery books on books.toscrape.com "
             "cost the most?",
    )
    print(result["result_summary"])
    await mesh.stop()

asyncio.run(main())
```

</div>
<div markdown>

<ol class="jcx-steps">
<li><strong>It chooses its tools.</strong>Search, read, browse, write and run code, or ask another agent. Every turn is one real tool call.</li>
<li><strong>It checks its own work.</strong>A goal is done when its evidence says so, not when the model says so. An agent that could not finish fails with its reason.</li>
<li><strong>It keeps a record.</strong>Each step is saved as it finishes, so a crash costs nothing already done.</li>
<li><strong>It hands back proof.</strong><code>result_summary</code> is the answer; <code>evidence</code> lists what was read and written; <code>status</code> is honest.</li>
</ol>

[How an agent turn works →](concepts/architecture.md)

</div>
</div>

</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">New in 2.3 · Multiplayer</span>

## Your team and its agents, in the same thread

<div class="jcx-split" markdown>
<div markdown>

<p class="jcx-sub">Anyone on the team asks in their own words. Agents do the work on shared files, people review and decide where they already talk, and every action is taken as the person who said it.</p>

<ul class="jcx-steps">
<li><strong>Rooms.</strong>Versioned shared files, members and roles. Every change arrives as a proposal; accepting merges line by line.</li>
<li><strong>Decisions stay human.</strong>The agent prepares; the person confirms with one tap. Nothing is accepted from what an agent read.</li>
<li><strong>Each person's own access.</strong>Work that used someone's Gmail or CRM is held for them until they release it.</li>
<li><strong>Slack built in.</strong>One app for every room of a tenant, Socket Mode, no Slack token in your code.</li>
</ul>

[Build a multiplayer agent →](guides/multiplayer-agents.md)

</div>
<div markdown>

<div class="jcx-thread">
<div class="jcx-thread-head">#launch-atlas <span>Thread · from a live run, trimmed</span></div>
<div class="jcx-msg"><div class="jcx-avatar" style="background:#7c3aed">AC</div><div><b>Ava Chen</b><p>@JarvisCore can you draft a short launch announcement in announcement.md from the brief? We launch Tuesday.</p></div></div>
<div class="jcx-msg"><div class="jcx-avatar" style="background:#1758F5">JC</div><div><b>JarvisCore <small>app</small></b><p>I've asked the agents to draft it from the brief. The proposal will appear in this thread.</p><div class="jcx-trace">plan: step-1 (writing) → step-2 (writing)<br>writer took step-1 · finished<br>writer took step-2 · finished</div></div></div>
<div class="jcx-msg"><div class="jcx-avatar" style="background:#0f766e">BI</div><div><b>Bob Iyer</b><p>nice, but move the launch to Wednesday and keep it under 80 words</p></div></div>
<div class="jcx-msg"><div class="jcx-avatar" style="background:#1758F5">JC</div><div><b>JarvisCore <small>app</small></b><div class="jcx-proposal">▲ <b>p-2ce60594</b> proposed by writer for Bob Iyer<br><small>announcement.md · revised as Bob asked</small><div class="jcx-buttons"><span>Accept</span><span>Full change</span></div></div></div></div>
<div class="jcx-msg"><div class="jcx-avatar" style="background:#b45309">DW</div><div><b>Dana Whitfield</b><p>this one's good, ship it</p></div></div>
<div class="jcx-msg"><div class="jcx-avatar" style="background:#1758F5">JC</div><div><b>JarvisCore <small>app</small></b><p><span class="jcx-ok">✓</span> Dana Whitfield accepted p-2ce60594 → v2</p></div></div>
</div>

</div>
</div>

</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">Batteries included</span>

## Everything an agent needs, already wired

<p class="jcx-sub">No glue code between the parts. Add an agent to a mesh and it gets tools, memory, credentials, durable state and tracing.</p>

<div class="jcx-caps" markdown>

<div class="jcx-cap" markdown>
:material-web:
### Browser
Reads JavaScript sites page after page, fills forms, stays logged in, and waits for approval before anything that commits you.

[Browser automation →](guides/browser-automation.md)
</div>

<div class="jcx-cap" markdown>
:material-language-python:
### Sandboxed code
Agents write Python, run it confined, repair what fails, and keep verified functions for reuse.

[AutoAgent →](guides/autoagent.md)
</div>

<div class="jcx-cap" markdown>
:material-magnify-scan:
### Research
Search, read and cite the live web. Answers carry the pages they came from.

[Internet search →](guides/internet-search.md)
</div>

<div class="jcx-cap" markdown>
:material-brain:
### Memory
Working, episodic and long-term memory out of the box; Athena for semantic memory shared across machines.

[Memory →](concepts/memory.md)
</div>

<div class="jcx-cap" markdown>
:material-shield-key:
### Credentials with Nexus
OAuth and API keys for your integrations, placed at the call and never in a prompt.

[Nexus →](guides/nexus.md)
</div>

<div class="jcx-cap" markdown>
:material-transit-connection-variant:
### Agent mesh
Agents find each other by capability over SWIM gossip. One process or many machines, the same code.

[P2P →](concepts/p2p.md)
</div>

<div class="jcx-cap" markdown>
:material-graph-outline:
### Durable workflows
Plans, DAGs and goals that survive restarts, with budgets, retries and replanning.

[Workflows →](guides/workflows.md)
</div>

<div class="jcx-cap" markdown>
:material-account-group:
<span class="jcx-new">New</span>
### Multiplayer rooms
Teams and agents on shared files, from Slack or your own app, with audit and per-person spending caps.

[Multiplayer →](concepts/multiplayer.md)
</div>

<div class="jcx-cap" markdown>
:material-chart-timeline-variant:
### Observability
Every turn, tool call and model request traced: live streams, JSONL records, Prometheus.

[Observability →](guides/observability.md)
</div>

</div>

</section>

<section class="jcx-band jcx-band-sovereign" markdown>
<div markdown>

<span class="jcx-eyebrow">JarvisCore Enterprise</span>

<h2>Agents that act within your institution's boundaries</h2>

<p>Registered agent identities, delegated access on behalf of each person, cost efficiency at scale and workflows that improve themselves. On your infrastructure, with your keys and your models.</p>

<ul class="jcx-ticks">
<li>Nexus agent identity, OBO sessions and enforced scopes</li>
<li>Maven cost efficiency and enterprise model routing</li>
<li>Deployment, support and professional services</li>
</ul>

<div class="jcx-actions">
<a class="jcx-btn jcx-btn-primary" href="infrastructure/enterprise/">Explore Enterprise →</a>
</div>

</div>
<div class="jcx-video" data-yt="7_Uo5n9CKYw" data-title="JarvisCore Enterprise">
<a class="jcx-video-poster" href="https://www.youtube.com/watch?v=7_Uo5n9CKYw" target="_blank" rel="noopener" aria-label="Play the JarvisCore Enterprise film, 2 minutes">
<img src="https://i.ytimg.com/vi/7_Uo5n9CKYw/maxresdefault.jpg" alt="JarvisCore Enterprise: welcome to your sovereignty" width="1280" height="720" loading="lazy">
<span class="jcx-play"></span>
</a>
<div class="jcx-video-meta"><span>▶ Enterprise</span><span>2:00</span></div>
</div>
</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">Start here</span>

## Pick your path

<div class="jcx-paths">
<a class="jcx-path" href="getting-started/"><small>5 minutes</small><strong>Run your first agent</strong><span>Install, add one model key, and watch an agent research, compute and answer.</span></a>
<a class="jcx-path" href="concepts/architecture/"><small>Understand</small><strong>Learn how it fits together</strong><span>Agents, the Kernel, memory, the mesh and Nexus: the mental model in one read.</span></a>
<a class="jcx-path" href="guides/production/"><small>Ship</small><strong>Take it to production</strong><span>Redis, storage, credentials, sandboxing and scaling a fleet of agents.</span></a>
</div>

</section>

<section class="jcx-section" markdown>

<span class="jcx-kicker">Compare</span>

## Coming from another framework?

<p class="jcx-sub">How JarvisCore differs from <a href="compare/crewai/">CrewAI</a>, <a href="compare/langgraph/">LangGraph</a> and <a href="compare/hermes-agent/">Hermes Agent</a> by operating model, and <a href="guides/migration/">how to migrate</a>. The integration catalog for your installed version is one command away: <a href="reference/cli/#atom-list"><code>jarviscore atom list</code></a>.</p>

</section>

<div class="jc-ecosystem" markdown>
<div class="jc-ecosystem-card" markdown>

### Star us on GitHub

Every star helps another developer find JarvisCore.

<div class="jc-cta" markdown>
[Star on GitHub](https://github.com/Prescott-Data/jarviscore-framework){ .jc-btn .jc-btn-github target="_blank" rel="noopener" }
</div>

</div>
<div class="jc-ecosystem-card" markdown>

### Build with us

Ask questions, share what you're building, and debug real agents with the team.

<div class="jc-cta" markdown>
[Join Discord](https://discord.gg/jarviscore){ .jc-btn .jc-btn-discord target="_blank" rel="noopener" }
</div>

</div>
</div>
