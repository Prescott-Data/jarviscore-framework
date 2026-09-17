---
icon: material/map-marker-path
title: "JarvisCore Implementation Guides"
description: "Follow practical guides for building AutoAgent and CustomAgent systems, connecting tools, testing workflows, and deploying JarvisCore in production."
---

# Guides

These guides take a system from its first execution profile to production. Start
with an agent, choose how work is orchestrated, connect only the capabilities you
need, then add serving, testing, and operations.

## Choose the execution path first

| Need | Start here |
|---|---|
| One autonomous agent reasons through a task | [AutoAgent](autoagent.md) |
| Application code owns every execution step | [CustomAgent](customagent.md) |
| Your application already knows the workflow DAG | [Workflow DAGs](workflows.md) |
| Peers must derive and claim work from a source goal | [Durable Goal Execution](goal-execution.md) |

Durable Goal Execution is an independent guide because it has a different state
contract from a declared workflow: immutable attempts, source obligations,
revision-fenced reconciliation, and separate execution, obligation, and response
status. Learn Workflow DAGs first if you are new to multi-step execution.

## 1. Build the agents

<div class="grid cards" markdown>

-   :material-robot: **AutoAgent**

    The framework brings the brain. Describe the task; the agent plans, generates code in a sandbox, and self-repairs. Use when you can describe the work but not code it.

    [Read more →](autoagent.md)

-   :material-code-braces: **CustomAgent**

    You bring the brain. Plain Python in `execute_task`, deterministic control, same mesh. Use when you can code the logic.

    [Read more →](customagent.md)

-   :material-text-box-edit-outline: **System Prompts**

    Define an AutoAgent's role, output contract, verification behavior, and
    failure handling.

    [Write system prompts →](system-prompts.md)

-   :material-layers-triple-outline: **Custom Sub-agents**

    Extend the Kernel with a specialized execution unit when built-in roles are
    not enough.

    [Build a sub-agent →](custom-subagents.md)

-   :material-swap-horizontal: **Adapters**

    Bring existing Python, LangChain, or CrewAI objects into the Mesh without a
    full rewrite.

    [Adapt existing code →](adapters.md)

</div>

## 2. Orchestrate work

<div class="grid cards" markdown>

-   :material-sitemap: **Workflow DAGs**

    Declare known steps, roles, dependencies, parallel branches, and output
    chaining in application code.

    [Build a known workflow →](workflows.md)

-   :material-graph-outline: **Durable Goal Execution**

    Compile an unknown source goal into capability-addressed work that peers
    claim independently, with durable obligation truth and selective repair.

    [Run a distributed goal →](goal-execution.md)

-   :material-account-supervisor: **Human-in-the-Loop**

    Pause only at genuine human boundaries, then resume the same durable work.

    [Design human review →](hitl.md)

</div>

## 3. Connect capabilities

<div class="grid cards" markdown>

-   :material-connection: **Integrations**

    Discover the typed atom catalog for business systems, storage, developer
    tools, communication, and provider readback.

    [Browse integrations →](integrations.md)

-   :material-key-variant: **Nexus Credentials**

    Register provider connections while keeping raw credentials outside agent
    reasoning and generated code.

    [Configure credentials →](nexus.md)

-   :material-book-search: **Knowledge Base**

    Ingest internal documents and add local retrieval to research work.

    [Build a knowledge base →](knowledge-base.md)

-   :material-earth: **Internet Search**

    Configure grounded and multi-provider search with ranking and resilience.

    [Configure search →](internet-search.md)

-   :material-web: **Browser Automation**

    Add Playwright-backed interaction for websites that require a real browser.

    [Configure browser automation →](browser-automation.md)

</div>

## 4. Serve, test, and operate

<div class="grid cards" markdown>

-   :material-api: **FastAPI**

    Embed agent lifecycle into a FastAPI application.

    [Integrate FastAPI →](fastapi.md)

-   :material-chat-processing: **Chat Endpoint**

    Expose synchronous and streaming conversational interfaces.

    [Build a chat endpoint →](chat.md)

-   :material-chart-line: **Observability**

    Inspect traces, events, costs, workflow state, and Prometheus metrics.

    [Add observability →](observability.md)

-   :material-test-tube: **Testing Agents**

    Exercise agent behavior with deterministic Mesh, peer, and LLM mocks.

    [Test agents →](testing.md)

-   :material-test-tube-empty: **Testing Atoms**

    Validate integration functions structurally and against connected providers.

    [Test atoms →](testing-atoms.md)

-   :material-robot-happy: **AI Editor Setup**

    Teach Copilot, Claude Code, Cursor, and other coding agents the current
    JarvisCore contracts.

    [Configure an AI editor →](ai-editors.md)

-   :material-rocket-launch: **Production Deployment**

    Harden storage, credentials, sandboxing, networking, budgets, and monitoring.

    [Deploy to production →](production.md)

</div>
