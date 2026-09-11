"""Compile a source goal into a validated capability-addressed mesh DAG."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


class MeshPlanError(ValueError):
    """The proposed plan cannot faithfully and safely enter the shared ledger."""


@dataclass(frozen=True)
class GoalObligation:
    id: str
    description: str
    source_quote: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "source_quote": self.source_quote,
        }


@dataclass(frozen=True)
class MeshPlannedStep:
    step_id: str
    capability: str
    effect: str
    systems: list[str]
    task: str
    success_criterion: str
    expected_findings: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    covers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.step_id,
            "capability": self.capability,
            "effect": self.effect,
            "systems": list(self.systems),
            "task": self.task,
            "success_criterion": self.success_criterion,
            "expected_findings": list(self.expected_findings),
            "depends_on": list(self.depends_on),
            "covers": list(self.covers),
        }


@dataclass(frozen=True)
class MeshPlan:
    goal: str
    obligations: list[GoalObligation]
    steps: list[MeshPlannedStep]
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "obligations": [item.to_dict() for item in self.obligations],
            "steps": [step.to_dict() for step in self.steps],
            "revision": self.revision,
        }


class MeshPlanner:
    """Produce work requirements; Redis claims decide which peer executes them."""

    def __init__(
        self,
        llm_client,
        capabilities: dict[str, Any],
        response_capability: str | None = None,
    ):
        self.llm = llm_client
        all_effects = {
            "read", "propose", "write", "notify", "destructive", "final_response"
        }
        self.capability_contracts = {}
        for name, offering in capabilities.items():
            if isinstance(offering, dict):
                effects = {str(value) for value in offering.get("effects", [])}
                systems = [str(value) for value in offering.get("systems", [])]
                description = str(offering.get("description") or name)
            else:
                effects = set(all_effects)
                systems = []
                description = str(offering)
            if not effects or not effects <= all_effects:
                raise MeshPlanError(f"Capability {name!r} has invalid effect authority")
            self.capability_contracts[str(name)] = {
                "description": description,
                "effects": effects,
                "systems": systems,
            }
        self.capabilities = {
            name: contract["description"]
            for name, contract in self.capability_contracts.items()
        }
        self.response_capability = response_capability
        if response_capability and response_capability not in self.capabilities:
            raise MeshPlanError(
                f"Configured response capability {response_capability!r} is unavailable"
            )
        if (
            response_capability
            and "final_response"
            not in self.capability_contracts[response_capability]["effects"]
        ):
            raise MeshPlanError(
                f"Configured response capability {response_capability!r} "
                "does not authorize final_response"
            )

    async def plan(self, goal: str, context: dict[str, Any] | None = None) -> MeshPlan:
        source = (goal or "").strip()
        if not source:
            raise MeshPlanError("A mesh goal cannot be empty")
        if not self.capabilities:
            raise MeshPlanError("No mesh capabilities are available")
        obligation_raw = await self._call_json(self._obligation_prompt(source))
        try:
            obligations = self._parse_obligations(obligation_raw, source)
        except MeshPlanError as first_error:
            try:
                repaired_raw = await self._call_json(
                    self._obligation_repair_prompt(
                        source, obligation_raw, str(first_error)
                    )
                )
                obligations = self._parse_obligations(repaired_raw, source)
            except Exception as repair_error:
                raise MeshPlanError(
                    f"{first_error}; obligation repair failed: {repair_error}"
                ) from repair_error
        step_raw = await self._call_json(
            self._step_prompt(source, obligations, context or {})
        )
        steps = self._ensure_response_step(self._parse_steps(step_raw, obligations))
        plan = MeshPlan(goal=source, obligations=obligations, steps=steps)
        audit = await self._call_json(self._audit_prompt(plan))
        first_failure = audit.get("missing") or audit
        for repair_attempt in range(1, 3):
            if audit.get("complete") is True and not audit.get("missing"):
                return plan
            try:
                corrected_obligations = audit.get("obligations")
                if corrected_obligations is not None:
                    obligations = self._parse_obligations(
                        {"obligations": corrected_obligations}, source
                    )
                    repair_raw = await self._call_json(
                        self._step_prompt(source, obligations, context or {})
                    )
                else:
                    repair_raw = await self._call_json(
                        self._repair_prompt(plan, audit, context or {})
                    )
                repaired_steps = self._ensure_response_step(
                    self._parse_steps(repair_raw, obligations)
                )
                plan = MeshPlan(
                    goal=source,
                    obligations=obligations,
                    steps=repaired_steps,
                )
                audit = await self._call_json(self._audit_prompt(plan))
            except Exception as exc:
                raise MeshPlanError(
                    f"Mesh plan failed coverage audit: {first_failure}; "
                    f"repair {repair_attempt} failed: {exc}"
                ) from exc
        if audit.get("complete") is not True or audit.get("missing"):
            raise MeshPlanError(
                "Mesh plan failed coverage audit after two repairs: "
                f"{audit.get('missing') or audit}"
            )
        return plan

    async def amend(
        self,
        goal: str,
        *,
        obligations: list[dict[str, Any]],
        target_obligation_ids: set[str] | None = None,
        current_steps: list[dict[str, Any]],
        reason: str,
        revision: int,
        context: dict[str, Any] | None = None,
    ) -> MeshPlan:
        """Plan only new work against immutable workflow history."""
        source = (goal or "").strip()
        parsed_obligations = self._parse_obligations(
            {"obligations": obligations}, source
        )
        obligation_ids = {item.id for item in parsed_obligations}
        targets = (
            obligation_ids
            if target_obligation_ids is None
            else set(target_obligation_ids)
        )
        if not targets or not targets <= obligation_ids:
            raise MeshPlanError("Amendment targets must be known source obligations")
        step_raw = await self._call_json(
            self._amendment_prompt(
                source,
                parsed_obligations,
                targets,
                current_steps,
                reason,
                context or {},
            )
        )
        current_ids = {
            str(step.get("id") or step.get("step_id"))
            for step in current_steps
        }
        try:
            steps = self._ensure_response_step(
                self._parse_steps(
                    step_raw, parsed_obligations,
                    allowed_dependency_ids=current_ids,
                    forbidden_step_ids=current_ids,
                    required_obligation_ids=targets,
                    allowed_cover_ids=targets,
                ),
                reserved_ids=current_ids,
            )
        except MeshPlanError as first_error:
            last_error = first_error
            for repair_attempt in range(1, 3):
                try:
                    step_raw = await self._call_json(
                        self._invalid_amendment_repair_prompt(
                            source,
                            parsed_obligations,
                            current_steps=current_steps,
                            rejected=step_raw,
                            reason=reason,
                            validation_error=str(last_error),
                        )
                    )
                    steps = self._ensure_response_step(
                        self._parse_steps(
                            step_raw, parsed_obligations,
                            allowed_dependency_ids=current_ids,
                            forbidden_step_ids=current_ids,
                            required_obligation_ids=targets,
                            allowed_cover_ids=targets,
                        ),
                        reserved_ids=current_ids,
                    )
                    break
                except Exception as exc:
                    last_error = exc
            else:
                raise MeshPlanError(
                    f"Mesh amendment draft is invalid: {first_error}; "
                    f"repair failed: {last_error}"
                ) from last_error
        plan = MeshPlan(
            goal=source,
            obligations=parsed_obligations,
            steps=steps,
            revision=revision + 1,
        )
        audit = await self._call_json(self._amendment_audit_prompt(
            plan, current_steps=current_steps, reason=reason,
        ))
        first_failure = audit.get("missing") or audit
        for repair_attempt in range(1, 3):
            if audit.get("complete") is True and not audit.get("missing"):
                return plan
            try:
                repair_raw = await self._call_json(self._amendment_repair_prompt(
                    plan,
                    audit=audit,
                    current_steps=current_steps,
                    reason=reason,
                ))
                repaired_steps = self._ensure_response_step(
                    self._parse_steps(
                        repair_raw, parsed_obligations,
                        allowed_dependency_ids=current_ids,
                        forbidden_step_ids=current_ids,
                        required_obligation_ids=targets,
                        allowed_cover_ids=targets,
                    ),
                    reserved_ids=current_ids,
                )
                plan = MeshPlan(
                    goal=source,
                    obligations=parsed_obligations,
                    steps=repaired_steps,
                    revision=revision + 1,
                )
                audit = await self._call_json(self._amendment_audit_prompt(
                    plan, current_steps=current_steps, reason=reason,
                ))
            except Exception as exc:
                if repair_attempt == 2:
                    raise MeshPlanError(
                        f"Mesh amendment failed coverage audit: {first_failure}; "
                        f"repair {repair_attempt} failed: {exc}"
                    ) from exc
                audit = {
                    "complete": False,
                    "missing": [f"Repair draft failed validation: {exc}"],
                }
        if audit.get("complete") is True and not audit.get("missing"):
            return plan
        raise MeshPlanError(
            "Mesh amendment failed coverage audit after two repairs: "
            f"{audit.get('missing') or audit}"
        )

    async def reconciliation_decision(
        self,
        goal: str,
        *,
        obligations: list[dict[str, Any]],
        current_steps: list[dict[str, Any]],
        revision: int,
    ) -> dict[str, str]:
        """Decide whether semantic gaps require another bounded DAG revision."""
        raw = await self._call_json(self._reconciliation_prompt(
            goal, obligations, current_steps, revision,
        ))
        unknown = set(raw) - {"decision", "reason"}
        decision = str(raw.get("decision") or "").strip().lower()
        reason = str(raw.get("reason") or "").strip()
        if unknown or decision not in {"amend", "settle_blocked"} or not reason:
            raise MeshPlanError(
            "Semantic reconciliation requires exactly "
            "decision=amend|settle_blocked and reason"
            )
        return {"decision": decision, "reason": reason}

    def _ensure_response_step(
        self,
        steps: list[MeshPlannedStep],
        reserved_ids: set[str] | None = None,
    ) -> list[MeshPlannedStep]:
        capability = self.response_capability
        active_response = any(
            step.capability == capability
            for step in steps
        )
        if not capability or active_response:
            return steps
        depended_on = {
            dependency for step in steps for dependency in step.depends_on
        }
        sinks = [step.step_id for step in steps if step.step_id not in depended_on]
        existing_ids = {step.step_id for step in steps} | (reserved_ids or set())
        step_id = "final_response"
        suffix = 2
        while step_id in existing_ids:
            step_id = f"final_response_{suffix}"
            suffix += 1
        return [
            *steps,
            MeshPlannedStep(
                step_id=step_id,
                capability=capability,
                effect="final_response",
                systems=[],
                task=(
                    "Synthesize the completed peer artifacts into the explicit "
                    "user-facing response. State the outcome and direct reason "
                    "concisely; keep workflow internals in the artifact only."
                ),
                success_criterion=(
                    "A concise user response states the outcome and direct reason "
                    "without workflow IDs, step IDs, evidence pointers or trace details."
                ),
                expected_findings=["user-facing outcome"],
                depends_on=sinks,
                covers=[],
            ),
        ]

    async def _call_json(self, prompt: str) -> dict[str, Any]:
        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
        except TypeError:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        text = content.strip()
        if text.startswith("```"):
            text = "\n".join(
                line for line in text.splitlines()
                if not line.strip().startswith("```")
            ).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MeshPlanError(f"Mesh planner response is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise MeshPlanError("Mesh planner response must be a JSON object")
        return parsed

    @staticmethod
    def _obligation_prompt(goal: str) -> str:
        return f"""Extract the complete obligation ledger from one source goal.

SOURCE GOAL:
{goal}

Return one valid json object with `obligations`. Each obligation has exactly:
id, description, source_quote.
- source_quote is an exact non-empty quote from SOURCE GOAL.
- capture every requested outcome, constraint, prohibition, approval boundary,
  fallback condition, scope limit and evidence requirement.
- split independently verifiable obligations; do not add or execute work.
- a named workflow or playbook is context, not another obligation, when the source
    immediately defines it through independently verifiable outcomes.
- do not emit an umbrella obligation whose only success criterion is completion
    of other obligations in the same ledger."""

    @staticmethod
    def _obligation_repair_prompt(
        goal: str,
        invalid: dict[str, Any],
        validation_error: str,
    ) -> str:
        return f"""Repair one invalid obligation extraction against immutable source text.

SOURCE GOAL (immutable):
{goal}

INVALID OBLIGATIONS:
{json.dumps(invalid, ensure_ascii=False)}

VALIDATION ERROR:
{validation_error}

Return one valid json object with `obligations`. Each obligation has exactly:
id, description, source_quote.
- Every source_quote must be one contiguous exact substring of SOURCE GOAL.
- Preserve the intended meaning of every invalid obligation.
- Do not add, remove, merge or split obligations.
- Do not execute work or add requirements."""

    def _step_prompt(
        self,
        goal: str,
        obligations: list[GoalObligation],
        context: dict[str, Any],
    ) -> str:
        catalog = self._render_capability_catalog()
        public_context = {
            key: value for key, value in context.items() if not str(key).startswith("_")
        }
        return f"""Compile one goal into a complete peer-executable DAG.

SOURCE GOAL (preserve exactly):
{goal}

IMMUTABLE OBLIGATION LEDGER:
{json.dumps([item.to_dict() for item in obligations], ensure_ascii=False)}

LIVE CAPABILITY CATALOG:
{catalog}

PUBLIC CONTEXT:
{json.dumps(public_context, ensure_ascii=False, default=str)}

Return one valid json object with `steps`. Each step has exactly:
step_id, capability, effect, systems, task, success_criterion,
expected_findings, depends_on, covers.
- capability must come from LIVE CAPABILITY CATALOG.
- effect must be exactly one of: read, propose, write, notify, destructive, final_response.
- systems lists every provider the step will call and must be authorized by the capability.
- write, notify and destructive outcomes must name exactly one provider in systems.
- covers contains obligation ids satisfied by the step.
- use capabilities, never an agent ID or named instance.
- reason about the information required to execute each effectful outcome. Every
    required fact must come from the source goal or an ancestor step whose task and
    success criterion resolve it. naming an entity does not supply its provider identifiers.
- when downstream work needs an artifact's contents, the producing step must inspect
    and return provider-readback evidence of usable content; a matching name, identifier,
    link or MIME type proves resource identity, not content sufficiency.
- declare only real data dependencies; independent work should run in parallel only
    when neither outcome needs information discovered by the other.
- each task must include enough scope and constraints to execute independently.
- model business outcomes, not provider calls or conditional branches.
- keep an inspect-or-create, inspect-or-update, or check-then-act decision as one provider-owned outcome.
  Use its mutating effect and one provider; the claiming peer receives both read and
  authorized mutation tools and decides from current state.
- a provider-owned outcome may resolve its own provider identifiers, folders, records,
    and links before conditionally mutating; state that discovery explicitly in its task
    and success criterion instead of inventing provider-call steps.
- never make an always-required downstream outcome depend on an optional
  mutation-only branch.

Do not assign peers, choose winners, execute work or add requirements."""

    def _repair_prompt(
        self,
        plan: MeshPlan,
        audit: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        public_context = {
            key: value for key, value in context.items() if not str(key).startswith("_")
        }
        return f"""Repair one rejected peer-executable DAG before publication.

SOURCE GOAL (immutable):
{plan.goal}

OBLIGATION LEDGER (immutable):
{json.dumps([item.to_dict() for item in plan.obligations], ensure_ascii=False)}

REJECTED DAG:
{json.dumps([step.to_dict() for step in plan.steps], ensure_ascii=False)}

INDEPENDENT AUDIT FINDINGS:
{json.dumps(audit, ensure_ascii=False)}

LIVE CAPABILITY CATALOG:
{self._render_capability_catalog()}

PUBLIC CONTEXT:
{json.dumps(public_context, ensure_ascii=False, default=str)}

Return one valid json object with a complete replacement `steps` list. Each step
has exactly: step_id, capability, effect, systems, task, success_criterion,
expected_findings, depends_on, covers.
- resolve every audit finding without changing or adding obligations.
- use capabilities, never agent IDs, named instances, atom names, or provider calls.
- model business outcomes, not conditional branches.
- keep inspect-or-create and check-then-act work as one provider-owned outcome;
    its peer decides from current state whether the authorized mutation is necessary.
- provider-owned outcomes should absorb missing same-provider resource discovery and
    return concrete identifiers or links needed by dependents.
- mutating outcomes use exactly one provider and an effect authorized by capability.
- never make required downstream work depend on an optional mutation-only branch.
- repair missing information dependencies: every effectful outcome must receive the
    facts needed to fulfill the source objective from the source goal or an ancestor.
- preserve real data dependencies and allow independent outcomes to run in parallel.

Do not execute work or add requirements."""

    def _amendment_prompt(
        self,
        goal: str,
        obligations: list[GoalObligation],
        target_obligation_ids: set[str],
        current_steps: list[dict[str, Any]],
        reason: str,
        context: dict[str, Any],
    ) -> str:
        catalog = self._render_capability_catalog()
        ledger = self._amendment_ledger_view(current_steps)
        return f"""Amend the unfinished portion of one capability-addressed DAG.

SOURCE GOAL (immutable):
{goal}

OBLIGATION LEDGER (immutable):
{json.dumps([item.to_dict() for item in obligations], ensure_ascii=False)}

UNRESOLVED OBLIGATION IDS (the only obligations this delta may cover):
{json.dumps(sorted(target_obligation_ids), ensure_ascii=False)}

CURRENT STEP DEFINITIONS (return using the normal step schema):
{json.dumps(ledger["definitions"], ensure_ascii=False, default=str)}

AUTHORITATIVE STEP OUTCOMES (reason from these; do not copy runtime fields):
{json.dumps(ledger["outcomes"], ensure_ascii=False, default=str)}

AMENDMENT REASON:
{reason}

LIVE CAPABILITY CATALOG:
{catalog}

PUBLIC CONTEXT:
{json.dumps(context, ensure_ascii=False, default=str)}

Return one valid json object containing only NEW `steps`. Each step has exactly:
step_id, capability, effect, systems, task, success_criterion,
expected_findings, depends_on, covers.
- do not reproduce, alter or remove any current step.
- every step_id must be new; current step ids may only appear in depends_on.
- semantic hold or rejection on a completed attempt may be remediated only by adding
    concrete new work that depends on its durable artifact; never alter or rerun the attempt.
- preserve completed effects as immutable facts and do not add work that repeats them.
- cover every UNRESOLVED OBLIGATION ID exactly through new work and preserve
    dependencies on completed work; `covers` must not contain any other obligation id.
- capability must come from LIVE CAPABILITY CATALOG.
- effect must be exactly one of: read, propose, write, notify, destructive, final_response.
- systems lists every provider the step will call and must be authorized by the capability.
- write, notify and destructive outcomes must name exactly one provider in systems.
- use capabilities, never an agent ID or named instance.

Do not assign peers, execute work, change completed work or add requirements."""

    def _reconciliation_prompt(
        self,
        goal: str,
        obligations: list[dict[str, Any]],
        current_steps: list[dict[str, Any]],
        revision: int,
    ) -> str:
        return f"""Reconcile one terminal mesh DAG against its source obligations.

SOURCE GOAL (immutable):
{goal}

OBLIGATION LEDGER (immutable):
{json.dumps(obligations, ensure_ascii=False, default=str)}

TERMINAL STEP LEDGER (authoritative artifacts and semantic interpretations):
{json.dumps(current_steps, ensure_ascii=False, default=str)}

CURRENT REVISION: {revision}

LIVE CAPABILITY CATALOG:
{self._render_capability_catalog()}

Return exactly one json object with `decision` and `reason`.
- decision=`amend` only when an unmet or partially met source obligation can be
  advanced by concrete new work authorized by the live capability catalog.
- decision=`settle_blocked` only when the remaining gaps require unavailable
    authority, missing human input, or facts no available capability can obtain.
- this decision is invoked only while obligation gaps exist; never claim all source
    obligations are satisfied here. Satisfaction is derived after those gaps close.
- treat completed effects and provider identities as authoritative world state;
  never propose repeating an already completed effect.
- reason identifies the remaining obligation and why another DAG revision can or
  cannot make progress.

Do not choose tools, name atoms, execute work, alter completed artifacts, or add obligations."""

    @staticmethod
    def _amendment_audit_prompt(
        plan: MeshPlan,
        *,
        current_steps: list[dict[str, Any]],
        reason: str,
    ) -> str:
        completed = [step for step in current_steps if step.get("status") == "completed"]
        ledger = MeshPlanner._amendment_ledger_view(completed)
        return f"""Audit one reconciled mesh DAG against immutable completed history.

SOURCE GOAL:
{plan.goal}

OBLIGATIONS:
{json.dumps([item.to_dict() for item in plan.obligations], ensure_ascii=False)}

COMPLETED ATTEMPT DEFINITIONS (immutable historical facts):
{json.dumps(ledger["definitions"], ensure_ascii=False, default=str)}

AUTHORITATIVE ATTEMPT OUTCOMES:
{json.dumps(ledger["outcomes"], ensure_ascii=False, default=str)}

RECONCILIATION REASON:
{reason}

PROPOSED NEW-STEP DELTA:
{json.dumps([step.to_dict() for step in plan.steps], ensure_ascii=False)}

Return exactly one json object: {{"complete": true, "missing": []}} only when:
- every proposed step is new and completed history is left untouched;
- new work can advance the reconciliation reason using available dependencies;
- no new step repeats a provider effect whose authoritative outcome says it executed;
- every immutable obligation remains covered by completed history or executable new work;
- a fresh final response follows the new terminal work when one is configured.

Durable step status `completed` means the attempt ended; it does not prove its provider
effect executed. Use typed output `execution_state`, semantic decision and provider evidence
to determine effect truth. A new effectful step may remediate a completed attempt whose
authoritative outcome is blocked or `not_executed`, but must not repeat an already executed
provider outcome. A capability-change amendment may advance only the blocked obligations named
by its reconciliation reason; other obligations already represented by completed blocked
attempts may remain unresolved history and do not require invented replacement work. Do not
retroactively reject, reorder or demand prerequisites for an effect that actually executed.
Audit only whether new work safely advances the named semantic gaps.
Otherwise return complete=false with `missing` entries describing the amendment defect."""

    @staticmethod
    def _amendment_repair_prompt(
        plan: MeshPlan,
        *,
        audit: dict[str, Any],
        current_steps: list[dict[str, Any]],
        reason: str,
    ) -> str:
        completed = [
            step for step in current_steps if step.get("status") == "completed"
        ]
        ledger = MeshPlanner._amendment_ledger_view(completed)
        return f"""Repair one rejected reconciliation amendment.

SOURCE GOAL (immutable):
{plan.goal}

OBLIGATION LEDGER (immutable):
{json.dumps([item.to_dict() for item in plan.obligations], ensure_ascii=False)}

COMPLETED STEP DEFINITIONS (reproduce each exactly using the normal step schema):
{json.dumps(ledger["definitions"], ensure_ascii=False, default=str)}

COMPLETED OUTCOMES (reason from these; do not copy runtime fields):
{json.dumps(ledger["outcomes"], ensure_ascii=False, default=str)}

RECONCILIATION REASON:
{reason}

REJECTED NEW-STEP DELTA:
{json.dumps([step.to_dict() for step in plan.steps], ensure_ascii=False)}

AUDIT FINDINGS:
{json.dumps(audit, ensure_ascii=False, default=str)}

Return one valid json object containing only NEW `steps` using the normal step
schema. Current step ids may appear only in depends_on. Add remediation work after
completed history and a distinct final response after its sinks when configured.
Never repeat a completed effect, alter source obligations, choose tools, or name atoms."""

    def _invalid_amendment_repair_prompt(
        self,
        goal: str,
        obligations: list[GoalObligation],
        *,
        current_steps: list[dict[str, Any]],
        rejected: dict[str, Any],
        reason: str,
        validation_error: str,
    ) -> str:
        ledger = self._amendment_ledger_view(current_steps)
        return f"""Repair one invalid reconciliation amendment before audit.

SOURCE GOAL (immutable):
{goal}

OBLIGATION LEDGER (immutable):
{json.dumps([item.to_dict() for item in obligations], ensure_ascii=False)}

CURRENT STEP DEFINITIONS:
{json.dumps(ledger["definitions"], ensure_ascii=False, default=str)}

AUTHORITATIVE STEP OUTCOMES (reason from these; do not copy runtime fields):
{json.dumps(ledger["outcomes"], ensure_ascii=False, default=str)}

RECONCILIATION REASON:
{reason}

LIVE CAPABILITY CATALOG:
{self._render_capability_catalog()}

REJECTED AMENDMENT:
{json.dumps(rejected, ensure_ascii=False, default=str)}

VALIDATION ERROR:
{validation_error}

Return one valid json object containing only NEW `steps` using the normal step
schema and capabilities in the live catalog. Current step ids may appear only in
depends_on. Preserve completed effects and add a fresh final response after
remediation when configured. Do not choose tools, name atoms, add capabilities,
or copy runtime fields."""

    @staticmethod
    def _amendment_ledger_view(
        current_steps: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        definition_fields = (
            "capability", "effect", "systems", "task", "success_criterion",
            "expected_findings", "depends_on", "covers",
        )
        definitions = []
        outcomes = []
        for step in current_steps:
            step_id = str(step.get("id") or step.get("step_id") or "")
            definitions.append({
                "step_id": step_id,
                **{field: step.get(field) for field in definition_fields},
            })
            outcomes.append({
                "step_id": step_id,
                "status": step.get("status"),
                "semantic_outcome": step.get("semantic_outcome"),
                "semantic_decision": step.get("semantic_decision"),
                "output": step.get("output"),
            })
        return {"definitions": definitions, "outcomes": outcomes}

    def _render_capability_catalog(self) -> str:
        lines = []
        for name, contract in sorted(self.capability_contracts.items()):
            systems = ", ".join(contract["systems"]) or "none declared"
            effects = ", ".join(sorted(contract["effects"]))
            lines.append(
                f"- {name}: {contract['description']} | effects: {effects} | systems: {systems}"
            )
        return "\n".join(lines)

    @staticmethod
    def _audit_prompt(plan: MeshPlan) -> str:
        return f"""Audit a proposed mesh DAG against its immutable source goal.

SOURCE GOAL:
{plan.goal}

OBLIGATIONS:
{json.dumps([item.to_dict() for item in plan.obligations], ensure_ascii=False)}

DAG STEPS:
{json.dumps([step.to_dict() for step in plan.steps], ensure_ascii=False)}

Return exactly one json object: {{"complete": true, "missing": []}} only if every requested
outcome, constraint, prohibition, approval boundary, fallback condition, scope
limit and evidence requirement in SOURCE GOAL exists in the obligation ledger
and is covered by an executable DAG step. For every write, notify, or destructive
step, verify that information needed to perform the intended action is supplied by the
source goal or an ancestor step; naming a person, account, file, channel, or event is
not equivalent to having its provider identifier or contact details. Flag parallel
steps when one needs facts the other is expected to discover. A provider-owned
inspect-or-create outcome is executable when its task explicitly discovers its own
same-provider identifiers and its success criterion returns the concrete identifiers
or links required downstream; do not demand atom-level steps for that discovery.
When a downstream outcome needs an artifact's content, require the producing step's
task and success criterion to inspect and return provider-readback evidence of usable
content. Resource existence, title, identifier, link or MIME type alone is insufficient.
Every obligation must also have an independently verifiable success criterion. A named
workflow or playbook is not an additional obligation when its meaning is fully defined
by the atomic outcomes that follow it. Do not require a synthesis or inspection step
merely to restate completion of those outcomes.

For an invalid obligation ledger, return complete=false, `missing`, and a corrected
`obligations` list using exactly id, description, source_quote. The corrected ledger may
remove only redundant composite obligations and must preserve every independently
verifiable source requirement. For an executable-step defect, omit `obligations` and
list each missing item with description and an exact source_quote."""

    @staticmethod
    def _parse_obligations(raw: dict[str, Any], goal: str) -> list[GoalObligation]:
        raw_obligations = raw.get("obligations")
        if not isinstance(raw_obligations, list) or not raw_obligations:
            raise MeshPlanError("Mesh plan requires at least one obligation")

        obligations = []
        obligation_ids = set()
        for index, item in enumerate(raw_obligations):
            if not isinstance(item, dict):
                raise MeshPlanError(f"Obligation {index} must be an object")
            obligation_id = str(item.get("id") or "").strip()
            description = str(item.get("description") or "").strip()
            source_quote = str(item.get("source_quote") or "").strip()
            if not obligation_id or obligation_id in obligation_ids:
                raise MeshPlanError(f"Obligation {index} has a missing or duplicate id")
            if not description:
                raise MeshPlanError(f"Obligation {obligation_id} has no description")
            if not source_quote or source_quote not in goal:
                raise MeshPlanError(
                    f"Obligation {obligation_id} source_quote is not present in the source goal"
                )
            obligation_ids.add(obligation_id)
            obligations.append(GoalObligation(obligation_id, description, source_quote))
        return obligations

    def _parse_steps(
        self,
        raw: dict[str, Any],
        obligations: list[GoalObligation],
        allowed_dependency_ids: set[str] | None = None,
        forbidden_step_ids: set[str] | None = None,
        required_obligation_ids: set[str] | None = None,
        allowed_cover_ids: set[str] | None = None,
    ) -> list[MeshPlannedStep]:
        raw_steps = raw.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise MeshPlanError("Mesh plan requires at least one step")
        obligation_ids = {item.id for item in obligations}
        steps = []
        step_ids = set()
        for index, item in enumerate(raw_steps):
            if not isinstance(item, dict):
                raise MeshPlanError(f"Step {index} must be an object")
            allowed = {
                "id", "step_id", "capability", "effect", "systems", "task", "success_criterion",
                "expected_findings", "depends_on", "covers",
            }
            unknown = set(item) - allowed
            if unknown:
                raise MeshPlanError(f"Step {index} has unsupported fields: {sorted(unknown)}")
            raw_id = str(item.get("id") or "").strip()
            raw_step_id = str(item.get("step_id") or "").strip()
            if raw_id and raw_step_id and raw_id != raw_step_id:
                raise MeshPlanError(f"Step {index} has conflicting id and step_id")
            step_id = raw_step_id or raw_id
            capability = str(item.get("capability") or "").strip()
            effect = str(item.get("effect") or "").strip()
            systems = [str(value).strip() for value in item.get("systems") or [] if str(value).strip()]
            task = str(item.get("task") or "").strip()
            criterion = str(item.get("success_criterion") or "").strip()
            if not step_id or step_id in step_ids:
                raise MeshPlanError(f"Step {index} has a missing or duplicate step_id")
            if step_id in (forbidden_step_ids or set()):
                raise MeshPlanError(f"Step {step_id} already exists in immutable history")
            if capability not in self.capabilities:
                raise MeshPlanError(f"Step {step_id} requests unknown capability {capability!r}")
            if effect not in {
                "read", "propose", "write", "notify", "destructive", "final_response"
            }:
                raise MeshPlanError(f"Step {step_id} requires a valid effect")
            if effect in {"write", "notify", "destructive"} and len(systems) != 1:
                raise MeshPlanError(
                    f"Step {step_id} with effect {effect!r} requires exactly one system"
                )
            authorized = self.capability_contracts[capability]["effects"]
            if effect not in authorized:
                raise MeshPlanError(
                    f"Capability {capability!r} does not authorize effect {effect!r}"
                )
            authorized_systems = set(self.capability_contracts[capability]["systems"])
            unauthorized_systems = set(systems) - authorized_systems
            if unauthorized_systems:
                raise MeshPlanError(
                    f"Capability {capability!r} does not authorize systems: "
                    f"{sorted(unauthorized_systems)}"
                )
            if not task or not criterion:
                raise MeshPlanError(f"Step {step_id} requires task and success_criterion")
            expected_raw = item.get("expected_findings") or []
            expected_findings = (
                [expected_raw.strip()] if isinstance(expected_raw, str) and expected_raw.strip()
                else [str(value) for value in expected_raw]
            )
            step_ids.add(step_id)
            steps.append(MeshPlannedStep(
                step_id=step_id,
                capability=capability,
                effect=effect,
                systems=systems,
                task=task,
                success_criterion=criterion,
                expected_findings=expected_findings,
                depends_on=[str(value) for value in item.get("depends_on") or []],
                covers=[str(value) for value in item.get("covers") or []],
            ))

        for step in steps:
            missing_dependencies = set(step.depends_on) - (
                step_ids | (allowed_dependency_ids or set())
            )
            if missing_dependencies or step.step_id in step.depends_on:
                raise MeshPlanError(
                    f"Step {step.step_id} has invalid dependencies: "
                    f"{sorted(missing_dependencies | ({step.step_id} if step.step_id in step.depends_on else set()))}"
                )
            valid_cover_ids = allowed_cover_ids or obligation_ids
            unknown_obligations = set(step.covers) - valid_cover_ids
            if unknown_obligations:
                raise MeshPlanError(
                    f"Step {step.step_id} covers obligations outside the amendment target: "
                    f"{sorted(unknown_obligations)}"
                )
        covered = {obligation for step in steps for obligation in step.covers}
        uncovered = (required_obligation_ids or obligation_ids) - covered
        if uncovered:
            raise MeshPlanError(f"Mesh plan has uncovered obligation(s): {sorted(uncovered)}")
        self._reject_cycles(steps, external_ids=allowed_dependency_ids or set())
        return steps

    @staticmethod
    def _reject_cycles(
        steps: list[MeshPlannedStep], external_ids: set[str] | None = None
    ) -> None:
        dependencies = {step.step_id: set(step.depends_on) for step in steps}
        visiting = set()
        visited = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise MeshPlanError("Mesh plan contains a dependency cycle")
            if step_id in visited:
                return
            if step_id in (external_ids or set()):
                visited.add(step_id)
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in dependencies:
            visit(step_id)
