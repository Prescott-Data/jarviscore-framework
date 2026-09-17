---
icon: material/source-repository
title: Open Source AI Agent Framework for Production
description: Evaluate open source AI agent frameworks by autonomy, orchestration, durable state, tools, credentials, observability, and deployment model.
---

# Open source AI agent framework for production

An open source AI agent framework should do more than wrap a model call. Once an
agent runs unattended, the hard problems become execution ownership, durable
state, tool failures, credential boundaries, human decisions, and evidence about
what actually happened.

JarvisCore is an Apache-2.0 Python framework for building autonomous and
deterministic agents on a shared runtime. It combines agent reasoning, a
peer-to-peer Mesh, Redis-backed workflow state, typed integration atoms, Nexus
credential isolation, memory, and tracing in one installable package.

```bash
pip install "jarviscore-framework[redis]"
```

## What to evaluate in an agent framework

### 1. Where does control live?

Some frameworks place control in a manager agent. Others use a developer-authored
graph or an event-driven flow. JarvisCore supports explicit workflow DAGs, but a
natural-language distributed goal does not create a permanent supervisor.

`Mesh.execute_goal()` uses a temporary planning lease to publish a validated,
capability-addressed DAG. Once published, agents inspect ready work and race to
claim steps they are authorized to execute. Redis resolves ownership atomically;
no agent selects the winner.

### 2. Is completion durable and inspectable?

A successful function return does not necessarily mean the source request is
satisfied. JarvisCore records immutable attempts and maintains a separate
current-obligation projection. Its result contract exposes:

- `status` for execution state;
- `obligation_status` for current source-goal satisfaction;
- `response_status` for final-response delivery.

Reconciliation appends only work needed for unresolved obligations. Completed
effects and their evidence are retained instead of replayed. See
[Durable Goal Execution](guides/goal-execution.md).

### 3. Can deterministic and autonomous agents coexist?

JarvisCore offers two profiles rather than forcing every component into one
reasoning model:

| Profile | You own | The framework owns |
|---|---|---|
| [`AutoAgent`](guides/autoagent.md) | Role, capabilities, system prompt | OODA loop, model routing, tool selection, sandbox execution, repair |
| [`CustomAgent`](guides/customagent.md) | Request handlers and deterministic application logic | Identity, lifecycle, Mesh, mailbox, storage, memory, credentials |

Both profiles can participate in one workflow and use the same infrastructure.

### 4. How do tools and credentials cross the boundary?

JarvisCore integrations are plain, typed Python functions called atoms. The
Kernel searches a versioned registry, reuses verified functions, and can repair
eligible code failures in a sandbox. Nexus resolves credentials at the provider
call boundary so raw tokens do not enter prompts or generated code.

Browse the [integration catalog](guides/integrations.md) and
[Nexus architecture](concepts/nexus.md).

### 5. What survives a process failure?

With Redis configured, workflow definitions, claims, attempts, outputs,
obligations, mailbox messages, checkpoints, and traces survive process death.
Claims use leases and fenced writes so an expired worker cannot overwrite a
newer's terminal result.

### 6. Can you operate it without a separate control-plane product?

JarvisCore includes JSONL and Redis traces, PubSub event streaming, Prometheus
metrics, workflow inspection, and a FastAPI integration. Optional enterprise
operations exist, but the runtime's core observability and durable state are in
the open-source package.

## Minimal agent, distributed runtime

```python
import asyncio

from jarviscore import AutoAgent, Mesh


class Researcher(AutoAgent):
    role = "researcher"
    capabilities = ["web_research"]
    system_prompt = "Find primary sources and return claims with URLs."


async def main():
    mesh = Mesh(config={"redis_url": "redis://localhost:6379/0"})
    mesh.add(Researcher)
    await mesh.start()
    try:
        result = await mesh.execute_goal(
            "Research the market and produce a source-backed decision brief.",
            workflow_id="market-brief-001",
        )
        print(result["status"], result["obligation_status"])
    finally:
        await mesh.stop()


asyncio.run(main())
```

Production systems normally add peers with complementary capabilities. Each peer
plans its own bounded execution after claiming a step.

## How it compares

JarvisCore is not the only valid open-source choice:

- **CrewAI** is a natural fit for role-based Crews coordinated inside
  event-driven Flows.
- **LangGraph** is a natural fit when your application should be expressed as an
  explicit state graph with developer-authored nodes and edges.
- **Hermes Agent** is a natural fit for a persistent personal assistant reached
  through a terminal or messaging gateway.
- **JarvisCore** is a fit when the runtime itself must coordinate independent
  agents, durable provider work, obligations, memory, credentials, and recovery.

Read the [framework comparison hub](compare/index.md) before choosing. The goal
is architectural fit, not replacing one vocabulary with another.

## Start with working code

1. [Install JarvisCore and run your first agent](getting-started.md).
2. Choose [`AutoAgent`](guides/autoagent.md) or
   [`CustomAgent`](guides/customagent.md).
3. Use an explicit [workflow DAG](guides/workflows.md) when the steps are known.
4. Use [durable goal execution](guides/goal-execution.md) when peers should
   compile and claim capability-addressed work.
5. Apply the [production deployment checklist](guides/production.md).