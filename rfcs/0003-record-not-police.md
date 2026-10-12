# RFC 0003: Record what the agent did; do not police how

Status: proposed
Scope: `jarviscore/kernel` completion checks, research phases, and every runtime
mechanism that decides an agent's next move during a run

The principle: the runtime observes, records and reports; it enforces boundaries
(authorization, human approvals, budgets, receipts, output integrity). The agent decides
its strategy and when its work is sufficient.

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
   no tool is refused because of a phase.
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

## Extension: steering during the run

Completion checks were not the only place the runtime decided for the agent. A trace of
live capital-markets verification showed agents with budget left stopping after three
calls, because the runtime told them to. Each mechanism below was reproduced before it
was changed.

| Mechanism | What it did | Now |
|---|---|---|
| Knowledge plateau | Counted only `research_findings`/`api_specs`, so three successful evidence reads injected "Call DONE with what you have" | Removed |
| Search similarity (`EpistemicLedger`) | Refused a query at Jaccard ≥ 0.7 (a changed trading date was refused at 83%); one similar query rejected a whole batch | Removed; every search runs |
| URL deduplication (`EpistemicLedger`, coder `read_api_docs`) | Refused re-reading a page that may have changed | Removed; an identical call's result notes the earlier receipt and whether the result changed |
| Convergence governor | Forced a strategy pivot after a same-tool streak, then yielded the step with budget left (successful polling included) | Removed; identical-call fact above |
| Failure guard | Refused a call that failed before (a 404), without knowing whether circumstances changed | `FailureLedger` records and classifies; recent failures are shown, never used to refuse |
| Budget coaching | Thresholds injected "Stop gathering … call done now" before the budget ran out | Each turn states remaining tokens, wall clock and turns as facts; the lease still ends the run |
| Exit check | The decision contract asked the agent to justify continuing | Removed |
| Research phase contract | Refused offered tools by a phase guessed from the last call | Removed |
| `RESEARCH_REQUIRE_URL_IDS` | After a batch search, refused `read_web_content(urls=[...])`, even for URLs that search returned | Removed; `url_ids` remain a shorthand |
| `preferred_domains` | Became a mandatory `site:` filter; an unrestricted query found sources the filter hid | A preference: preferred-domain results are listed first, open-web results still returned |
| Coordinate-click block | Refused coordinate clicks when snapshot refs existed | Removed |
| Coder research gate | Refused `delegate_research` until `write_code` had run | Removed |

Runtime facts are a per-turn `## RUNTIME NOTICE (this turn)` block in the prompt. They
are not stored as thoughts, so a checkpoint never carries old guidance into a resumed run.

Kept, because they are boundaries: the execution lease, human approvals for
consequential actions, effect-intent review and application guards, atom contracts,
credential and workspace boundaries, receipt grounding, result shape, products'
`required_tool_groups`, and the identical-rejected-DONE loop bound.

### Consequences

- An agent can poll, re-read a changing page, retry a failed call, or keep researching
  while budget remains. When it stops is its decision, visible in its record.
- A run that loops identically now runs until its lease ends rather than yielding
  early; the identical-call fact makes the loop visible to the agent and in the trace.
- `ConvergenceGovernor`, `EpistemicLedger`, `FailureLedger.is_guarded`, the
  `CONVERGENCE_*`/`FAILURE_GUARD_*` settings and `RESEARCH_STRICT_PHASE_CONTRACT` are
  removed. Subclasses overriding `_allowed_tools_for_phase` keep working but the
  override is no longer called.
