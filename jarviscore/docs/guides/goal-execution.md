---
icon: material/graph
title: Durable Multi-Agent Goal Execution Without a Central Router
description: Compile natural-language goals into durable capability-addressed DAGs that AI agents claim independently, reconcile, resume, and audit.
---

# Durable Goal Execution

`Mesh.execute_goal()` turns one natural-language objective into durable,
capability-addressed work. Redis holds the source goal, obligations, revisions,
claims and outputs; peers claim work independently. Planning does not create a
manager agent and the node that publishes a plan has no execution authority.

This API is different from the other two ways to run work:

| API | Use it when | Who defines the steps |
|---|---|---|
| `agent.execute_goal()` | One `AutoAgent` should run its own Plan, Execute, Evaluate loop | That AutoAgent |
| `mesh.workflow()` | Your application already knows the DAG | Your Python code |
| `mesh.execute_goal()` | The goal should be compiled into distributed, capability-addressed work | A temporary planning lease |

```mermaid
flowchart TB
    Source["Source goal and obligations"] --> Plan["Temporary planning lease"]
    Plan --> DAG["Capability-addressed DAG"]
    DAG --> Claims["Independent peer claims"]
    Claims --> Attempts["Immutable attempts and evidence"]
    Attempts --> Truth{"Current obligations satisfied?"}
    Truth -->|Yes| Final["Current-revision final response"]
    Truth -->|Actionable gap| Delta["Append selective revision"]
    Delta --> Claims
    Truth -->|No valid remediation| Blocked["Durable blocked settlement"]
```

## Define capability authority

Every participating agent declares capability names. For provider work, add a
capability contract so planning knows which effects and systems that capability
may use:

```python
from jarviscore import AutoAgent, Mesh


class RevenueOperations(AutoAgent):
    role = "revenue_operations"
    capabilities = ["pipeline_inspection"]
    capability_descriptions = {
        "pipeline_inspection": "Inspect and reconcile CRM pipeline state.",
    }
    capability_contracts = {
        "pipeline_inspection": {
            "effects": ["read", "propose"],
            "systems": ["hubspot"],
        },
    }


mesh = Mesh(config={
    "mesh_response_capability": "action_briefing",
    "execution_budget": {
        "max_seconds": 900,
        "max_tokens": 240_000,
        "max_epochs_per_step": 8,
    },
})
mesh.add(RevenueOperations)
```

Effects are `read`, `propose`, `write`, `notify`, `destructive` or
`final_response`. A `write`, `notify` or `destructive` step names exactly one
authorized system. The claiming peer still decides which atom or provider call
to use.

At least one started node needs an agent with an LLM for initial planning and
reconciliation decisions. A pure `CustomAgent` node can execute published work,
but it does not gain an LLM planner automatically.

## Execute and inspect a goal

```python
await mesh.start()

result = await mesh.execute_goal(
    "Inspect the active opportunity and prepare a decision brief.",
    workflow_id="opportunity-2026-09-11",
    context={"tenant_id": "acme"},
)

print(result["status"])
print(result["obligation_status"])
print(result["response_status"])
```

Caller context is copied without private keys or execution authority. The
framework derives capability, effect and systems from the published step and
injects them into the claiming agent's task context.

Source-backed products should set `workspace_required=True`. Source resolution
and snapshot integrity validation then complete before the goal is registered or
the planner sees it. Explicit structured context is accepted from APIs and CLIs;
message-only clients rely on the Mesh's provider-constrained source preflight.
Missing source identity, unavailable adapters and invalid snapshots fail the
request instead of producing a source-less DAG.

## Task context received by agents

Both `AutoAgent.execute_task()` and `CustomAgent.execute_task()` receive the
same distributed context:

| Key | Meaning |
|---|---|
| `objective` | Exact immutable source goal |
| `workflow_plan` | Goal, obligation ledger and all revisioned step definitions |
| `previous_step_results` | Durable dependency artifacts; all workflow artifacts for a final response |
| `previous_step_interpretations` | Semantic assessments from dependencies |
| `workflow_id`, `step_id` | Durable execution identity |
| `capability`, `effect`, `systems` | Authority declared by the published step |
| `execution_budget` | Shared workflow budget |
| `workflow_evidence` | Final-response snapshot of artifact IDs, interpretations, states and obligations; full artifacts remain in `previous_step_results` |

An exhausted execution epoch may continue from its durable checkpoint, up to
`max_epochs_per_step`. A request larger than an entire epoch is terminal because
starting another identical epoch cannot make it fit.

## Completion is evidence-derived

`DONE` is an agent proposal to evaluate the current durable state. It is not a
state transition by itself. Normal turns and budget-exhaustion landing turns use
the same completion evaluator. Rejected completion preserves tool history,
thoughts, failures and work-product state; actionable lease exhaustion continues
in a fresh bounded epoch rather than becoming a human wait. When repeated
completion proposals leave the same actionable gate unsatisfied, that boundary
also checkpoints the same state; the next epoch receives the gate evidence as
its critical error instead of restarting an equivalent dispatch.

Products may declare `execution_contract.required_tool_groups`. Each group lists
equivalent tools, and durable history must contain at least one invocation from
every group before completion is eligible. The gate reports observed tools and
missing groups; it does not decide domain truth or choose the next action.
Changing result wording without changing the observed evidence or performing a
new tool action is not progress and cannot reset the no-progress boundary.

Existing agents do not need to change. A successful result without an
`interpretation` is reduced from execution status: a completed attempt satisfies
the obligations covered by that step.

## Optional semantic interpretations

Return an interpretation when domain evidence can distinguish "the attempt
completed" from "the source requirement is satisfied". This is how an agent
can hold or reject its assigned path without teaching JarvisCore domain rules.

```python
async def execute_task(self, task):
    artifact = await self.inspect_pipeline(task)
    plan = task["context"]["workflow_plan"]
    step = next(item for item in plan["steps"] if item["id"] == task["id"])
    covered = list(step["covers"])

    if artifact["stage"] is None:
        interpretation = {
            "meaning": "The deal exists, but its current stage is not verified.",
            "satisfied_requirements": [],
            "unmet_requirements": covered,
            "evidence_refs": [artifact["record_id"]],
            "verdict": "unsatisfied",
            "decision": "hold",
        }
    else:
        interpretation = {
            "meaning": "The current deal stage was read from the CRM.",
            "satisfied_requirements": covered,
            "unmet_requirements": [],
            "evidence_refs": [artifact["record_id"]],
            "verdict": "satisfied",
            "decision": "proceed",
        }

    return {
        "status": "success",
        "output": artifact,
        "interpretation": interpretation,
    }
```

`satisfied_requirements` and `unmet_requirements` contain the stable obligation
IDs from the current step's `covers` list, not paraphrased descriptions. Assess
each covered ID exactly once. Recommended verdicts are `satisfied`, `partial`
and `unsatisfied`; recommended decisions are `proceed`, `hold` and `reject`.

A framework-owned final-response step has `covers=[]`. It presents current
workflow truth and cannot satisfy source obligations. When multiple steps in one
dependency path mention the same obligation, only terminal domain work retains
coverage; ancestor steps remain evidence for that terminal judgment.

Step dependencies use `dependency_policy="satisfied"` by default. Redis decides
whether dependencies are execution-ready; the recipient peer decides whether a
completed dependency's semantic uncertainty materially prevents its task. A
planner may set `dependency_policy="terminal_evidence"` only for work explicitly
intended to diagnose or remediate a failed or blocked attempt. Final-response
steps always receive terminal evidence so they can explain blocked and incomplete
goals.

## Current obligation truth

Attempts are immutable execution history. The obligation projection records
which attempts currently represent each source requirement:

```mermaid
flowchart LR
    R1["Revision 1<br/>inspect_deal<br/>unresolved"]
    R2["Revision 2<br/>inspect_deal_by_id<br/>satisfied"]
    R1 -->|"superseded for this obligation"| R2
    R1 -.-> Audit["Retained audit history"]
    R2 --> Current["Current obligation evidence"]
```

The revision 1 output remains available for audit. Revision 2 supersedes it only
for the obligation IDs covered by the new step. Satisfied obligations not named
by the delta retain their current source attempt and are not rerun.

Automatic reconciliation starts only after the current revision is terminal,
an unresolved obligation has semantic evidence, an LLM planner is available and
the revision budget permits another attempt. The planner may append remediation
or settle the remaining goal as blocked. It cannot rewrite the source obligation
ledger or mutate earlier attempts.

`Mesh.replan_goal()` uses the same append-only mechanism for explicit
continuation. Call it only while obligations remain unresolved:

```python
result = await mesh.replan_goal(
    "opportunity-2026-09-11",
    reason="A direct CRM record-read capability is now available.",
)
```

## Read terminal status correctly

The result reports three independent facts:

| Field | Values | Question answered |
|---|---|---|
| `status` | `completed`, `failed`, `waiting`, `cancelled` | Did the current revision execute? |
| `obligation_status` | `satisfied`, `blocked`, `incomplete` | Is the source goal fulfilled? |
| `response_status` | `completed`, `failed`, `waiting`, `not_required` | Was the current user-facing response produced? |

Do not infer goal truth from `status` alone. For example, provider actions may
be complete while response synthesis fails:

```python
{
    "status": "failed",
    "obligation_status": "satisfied",
    "response_status": "failed",
}
```

Agent Desk renders `completed` as **Execution finished**. The result separately
renders **Goal satisfied**, **Goal blocked** or **Goal incomplete** from
`obligation_status`.

`revision` identifies the current plan. `steps` retains attempts from every
revision; filter with `step["plan_revision"] == result["revision"]` when you
need only current execution. `result_summary` is selected from the current
revision's final response.

## Waiting, cancellation and shutdown

Resume a waiting step with the same workflow and step identity:

```python
result = await mesh.resume_goal(
    workflow_id,
    step_id,
    context={"human_response": "approved"},
)
```

Cancellation is durable. It fences future claims and prevents an expired
executor from committing after cancellation:

```python
mesh.cancel_goal(workflow_id, reason="Request withdrawn")
```

Cancelling the coroutine running `execute_goal()` also cancels the durable
workflow before re-raising `CancelledError`.

## Deployment rules

- Redis is required for `Mesh.execute_goal()`, resume, replan and cancellation.
- Use stable `workflow_id` values for retry and observation.
- Run compatible framework versions on every node that can claim the same DAG.
- Bound reconciliation with `mesh_max_reconciliation_revisions` and the shared
  `execution_budget`.
- Configure `mesh_response_capability` only when a peer owns
  `final_response` authority.