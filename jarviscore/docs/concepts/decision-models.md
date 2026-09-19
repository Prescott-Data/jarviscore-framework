---
icon: material/call-split
title: "TypeSafe Jev Decision Models"
description: "Use TypeSafe Jev Choice, Score, and Noul decisions in JarvisCore agents and optionally for Kernel subagent selection."
---

# Decision Models

JarvisCore supports [TypeSafe Jev](https://docs.typesafe.ai/) for bounded,
machine-consumable judgments. Jev reads text or structured state and returns
typed `Choice`, `Score`, or `Noul` answers with probability evidence. It does
not generate text and does not replace the language model used by `AutoAgent`.

Install the optional SDK and configure an API key:

```bash
pip install "jarviscore-framework[typesafe]"
export TYPESAFE_API_KEY=...
jarviscore check --validate-typesafe
```

The repository includes a complete Mesh and CustomAgent example at
[`examples/typesafe_jev_decisions.py`](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/typesafe_jev_decisions.py).

## Use Jev in a CustomAgent

When TypeSafe is configured, the Mesh injects one shared async client as
`self.decisions` before agent setup. The framework owns its lifecycle and
includes reported usage in the active workflow budget.

```python
from jarviscore import CustomAgent


class TriageAgent(CustomAgent):
    role = "triage"
    capabilities = ["ticket_triage"]

    async def execute_task(self, task):
        result = await self.decisions.evaluate(
            state=task["ticket"],
            questions={
                "department": {
                    "type": "choice",
                    "instructions": "Which team should handle this ticket?",
                    "criteria": {
                        "billing": "Charges, invoices, and subscriptions.",
                        "support": "Product usage and account assistance.",
                        "engineering": "Defects and service incidents.",
                    },
                },
                "urgent": {
                    "type": "noul",
                    "instructions": "Does this ticket require immediate attention?",
                },
            },
        )
        return {"status": "success", "decision": result.to_dict()}
```

The result preserves every answer, its probabilities and confidence where the
primitive provides them, the model, request ID, token usage, and estimated
input cost. Keep this evidence with the decision instead of retaining only the
winning label.

Score levels are keyed by string (`"0"`, `"1"`, `"2"`) in both `legend` and
`probabilities`, so a result read back from a checkpoint is identical to the
one just returned. Compare the numeric `score` against your own threshold; the
legend is descriptive text.

## Use Jev in an AutoAgent

Configured AutoAgents receive an `evaluate_decisions` thinking tool. The agent
can submit explicit state and raw TypeSafe question dictionaries during its
normal OODA loop. Decision results enter the same tool history and checkpoint
path as other observations.

Only state passed to `evaluate_decisions` is sent to TypeSafe. JarvisCore does
not automatically send UnifiedMemory, credentials, workflow history, or the
whole agent context. Do not include secrets unless sending them to TypeSafe is
acceptable for your application.

## Optional Kernel Routing

The Kernel can use Jev to choose among its registered subagent roles:

```bash
export KERNEL_ROUTER_PROVIDER=typesafe
export TYPESAFE_ROUTER_MIN_CONFIDENCE=0.5
```

This changes only model-backed role selection. Explicit execution contracts,
planner hints, profile roles, and deterministic credentialed-system routes
still take precedence and do not make a Jev call. Routing metadata preserves
the selected role, probability distribution, confidence, TypeSafe request ID,
model, usage, and cost.

Do not copy a confidence threshold between applications. Validate thresholds
against your own decision criteria, data, and consequences. A model decision
is not authorization, proof that an action ran, or evidence that a workflow
obligation was satisfied.

## Optional Complexity and Model-Tier Routing

Goal-oriented AutoAgents can use Jev to classify execution shape:

```bash
export TASK_COMPLEXITY_PROVIDER=typesafe
export TYPESAFE_COMPLEXITY_MIN_CONFIDENCE=0.5
```

`trivial` tasks take a direct Kernel turn on the `nano` tier, `moderate` tasks
take a direct turn on the `standard` tier, and `complex` tasks retain the full
Planner path. Explicit execution-shape contracts still win. A Jev answer below
the confidence threshold is treated as `complex`, preserving planning rather
than bypassing it. If the TypeSafe call fails, the existing LLM classifier is
used.

## Optional RAG Passage Decisions

Keep vector search as the fast first stage, then let Jev classify each passage
in the shortlist:

```bash
export RAG_DECISION_PROVIDER=typesafe
export RAG_TYPESAFE_MAX_CONCURRENT=4
```

Each query-passage pair receives four independent Noul scores: relevance,
usable answer evidence, contradiction of the query premise, and prompt
injection. Code applies configured thresholds in that order and returns:

- `accepted_results` and `accepted_evidence`
- `conflicting_results` and `conflicting_evidence`
- `excluded_results`
- the complete original `results`, with every decision and request ID retained

That complete audit shape is returned by `RagPipeline.retrieve_with_decisions()`.
The Researcher tool does not place excluded passage text back into its model
context: it returns accepted and conflicting text plus metadata-only excluded
records.

The prompt-injection score is a filter, not a security boundary. Accepted
passages remain untrusted text, and generation prompts must continue treating
them as data rather than instructions. Thresholds are policy and must be
evaluated against your corpus.

## Appropriate Work

Use Jev for focused judgments with a bounded answer space: classification,
relevance, routing, rubric scoring, and yes/no assessments. Keep generation,
multi-step planning, arithmetic, date comparison, authorization, and durable
execution in their existing owners.

See the [TypeSafe primitives documentation](https://docs.typesafe.ai/primitives)
for question design and current model limitations.

## Measured Behavior

Measured against `jev-1.13.0` from a single developer machine outside the US,
so treat these as a starting point rather than a guarantee. Latency depends on
your region, state size, and question count.

| Observation | Value |
|---|---|
| Three questions in one call | 434 ms median warm, 1.06 s first call |
| Kernel role routing | ~470-500 ms warm |
| Complexity classification | 8/8 expected probe decisions, ~390-493 ms warm |
| Three concurrent RAG passage decisions | 1.28 s total |
| Tokens for a short ticket, three questions | 437 in, 68 out |
| Reported cost for that call | about $0.000018 |

Question count matters far less than call count, because questions in one
request are evaluated in parallel. Ask everything your code might branch on in
a single call rather than issuing several.

Run your own measurement before relying on any number here:

```bash
jarviscore check --validate-typesafe
```
