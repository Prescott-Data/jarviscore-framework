---
icon: material/puzzle
title: "Contracts and Boundaries in JarvisCore"
description: "Understand JarvisCore execution, capability, completion, result, work-product, and durable-goal contracts and which layer owns each one."
---

# Contracts and Boundaries

Prompts tell an agent how to reason. Contracts tell the runtime what may execute,
what shape crosses a boundary, and what counts as complete. Production systems
need both: a prompt can explain good judgment, but it cannot enforce authority,
schema validity, durable identity, or completion state.

JarvisCore has several contracts at different boundaries. They are related, but
not interchangeable.

## Contract map

| Boundary | Framework surface | What it controls |
|---|---|---|
| Agent identity | `role`, `capabilities`, `capability_descriptions` | How peers and planners discover the agent |
| Capability authority | `capability_contracts` | Which effects and provider systems a capability may request |
| Task execution | `context["execution_contract"]` | Whether work is a direct response, one artifact, or normal agentic execution |
| Kernel completion | `DONE` plus `RESULT` | Human-facing completion prose and machine-usable result data |
| Output validation | `output_schema` or an application-owned validator | Whether structured output matches the required schema |
| Agent result | `status`, `output`, `result_summary`, telemetry, continuation metadata | The stable boundary returned by `execute_task()` |
| Durable goal | source obligations, revisions, step claims, attempts, interpretations | What was requested, attempted, satisfied, blocked, or superseded |

## Capability contracts

A capability name says what an agent can own. Its contract states the authority
available while performing that capability:

```python
from jarviscore import AutoAgent


class RepositoryReviewer(AutoAgent):
    role = "repository_reviewer"
    capabilities = ["code_review"]
    capability_descriptions = {
        "code_review": "Inspect a change and propose evidence-backed findings.",
    }
    capability_contracts = {
        "code_review": {
            "effects": ["read", "propose"],
            "systems": ["github"],
        },
    }
```

Distributed planning uses this catalog to create executable steps. Peer
execution derives `capability`, `effect`, and `systems` from the published step;
caller context cannot grant itself that authority. Credentials and provider
policy remain separate enforcement boundaries.

## Execution contracts

An execution contract travels in task context and selects the shape of one
AutoAgent turn:

```python
{
    "task": "Classify this incident and explain the decision.",
    "context": {
        "execution_contract": {
            "execution_shape": "single_response",
            "max_output_tokens": 4096,
        }
    },
}
```

| Shape | Behavior |
|---|---|
| omitted | Normal Kernel OODA execution with tools and completion protocol |
| `single_response` | One direct LLM completion; skips planning, tools, and code generation |
| `single_artifact` | One bounded Kernel deliverable; a raw JSON object can satisfy completion |

Use `output_schema` to validate data produced by CoderSubAgent execution. Other
roles, or domains with stronger invariants than one schema, should validate in a
shared application subclass and return only the validated work product.

## Completion and result contracts

Kernel sub-agents use a provider-neutral protocol:

```text
THOUGHT: <reasoning>
DONE: <complete human answer>
RESULT: <JSON or structured value for downstream work>
```

JarvisCore appends this protocol to the execution harness. Most application
prompts should specify the semantics and shape of the deliverable, not redefine
the parser syntax. A shared application subclass may reinforce `RESULT` when it
validates a domain work product.

The coder path has one additional boundary: generated Python assigns its value
to a variable named `result`. That sandbox convention is not required for
`single_response`, and it should not be confused with the outer task envelope.

`AutoAgent.execute_task()` returns the outer envelope. Its stable display field
is `result_summary`; structured data stays in `output` (and the standard Kernel
`payload` alias). Status, errors, token use, cost, dispatches, continuation
metadata, and goal metadata remain separate fields.

## Application work-product contracts

JarvisCore does not know whether a qualified account, code-review finding, legal
memo, or support resolution is valid. The application owns that domain truth.
A production harness commonly defines Pydantic models and validates every agent
handoff before it reaches memory, another peer, or a user interface.

For example, a code-review contract might require a file path, evidence span,
severity, explanation, and actionable remediation. A GTM contract might require
verified account evidence and explicitly forbid a ready outreach plan without a
verified contact. Those rules belong to the application, not the framework.

This division is deliberate:

- JarvisCore enforces execution, authority, lifecycle, and durable-state shapes.
- The application enforces domain evidence and work-product validity.
- The prompt explains how to reason toward a valid result.

## Durable goal contracts

`Mesh.execute_goal()` adds a durable contract around the whole multi-agent goal:

1. The source objective and obligation IDs are immutable.
2. A temporary planning lease publishes a capability-addressed DAG.
3. Eligible peers claim steps independently and append immutable attempts.
4. Optional interpretations map evidence to the exact obligation IDs covered by
   a step.
5. Reconciliation appends a new revision for unresolved obligations without
   erasing prior attempts or repeating satisfied effects.
6. Execution, obligation, and response statuses are reported independently.

An `interpretation` is useful when successful execution does not prove the
source requirement was satisfied. Its `satisfied_requirements` and
`unmet_requirements` must use the stable IDs from the step's `covers` list. The
framework reduces those IDs into current obligation truth; the agent remains
responsible for the domain judgment.

## Choose the right layer

Use a prompt for reasoning method, evidence standards, ownership, tone, and the
meaning of the deliverable. Use a contract for permissions, schemas, terminal
states, durable identity, and machine-readable handoffs. If downstream code
must rely on it, do not leave it only in prose.

Continue with:

- [System Prompts](../guides/system-prompts.md) for sectioned prompt composition;
- [AutoAgent](../guides/autoagent.md) for execution shapes and result envelopes;
- [Workflow DAGs](../guides/workflows.md) for application-authored graphs;
- [Durable Goal Execution](../guides/goal-execution.md) for peer-claimed DAGs,
  obligations, revisions, and interpretations.
