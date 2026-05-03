---
icon: material/hexagon-multiple
---

# Architecture Overview

JarvisCore is a Python framework for building autonomous, multi-agent systems. It provides a structured execution model, a composable infrastructure layer, and a peer-to-peer communication mesh that allows multiple agents to collaborate without centralised coordination.

This page establishes the mental model you need before working with any other part of the framework. Read it once carefully. Every other concept, guide, and reference document in this documentation site assumes familiarity with the terms defined here.

---

## The Two Agent Profiles

JarvisCore provides two distinct agent profiles. Choosing the right one is the first architectural decision you make.

### AutoAgent

`AutoAgent` is a fully autonomous reasoning agent. It receives a task description in natural language and completes it without further instruction. Internally it runs an OODA loop (Observe, Orient, Decide, Act) powered by a `Kernel` that decides which tools to call, in what order, and when the task is complete.

Use `AutoAgent` when:

- The task requires adaptive reasoning or multi-step planning.
- The steps needed to complete the task are not known in advance.
- You want the agent to handle retries, tool failures, and replanning automatically.

### CustomAgent

`CustomAgent` is a structured execution agent. You write the `run()` method yourself, giving you complete control over the execution sequence. The framework provides the infrastructure (memory, peer communication, tool access) but does not impose a reasoning loop.

Use `CustomAgent` when:

- The execution logic is deterministic and known in advance.
- You are implementing a specialised worker (data transformer, notifier, gateway).
- You are wrapping an existing service inside the agent mesh.

---

## The Kernel

The `Kernel` is the reasoning engine inside every `AutoAgent`. It is not instantiated directly; `AutoAgent.setup()` creates and manages it.

On each OODA loop turn the Kernel:

1. Reads the current context bundle from `UnifiedMemory`.
2. Selects the next action by calling the LLM with the full context.
3. Executes the chosen tool or sub-agent call.
4. Writes the result back to memory.
5. Evaluates whether the task is complete or whether it should continue.

The Kernel has a configurable turn limit (`KERNEL_MAX_TURNS`, default `30`). If the limit is reached before the task is complete, the Kernel returns a partial result with an explanation.

---

## The Mesh

The `Mesh` is the top-level runtime object that hosts one or more agents and connects them to shared infrastructure. You create one `Mesh`, add agents to it, and call `start()`.

```python title="Minimal mesh startup"
from jarviscore import Mesh

async def main():
    mesh = Mesh(agents=[MyResearcher, MyAnalyst])
    await mesh.start()
```

`Mesh.start()` performs the following sequence in order:

1. Reads environment variables and initialises the settings object.
2. Connects to Redis if `REDIS_URL` or `REDIS_HOST` is configured.
3. Connects to blob storage based on `STORAGE_BACKEND`.
4. Initialises the `AthenaClient` if `ATHENA_URL` is set.
5. Starts the SWIM gossip coordinator if `P2P_ENABLED=true`.
6. Instantiates every agent class and calls its `setup()` method.
7. Registers agent mailboxes and begins the event loop.

Every piece of infrastructure is opt-in. If none of the infrastructure environment variables are set, the Mesh runs in pure in-process mode using only in-memory state.

---

## The OODA Loop

The Observe-Orient-Decide-Act loop is the execution model for `AutoAgent`. Understanding it makes the framework's behaviour predictable.

| Phase | What happens |
|---|---|
| Observe | The Kernel calls `UnifiedMemory.rehydrate_bundle()` to load all available context: recent episodic turns, the LTM summary, the scratchpad, and any Athena context. |
| Orient | The Kernel formats all context into a system prompt and calls the LLM to produce a next-action decision. |
| Decide | The LLM response is parsed into a structured action: a tool call, a sub-agent invocation, a HITL escalation, or a completion signal. |
| Act | The framework executes the chosen action and writes the outcome back to memory via `UnifiedMemory.log_turn()`. |

The loop continues until the Kernel receives a completion signal, hits the turn limit, or encounters a fatal error.

---

## Infrastructure Layers

JarvisCore's infrastructure is composed of independent, opt-in layers. Each layer activates only when the corresponding environment variables are present.

| Layer | What it provides | Activates when |
|---|---|---|
| Redis | Distributed workflow state, durable mailboxes, episodic ledger | `REDIS_URL` is set |
| Blob Storage | Large output persistence (reports, datasets, generated files) | Always (defaults to local filesystem) |
| Athena MemOS | Cross-session semantic memory (STM, MTM, LTM graph) | `ATHENA_URL` is set |
| Nexus Gateway | OAuth and API-key credential management for third-party services | `NEXUS_GATEWAY_URL` is set |
| P2P / SWIM Mesh | Multi-node agent discovery and message routing | `P2P_ENABLED=true` |

None of these layers are required for a single-node, single-session workflow. You add them as your operational requirements grow.

---

## Agent Personas

Every agent in JarvisCore has an identity that shapes how it reasons and what it is authorised to do. Identity is defined by two complementary mechanisms.

**Class-level attributes** define the agent's static identity: its name, role, capabilities, and system prompt. These are set on the class body and are available before the agent runs.

**Agent profiles** (YAML files) inject structured role intelligence into the system prompt at runtime. A profile adds expertise areas, standing operating procedures, artifact ownership, and escalation rules. Profiles are loaded from the directory pointed to by `JARVISCORE_PROFILES_DIR`.

The combination of class-level identity and a loaded profile gives each agent a complete, grounded understanding of its role without requiring the developer to embed long prose in the system prompt.

---

## Sub-agents

Sub-agents are specialised capability modules that the Kernel can call as tools. They are not standalone agents and do not run their own event loops. The Kernel treats them identically to any other tool call.

The built-in sub-agents are:

| Sub-agent | Purpose |
|---|---|
| `CoderSubAgent` | Write, review, and execute code |
| `ResearcherSubAgent` | Search the internet and synthesise findings |
| `BrowserSubAgent` | Navigate web pages and interact with browser UIs |
| `DataAnalystSubAgent` | Analyse structured data and produce visualisations |

You can implement custom sub-agents by subclassing `BaseSubAgent`. Custom sub-agents are registered with the Kernel via the `tools` list on the agent class.

---

## What to Read Next

If you are new to JarvisCore, follow this reading order:

1. [Memory](./memory.md) — understand how agents persist and retrieve context.
2. [Agent Personas](./agent-personas.md) — understand how profiles shape agent behaviour.
3. [P2P Communication](./p2p.md) — understand how agents communicate across a mesh.
4. Then proceed to the [Getting Started guide](../getting-started.md) to write your first agent.
