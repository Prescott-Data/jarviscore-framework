# RFC 0003: Record what the agent did; do not police how

Status: proposed
Scope: `jarviscore/kernel` completion checks and research phases

## Problem

A completion check runs when an agent emits DONE and can refuse it. Two kinds have
accumulated in the kernel:

| Check | Reads | Kind |
|---|---|---|
| `tool_receipt_grounding` | the result's own command and workspace claims against tool receipts | work product |
| researcher done payload (`summary`, `evidence`, `api_specs`) | the result's own shape | work product |
| `declared_action_evidence` | tool groups the product declared for the step | product contract |
| `max_identical_done_attempts` | repeated identical rejections | loop bound |
| `research_performed` | whether a search or read ran | process |
| `meaningful_attempt` | whether any tool ran | process |
| `browser_observation` | whether an observation tool ran | process |
| `ResearchPhase` tool contract | which tools the last tool call "unlocks" | process |

The process checks share four failures, all observed in production:

1. **They do not change behaviour.** A model that believes it has the answer resubmits
   it, reworded, until `max_identical_done_attempts` ends the step. The Evidence Engine
   lost verifications to "Completion gate 'claim_was_investigated' unsatisfied after 10
   identical attempts", a product copy of `research_performed`.
2. **They punish correct work.** A direct answer, an upstream result already in context,
   or an evidence dossier supplied by the product all satisfy the task with no tool call,
   and are refused.
3. **They hide the cause.** The refusal names a missing process step, not the fact the
   result lacks, so the trace shows a loop instead of the real gap. In the Evidence
   Engine the real gap was a verdict rule that refused the agent's evidence; the process
   checks masked it for weeks.
4. **They need hidden state.** Phases guessed from the last tool call block the next
   one with no product reason, and an agent cannot see why a tool is suddenly refused.

## Decision

1. **Keep checks that read the work product** (receipt grounding, result shape) and
   **checks the product declares** (`required_tool_groups`). Keep the loop bound.
2. **Remove** `research_performed`, `meaningful_attempt` and `browser_observation`.
3. **Record instead.** Every accepted result carries `metadata["work_record"]`:
   `{tool_name: {"calls": n, "succeeded": m}}`, counted from the tool log. The agent
   cannot write it. The product, a reviewer or a person decides what it supports.
4. **Research phases are recorded, not enforced.** Phases are still traced and stored;
   blocking tools by phase is opt-in with `RESEARCH_STRICT_PHASE_CONTRACT=true`.
5. **Prompts state facts, not orders.** The coder's first turn lists the relevant tools
   and says the run's tools are recorded; it no longer says the agent MUST call one.

A product that needs a step to have searched declares it with `required_tool_groups`,
or checks its own result against its own rules (as the capital-markets verifier does
with verdict admissibility). That is a product decision made in the open, not a kernel
default made in the dark.

## Consequences

- A direct or honest partial answer completes, and its record shows no tools ran.
- Steps that previously failed at the loop bound now return a result whose record shows
  what was and was not done.
- Behaviour that depended on phase gating can restore it with the environment flag.
