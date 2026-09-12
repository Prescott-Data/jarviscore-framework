---
icon: material/cube-outline
title: "JarvisCore Multi-Agent Framework Concepts"
description: "Learn agent identity, execution models, peer-to-peer coordination, planning loops, memory architecture, and distributed task routing."
---

# Concepts

Use this section to build the mental model behind JarvisCore before choosing
implementation details. Read the stages in order if you are new to the
framework; jump directly to a concept when diagnosing an existing system.

## 1. Runtime foundations

<div class="grid cards" markdown>

-   :material-hexagon-multiple: **Architecture**

    See how the agent profiles, Mesh, durable state, integrations, credentials,
    and observability fit together.

    [Start with the architecture →](architecture.md)

-   :material-robot-outline: **Agents**

    Understand agent identity, capabilities, lifecycle, and the boundary between
    autonomous `AutoAgent` and deterministic `CustomAgent` execution.

    [Understand agents →](agents.md)

</div>

## 2. Reasoning and model behavior

<div class="grid cards" markdown>

-   :material-map-outline: **Planning**

    Learn the single-agent Plan, Execute, Evaluate loop and when replanning
    occurs.

    [Learn planning →](planning.md)

-   :material-chip: **Language Models**

    Understand provider configuration and the model roles used by the runtime.

    [Understand language models →](language-models.md)

-   :material-transit-connection-variant: **Model Routing**

    See how capability tiers select models for reasoning, coding, browser work,
    and lightweight evaluation.

    [Learn model routing →](model-routing.md)

-   :material-account-circle: **Agent Personas**

    Add structured role intelligence and operating context without replacing an
    agent's executable contract.

    [Define personas →](agent-personas.md)

</div>

## 3. State and coordination

<div class="grid cards" markdown>

-   :material-database: **Memory**

    Follow working, episodic, long-term, and optional Athena semantic memory
    across turns and sessions.

    [Understand memory →](memory.md)

-   :material-transit-connection-variant: **P2P Communication**

    Learn how agents discover peers, exchange requests, and communicate across
    processes with SWIM and ZMQ.

    [Understand peer communication →](p2p.md)

</div>

## 4. Tools and trust boundaries

<div class="grid cards" markdown>

-   :material-puzzle: **System Bundles and Atoms**

    Understand typed integration functions, registry discovery, versioning, and
    how atoms differ from MCP servers.

    [Understand tools →](system-bundles.md)

-   :material-shield-key: **Nexus**

    See how provider credentials are resolved at the execution boundary and kept
    out of agent reasoning.

    [Understand credentials →](nexus.md)

</div>

Once this model is clear, move to the [implementation guides](../guides/index.md).
