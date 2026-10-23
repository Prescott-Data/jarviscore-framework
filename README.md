<p align="center">
  <img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/combo-brand.svg" alt="JarvisCore" height="68" />
</p>

<p align="center">
  <a href="https://pypi.org/project/jarviscore-framework/"><img src="https://img.shields.io/pypi/v/jarviscore-framework?style=flat-square&color=1758F5&label=pypi" alt="PyPI" /></a>
  <a href="https://pypi.org/project/jarviscore-framework/"><img src="https://img.shields.io/pypi/pyversions/jarviscore-framework?style=flat-square&color=0533AC" alt="Python" /></a>
  <a href="https://jarviscore.developers.prescottdata.io/"><img src="https://img.shields.io/badge/docs-jarviscore-35B0FE?style=flat-square" alt="Docs" /></a>
  <a href="https://discord.gg/B2aJV5BJmb"><img src="https://img.shields.io/badge/office%20hours-discord-0CF0E3?style=flat-square&labelColor=0533AC" alt="Discord" /></a>
  <a href="https://github.com/Prescott-Data/jarviscore-framework/tree/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-1758F5?style=flat-square" alt="License" /></a>
</p>

```bash
pip install jarviscore-framework
```

**JarvisCore** is a runtime where AI agents operate as a fleet of equal peers. Agents
discover one another by capability, execute tasks from a shared ledger, and authenticate
to every external service through a zero-trust broker, never with their own keys.

<p align="center">
  <img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/mesh-vs-orchestrator.png" alt="Two blueprints side by side. A, a central orchestrator: one box that plans, routes and holds state, with arrows out to scout, coder, browser and writer, marked as a single point of failure; if it stops, everything stops. B, the JarvisCore peer mesh: scout, coder, browser and writer connected to each other, an analyst shown stopped, each live peer linked to a shared ledger of steps, claims and results in Redis, and coder and browser linked to the Nexus zero-trust broker; a node stops and a peer claims its step from the ledger." width="900" />
</p>

Most agent frameworks put one **orchestrator** in charge: it plans, routes every request
and holds the state, so the system is only as available as that one process. On a
JarvisCore **mesh**, every agent is a **peer**. Peers find each other by what they can
do (SWIM gossip), take steps from a shared **ledger** (Redis) and record what they did
there, so when one stops, another claims its step and the work goes on. None of them
holds a credential: the **Nexus** broker places it at the call.


## Video overview

<p align="center">
  <a href="https://www.youtube.com/watch?v=4IOpKZgjXIw"><img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/video-overview.jpg" alt="Watch the JarvisCore overview on YouTube (2:07): an open-source runtime for AI agents that work as a mesh of equal peers." width="820" /></a>
</p>
<p align="center"><sub>The whole idea in two minutes: discovery by capability, the shared ledger, and the zero-trust broker, on a real mesh.</sub></p>

## Contents

- [Video overview](#video-overview)
- [Components](#components)
- [Start in two minutes](#start-in-two-minutes)
- [What people build with it](#what-people-build-with-it)
- [What you can count on](#what-you-can-count-on)
- [Go further](#go-further)
- [Community](#community)
- [License](#license)

## Components

JarvisCore puts eight components around the model: **AutoAgent, CustomAgent, the
Kernel, the mesh, memory, Nexus, integrations, and people in the loop**, with
[rooms](https://jarviscore.developers.prescottdata.io/concepts/multiplayer/) for teams. You write the agents; the rest
handles context, tools, credentials, durable state, coordination and approvals around
every call the model makes.

<p align="center">
  <img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/components.png" alt="The model at the top, connected to four groups of components. Write: AutoAgent (role, capabilities, prompt) and CustomAgent (plain Python in execute_task). Run: the Kernel (roles, budgets, done check) and the mesh (peers, shared ledger, pools). Remember and reach: memory (notes, episodes, Athena), Nexus (credentials placed at the call) and integrations (typed atoms, auth injected). People: people in the loop (approve once, then it runs) and rooms (shared files, Slack), new in 2.3. You write the first column; the runtime supplies the rest." width="900" />
</p>

## Start in two minutes

Use **Python 3.10 or later** and one model key. In a new folder:

```bash
pip install jarviscore-framework
jarviscore init
cp .env.example .env    # add AZURE_API_KEY, CLAUDE_API_KEY, GEMINI_API_KEY or LLM_ENDPOINT
jarviscore check --validate-llm
```

Then run your first agent. It needs no database, broker or Docker:

```python
import asyncio
from jarviscore import AutoAgent, Mesh


class Researcher(AutoAgent):
    role = "researcher"
    capabilities = ["research"]
    system_prompt = "You find primary sources, read them, and cite every fact."


async def main():
    mesh = Mesh()
    mesh.add(Researcher)
    await mesh.start()
    result = await mesh.run_task(
        agent="researcher",
        task="What changed in the EU AI Act's final text for open-source models?",
    )
    print(result["result_summary"])  # the answer
    print(result["evidence"])        # what the tools actually saw
    await mesh.stop()

asyncio.run(main())
```

Add capabilities as you need them: a [browser](https://jarviscore.developers.prescottdata.io/guides/browser-automation/)
(`[browser]`), [durable workflows and crash recovery](https://jarviscore.developers.prescottdata.io/guides/workflows/)
(`[redis]` with `REDIS_URL`), [agents on several machines](https://jarviscore.developers.prescottdata.io/concepts/p2p/)
(`[p2p]`), or everything (`[full]`). Prefer plain Python? A
[`CustomAgent`](https://jarviscore.developers.prescottdata.io/guides/customagent/) runs on the same mesh. See
[Getting Started](https://jarviscore.developers.prescottdata.io/getting-started/) for the full walkthrough.

## What people build with it

### A research team, live in the Desk

<p align="center">
  <a href="https://github.com/Prescott-Data/jarviscore-framework/releases/download/v2.3.0/desk-research-team.mp4"><img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/desk-research-team.gif" alt="Play the recording: the JarvisCore Desk running a three-agent research mesh. The request is typed, the Scout searches the web and reads official docs, the Analyst compares the options and hands its comparison to the Writer, and the Writer delivers a decision brief with source links as a document." width="900" /></a>
</p>
<p align="center"><sub>
  Three agents on one mesh: a scout reads official docs on the live web, an analyst compares, a writer delivers the brief
  with its sources. A real run, idle time trimmed. <a href="https://github.com/Prescott-Data/jarviscore-framework/releases/download/v2.3.0/desk-research-team.mp4">Play the video</a> to pause and scrub.
  The Desk ships with <a href="https://github.com/Prescott-Data/jarviscore-agents">JarvisCore Agents</a>, with four complete blueprints to run in it.
</sub></p>

The whole team is [30 lines of Python](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/desk/research_desk.py):

```python
class Scout(AutoAgent):
    role = "scout"
    capabilities = ["web_research"]
    default_kernel_role = "researcher"
    system_prompt = "You find primary sources on the live web, read them, and cite every fact."

class Analyst(AutoAgent):
    role = "analyst"
    capabilities = ["analysis"]
    default_kernel_role = "communicator"
    system_prompt = "You compare options strictly on the evidence."

class Writer(AutoAgent):
    role = "writer"
    capabilities = ["writing"]
    default_kernel_role = "communicator"
    system_prompt = "You write short, decisive briefs for engineering leads, citing sources."

results = await mesh.workflow("vector-db-brief", [
    {"agent": "scout",   "task": "Gather the facts this request turns on, from official docs: ..."},
    {"agent": "analyst", "task": "Compare the options on the scout's evidence.", "depends_on": [0]},
    {"agent": "writer",  "task": "Write a decision brief of at most eight lines.", "depends_on": [1]},
])
```

### Read a whole website

One `goal_oriented` agent opens the catalogue, walks every page, computes the figures
with code and saves a report: 32 books, 2 pages, every figure correct.
[`browse_a_whole_site.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/browse_a_whole_site.py) · real time 1m 56s ·
needs `jarviscore-framework[browser]` and `BROWSER_ENABLED=true`.

<details><summary>Watch it run in a terminal</summary>

<img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/browse.gif" alt="browse_a_whole_site.py: an agent collects all 32 books in the Mystery category of books.toscrape.com across both pages, reports the count per rating, the average price of £31.72 and the three most expensive books, and saves mystery_report.md." width="820" />

</details>

### Compute, never estimate

Revenue and quarter-on-quarter growth for four regions from a 400-row CSV, computed by
code the agent writes and runs in a sandbox. Every figure matches a hand-written check.
[`analyst_that_computes.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/analyst_that_computes.py) · real time 54s.

<details><summary>Watch it run in a terminal</summary>

<img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/analyst.gif" alt="analyst_that_computes.py: an agent reads a 400-row sales CSV, writes and runs Python, and reports exact revenue per region and Q1 to Q2 growth, with South growing most at 28.64%." width="820" />

</details>

### Remember across runs

Tell it once. A new process, given nothing, still knows. Kept facts live in
`.jarviscore/memory/`, with nothing to install; point it at Athena for semantic memory
shared across machines. [`agent_that_remembers.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/agent_that_remembers.py).

<details><summary>Watch it run in a terminal</summary>

<img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/memory.gif" alt="agent_that_remembers.py run twice: the first run is told Acme renews on 3 March 2027 with Jane Mwangi as contact; a second process, given nothing, answers with the date and the contact; the fact is shown on disk in .jarviscore/memory/account_manager.jsonl." width="820" />

</details>

### Survive `kill -9`

Kill the process mid-workflow and run the same command again: finished steps come back
from Redis, and only the unfinished work runs.
[`survives_a_crash.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/survives_a_crash.py) · needs `REDIS_URL`.

<details><summary>Watch it run in a terminal</summary>

<img src="https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/crash.gif" alt="survives_a_crash.py: a two-step workflow is started, the process is killed with kill -9 once step 1 is saved, and the same command in a new process recovers step 1 from Redis without re-running it and finishes step 2." width="820" />

</details>

### Work as a team, in Slack <sub>new in 2.3</sub>

People ask in their own words, agents change the team's shared files, and every
change comes back as a proposal people accept with one tap, as themselves. Work
that used someone's own Gmail or CRM is held for them. Live against a Slack
sandbox with a real model: a draft, a revision from a teammate's feedback, an
acceptance only the person who decided could confirm, and work that finished
once after a restart. [Build a multiplayer agent](https://jarviscore.developers.prescottdata.io/guides/multiplayer-agents/).

<details>
<summary><strong>More, end to end</strong></summary>

| Demo | What it shows |
|---|---|
| [Research team, in a terminal](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/showcase/research_team.py) | The same kind of team without the Desk: a scout and an analyst, one workflow, a cited brief. [Recording](https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/readme/research.gif). |
| [Investment committee](https://github.com/Prescott-Data/jarviscore-framework/tree/main/examples/investment_committee) | Seven agents deliberate a $1.5M position on live market data; the process is killed mid-deliberation and finishes without re-running the analysts. [Recording](https://raw.githubusercontent.com/Prescott-Data/jarviscore-framework/main/jarviscore/docs/assets/demo.gif). |
| [Four-process research mesh](https://github.com/Prescott-Data/jarviscore-framework/releases/download/v1.5.1/mesh_demo_full.mp4) | Four agents in four processes find each other over SWIM, claim steps from a shared ledger, and deliver to Slack through the credential vault. Reproduce with `examples/demo_synthesizer.py` and `demo_node_1/2/3.py`. |
| [Demo film](https://www.youtube.com/watch?v=4IOpKZgjXIw) | Agents as a fleet of equal peers: discovery by capability, a shared ledger, and every external call through the credential broker, in two minutes. |

</details>

## What you can count on

| Promise | What the runtime does |
|---|---|
| **An honest status** | An agent that could not do the task returns `failure` with its own reason, never a success with empty figures. |
| **Evidence you can check** | `result["evidence"]` holds each cited tool's input and output. A receipt the agent did not earn is refused. |
| **Work that survives** | Finished workflow steps are recovered from Redis after a crash, not re-run and not re-billed. Long steps continue across execution epochs. |
| **Memory that lasts** | Facts an agent keeps are recalled in later runs, keyed to its role, and kept apart per tenant with `memory_scope_field`. |
| **Credentials out of reach** | Tokens are placed at the call by Nexus, only for agents that declare `requires_auth`. They never appear in prompts, generated code or traces. |
| **A person in the loop** | Irreversible actions wait for an approval through `Mesh.resolve_hitl()`, then run exactly once. |
| **Scale without rewrites** | `Pool(max=8)` turns one agent into several workers, and every model call is paced to the provider's real limits. Verifying 196 claims took 9.4 minutes with pools, against 202 with fixed workers. |
| **Integrations without wiring** | Typed atoms for CRMs, payments, messaging, storage and more, with auth injected at runtime. See what your installed version ships with [`jarviscore atom list`](https://jarviscore.developers.prescottdata.io/reference/cli/#atom-list). |

## Go further

| Guide | What it covers |
|---|---|
| [Getting started](https://jarviscore.developers.prescottdata.io/getting-started/) | Install, first agent, first multi-agent workflow |
| [AutoAgent](https://jarviscore.developers.prescottdata.io/guides/autoagent/) · [CustomAgent](https://jarviscore.developers.prescottdata.io/guides/customagent/) | The two ways to write an agent |
| [Workflows](https://jarviscore.developers.prescottdata.io/guides/workflows/) · [Goals](https://jarviscore.developers.prescottdata.io/guides/goal-execution/) | Steps you know in advance, and goals that plan their own |
| [Browser](https://jarviscore.developers.prescottdata.io/guides/browser-automation/) · [People in the loop](https://jarviscore.developers.prescottdata.io/guides/hitl/) | Reading and acting on real sites, with approvals |
| [Memory](https://jarviscore.developers.prescottdata.io/concepts/memory/) · [Nexus](https://jarviscore.developers.prescottdata.io/guides/nexus/) | What agents keep, and how they reach your accounts |
| [Production](https://jarviscore.developers.prescottdata.io/guides/production/) · [Configuration](https://jarviscore.developers.prescottdata.io/reference/configuration/) | Pools, pacing, Redis, sandboxes and every setting |
| [Changelog](https://jarviscore.developers.prescottdata.io/changelog/) | What changed, release by release |

## Community

Every other week we debug real agents live in [office hours on Discord](https://discord.gg/B2aJV5BJmb).
If JarvisCore saves you time, a ⭐ helps other developers find it.

## License

Apache 2.0. See [LICENSE](https://github.com/Prescott-Data/jarviscore-framework/tree/main/LICENSE). You can build and sell products with it; there is
no revenue or user threshold that requires a commercial agreement. Separately licensed
enterprise modules have their own terms; see
[JarvisCore Enterprise](https://jarviscore.developers.prescottdata.io/infrastructure/enterprise/).

Building with JarvisCore? An optional
[Built with JarvisCore](https://developers.prescottdata.io) credit on your About page
or docs is appreciated; the [trademark policy](https://github.com/Prescott-Data/jarviscore-framework/blob/main/TRADEMARK.md) applies.
