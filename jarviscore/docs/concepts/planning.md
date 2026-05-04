---
icon: material/map-outline
---

# Planning

Goal-oriented planning is an opt-in mode for `AutoAgent`. By default, an `AutoAgent` executes each task as a single OODA loop and returns. When planning is enabled, the same task string is treated as a goal: the agent decomposes it into an ordered sequence of steps, executes each one, evaluates whether it succeeded, and revises the plan if something fails.

Planning is available exclusively on `AutoAgent`. `CustomAgent` does not have access to the planning loop.

Two components do this work: the `Planner`, which produces and revises step sequences, and the `StepEvaluator`, which judges each step's outcome and extracts facts that inform the steps that follow.

---

## Enabling Planning

Add `goal_oriented = True` to your `AutoAgent` subclass. That is the only change required.

```python
class ResearchAgent(AutoAgent):
    role = "researcher"
    capabilities = ["research", "analysis"]
    system_prompt = "You are a market researcher..."
    goal_oriented = True   # enables the Plan → Execute → Evaluate loop
```

With this set, every `execute_task()` call is routed through the planning loop automatically. The calling code is unchanged: you still call `mesh.workflow()` with a normal task dict. The response envelope is identical, with one addition: a `goal_execution` key containing a summary of the steps run, facts accumulated, and elapsed time.

Two environment variables allow you to tune the loop without code changes:

```bash
MAX_GOAL_STEPS=30        # hard ceiling on total steps (default: 30)
MAX_REPLAN_ATTEMPTS=8    # max replanning cycles before failing (default: 8)
```


## The Planner

The `Planner` takes a goal string and produces an ordered list of `PlannedStep` objects. Each step has four fields:

- `task`: a complete, self-contained description of what the agent should do. The agent executing this step has no access to any other context, so the task must be fully specified on its own.
- `success_criterion`: a concrete, observable condition that means the step is done. Vague criteria like "research the topic" are rejected; the criterion must be verifiable.
- `expected_findings`: a list of snake_case keys that this step is expected to produce (e.g. `api_base_url`, `row_count`). These keys are used to track what the goal knows.
- `subagent_hint`: an optional routing hint telling the Kernel which sub-agent role to use (`researcher`, `coder`, `communicator`, or `browser`). If omitted, the Kernel classifies from the task text automatically.

The planner enforces a limit of 3 to 10 steps. Plans outside this range are rejected. Each step must be atomic: one agent, one bounded outcome.

The Planner makes a single LLM call using the `heavy` model tier (`TASK_MODEL_HEAVY`). It requests JSON output and validates the response strictly: missing required fields, empty plans, and malformed JSON all raise `PlannerError` immediately. There is no silent fallback to a degraded plan.

---

## The Plan/Replan Cycle

Planning runs in two modes.

**Initial planning** happens once when the goal is first received. The Planner is given the goal, the agent's identity (the first 400 characters of the system prompt), and any known facts accumulated so far (none on the first call). It produces the initial step sequence.

**Replanning** happens after a step fails. The Planner receives the full execution state at the point of failure: every completed step with its verdict, the failed step and the reason it failed, and the facts accumulated so far. It produces a revised plan for the remaining work only. Completed steps are not re-planned. Critically, the prompt instructs the planner to change approach rather than repeat the same failed strategy.

This means the agent is not committed to its initial plan. If a web scraping step fails because a site blocks automated access, the replan can substitute an API-based approach. If a data processing step fails due to schema mismatch, the replan can add a schema inspection step first.

---

## Fact Accumulation

As each step completes, the `StepEvaluator` extracts facts from the step output and adds them to a shared `GoalExecution.truth` store. These facts are included in every subsequent planning call.

This is how a multi-step goal maintains coherence. A researcher step that discovers an API's base URL records `api_base_url` as a fact. The coder step that follows receives that fact in the planner's prompt and can use it directly in generated code, without needing to be told explicitly.

The evaluator's prompt explicitly instructs it not to re-extract facts already present in the accumulated store, so the truth store grows incrementally without duplication.

---

## The StepEvaluator

After each step executes, the `StepEvaluator` decides what happened. It returns one of four verdicts:

| Verdict | Meaning | What happens next |
|---|---|---|
| `pass` | The success criterion is clearly met | Execution continues to the next step |
| `partial` | The criterion is partially met | Execution continues; the shortfall is recorded in the fact store |
| `fail` | The criterion is not met | The goal loop triggers replanning |
| `hitl` | Cannot determine without human judgement | Execution pauses and a HITL request is raised |

The evaluator is designed to be cheap: it makes one focused LLM call using the `nano` tier (`TASK_MODEL_NANO`) because the verdict is a four-way classification, not a reasoning task.

Two outcomes short-circuit the LLM call entirely:

If the step execution returned `status == "failure"`, the evaluator immediately returns `fail` without calling the LLM. The agent already knows it failed.

If the step returned `status == "yield"`, the evaluator checks the yield type. Routine budget exhaustion (`YIELD_BUDGET_EXHAUSTED`, `YIELD_LEASE_EXHAUSTED`, `YIELD_EMERGENCY_TURN_FUSE`) is treated as `partial`, not `hitl`. The goal loop replans with smaller, more bounded steps rather than pausing for human review. Only convergence stalls — where the agent tried multiple strategies and still could not make progress — produce a genuine `hitl` verdict.

---

## Subagent Routing from the Plan

The `subagent_hint` in each `PlannedStep` is a routing recommendation. The Kernel treats it as an override: if the hint is set and valid, the Kernel dispatches directly to that sub-agent role rather than classifying the task by keyword.

The Planner normalises hints aggressively. Common LLM hallucinations like `analyst`, `architect`, `writer`, and `developer` are remapped to the nearest valid role. Unknown hints that cannot be resolved via alias or fuzzy matching are silently dropped to `null`, letting the Kernel classify automatically from the task text. The plan is never rejected over a bad hint.

Valid routing hints are: `researcher`, `coder`, `communicator`, `browser`.

---

## When Planning Fails

A `PlannerError` is a hard failure. The Planner does not retry with a degraded plan and does not silently return a partial result. If the LLM call fails, the JSON is malformed, the response contains no valid steps array, or a step is missing `task` or `success_criterion`, the error surfaces immediately to the caller.

The goal execution layer handles this by marking the goal as failed. There is no automatic retry of the planning call itself — planning failures typically indicate a prompt issue, a model configuration issue, or an unreachable LLM, none of which benefit from a blind retry.

An `EvaluatorError` follows the same pattern: invalid or unparseable evaluation responses raise immediately rather than defaulting to any verdict.

---

## Further Reading

- [Architecture Overview](./architecture.md), how the Planner and Kernel fit into the AutoAgent execution model
- [Model Routing](./model-routing.md), the heavy tier used by the Planner and the nano tier used by the StepEvaluator
- [HITL Escalation](../guides/hitl.md), what happens when the StepEvaluator returns a `hitl` verdict
- [Workflow DAGs](../guides/workflows.md), structuring multi-step goals with explicit dependencies
