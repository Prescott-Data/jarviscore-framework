---
icon: material/safety-goggles
title: Open Source Agent Harness for Reliable AI Systems
description: Learn what an open source agent harness should provide for planning, tools, context, memory, permissions, recovery, evaluation, and observability.
---

# Open source agent harness for reliable AI systems

An **agent harness** is the runtime around a language model that turns model
output into controlled, observable work. The model may decide what to do next,
but the harness decides what context it sees, which tools it can call, how long
it can run, where effects execute, what state survives, and what counts as done.

JarvisCore's `AutoAgent` is an open-source Python agent harness operating inside
a broader multi-agent runtime. It combines a supervised OODA loop with planning,
specialized sub-agents, typed tools, sandboxed code, repair, memory, budgets,
traces, and peer collaboration.

## The minimum harness contract

A production harness needs explicit answers to seven questions.

| Concern | JarvisCore mechanism |
|---|---|
| **Reasoning loop** | Kernel Observe, Orient, Decide, Act loop with role-specific execution leases |
| **Context** | Goal context, epistemic ledger, dependency evidence, workflow inspection, and labeled summaries |
| **Tools** | Versioned atom registry, typed schemas, provider integrations, browser and search sub-agents |
| **Execution** | Isolated coder sandbox with bounded validation and repair |
| **Permissions** | Capability contracts, Nexus credential injection, effect review, and typed HITL boundaries |
| **Persistence** | Redis workflows, attempts, outputs, mailbox, checkpoints, obligations, and long-term memory |
| **Observability** | Structured traces, JSONL, Redis PubSub, Prometheus metrics, and workflow inspection |

Without these boundaries, an agent loop is easy to demo but hard to trust.

## A harness is not the same as an orchestration graph

A graph runtime determines which node runs next and how state moves between
nodes. A harness determines how an agent behaves *inside* an agentic node: how it
plans, selects tools, handles failures, evaluates evidence, and stops.

JarvisCore provides both layers without collapsing them:

- `AutoAgent.execute_goal()` runs one agent's internal Plan, Execute, Evaluate
  loop.
- `Mesh.workflow()` executes an application-authored multi-agent DAG.
- `Mesh.execute_goal()` compiles a source goal into capability-addressed work
  that independent peers claim from durable state.

This separation lets a deterministic `CustomAgent` and a fully autonomous
`AutoAgent` work in the same DAG without pretending they have the same control
model.

## Tool use without handing over credentials

The harness exposes callable schemas to the model, but credentials stay behind
the runtime boundary. Built-in atoms call external services through Nexus, which
resolves scoped credentials at execution time. Generated Python receives a
restricted namespace and cannot mutate the parent Mesh lifecycle or registry.

When a suitable atom does not exist, the coder can generate an implementation,
execute it in the sandbox, and repair eligible code failures. A replacement only
enters the registry after contract validation and a successful invocation.

## Context that preserves uncertainty

An agent harness should not flatten every upstream result into "success." In a
distributed JarvisCore workflow, a peer receives the source objective, current
workflow plan, relevant dependency outputs, execution budget, and durable
workflow identity. It can inspect sibling steps and ask another peer by role or
capability.

Agent-owned interpretations can report which stable obligation IDs their
evidence satisfies or leaves unresolved. The storage layer records that
interpretation without inventing domain judgment from HTTP status codes or
string patterns.

## Bounded autonomy

JarvisCore bounds autonomous execution through:

- turn, token, cost, and wall-clock budgets;
- typed tool schemas and capability authority;
- sandbox and provider-call boundaries;
- pre-effect review and idempotency controls;
- typed human escalation only for credentials, human-exclusive data, or
  consequential actions;
- convergence evaluation and durable cancellation fencing.

These are safety boundaries around agent reasoning, not a replacement for it.

## Harness comparison

The term overlaps with several adjacent projects:

- LangChain describes Deep Agents as an agent harness built on LangGraph, while
  LangGraph itself is the lower-level orchestration runtime.
- Hermes Agent packages an interactive personal agent, memory, skills, terminal
  execution, subagents, scheduling, and messaging gateways as one end-user
  system.
- CrewAI provides autonomous Crews and event-driven Flows at a higher
  application abstraction.
- JarvisCore combines the AutoAgent harness with a peer-to-peer fleet runtime,
  deterministic CustomAgents, provider credentials, and a durable shared work
  ledger.

See [Compare open source agent frameworks](compare/index.md) for a neutral
selection guide.

## Build with the harness

Start with the [`AutoAgent` guide](guides/autoagent.md), then add:

1. [system prompts](guides/system-prompts.md) for the role and output contract;
2. [integration atoms](guides/integrations.md) for real provider work;
3. [testing](guides/testing.md) for deterministic harness checks;
4. [observability](guides/observability.md) for execution evidence;
5. [durable goals](guides/goal-execution.md) when several harnessed agents must
   coordinate without a permanent router.