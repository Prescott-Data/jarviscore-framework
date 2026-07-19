"""
jarviscore.planning.goal_context
=================================
Data contracts for long-horizon goal execution.

Pure dataclasses — no LLM calls, no I/O, no framework dependencies.
These define the state that lives across multiple Kernel.execute() calls
during a goal-oriented autonomous execution session.

The central object is GoalExecution: it holds the plan, the live
TruthContext (shared knowledge accumulating across steps), the full
history of completed steps, and the final result.

Usage:
    # Created automatically by AutoAgent.execute_goal()
    exec_state = GoalExecution(goal="Produce Q2 market analysis", agent_id="analyst")

    # After completion:
    exec_state.result         — final synthesised output
    exec_state.truth          — all facts discovered (TruthContext)
    exec_state.completed      — step-by-step history with evaluations
    exec_state.to_summary_dict() — compact dict for logging/API
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from jarviscore.context.truth import TruthContext

logger = logging.getLogger(__name__)


# ── Step planning ─────────────────────────────────────────────────────────────

@dataclass
class PlannedStep:
    """
    A single step in an agent-generated execution plan.

    Created by the Planner. Passed verbatim as the task to Kernel.execute().
    The success_criterion is given to the StepEvaluator after execution.

    Attributes:
        step_id:            Unique slug used for logging and deduplication.
        task:               Complete, self-contained task string for Kernel.execute().
        success_criterion:  Observable condition that means this step is done.
        expected_findings:  Fact keys the evaluator should look for in the output.
        depends_on:         step_ids that must complete before this one.
        subagent_hint:      If set, Kernel skips classification and uses this role.
    """
    step_id: str
    task: str
    success_criterion: str
    expected_findings: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    subagent_hint: Optional[Literal["coder", "researcher", "communicator", "browser"]] = None

    def to_context_extras(self) -> Dict[str, Any]:
        """
        Extra fields to merge into Kernel.execute()'s enriched_context.

        Passes step metadata and subagent routing hint to the Kernel
        without changing its public signature.
        """
        extras: Dict[str, Any] = {
            "step_id": self.step_id,
            "_success_criterion": self.success_criterion,
            "_expected_findings": self.expected_findings,
        }
        if self.subagent_hint:
            extras["_agent_default_kernel_role"] = self.subagent_hint
        return extras

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe serialization for goal persistence (issue #73)."""
        return {
            "step_id": self.step_id,
            "task": self.task,
            "success_criterion": self.success_criterion,
            "expected_findings": list(self.expected_findings),
            "depends_on": list(self.depends_on),
            "subagent_hint": self.subagent_hint,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlannedStep":
        """Rehydrate a step from a persisted snapshot (issue #73)."""
        return cls(
            step_id=str(data["step_id"]),
            task=str(data["task"]),
            success_criterion=str(data.get("success_criterion", "")),
            expected_findings=list(data.get("expected_findings") or []),
            depends_on=list(data.get("depends_on") or []),
            subagent_hint=data.get("subagent_hint"),
        )


# ── Step evaluation ───────────────────────────────────────────────────────────

@dataclass
class StepEvaluation:
    """
    Result of StepEvaluator.evaluate() for one completed step.

    Attributes:
        verdict:              "pass"|"partial"|"fail"|"hitl"
        confidence:           0.0–1.0 evaluator confidence in the verdict.
        evaluator_note:       Concise explanation of the verdict.
        additional_findings:  New facts extracted from the output — merged
                              into GoalExecution.truth by record_completed().
    """
    verdict: Literal["pass", "partial", "fail", "hitl"]
    confidence: float
    evaluator_note: str
    additional_findings: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict in ("pass", "partial")

    @property
    def needs_hitl(self) -> bool:
        return self.verdict == "hitl"

    @property
    def needs_replan(self) -> bool:
        return self.verdict == "fail"


# ── Completed step record ─────────────────────────────────────────────────────

@dataclass
class CompletedStep:
    """
    Immutable record of a step that has been executed and evaluated.

    Stored in GoalExecution.completed — the full execution audit trail.
    """
    step: PlannedStep
    output: Any                          # AgentOutput instance
    evaluation: StepEvaluation
    elapsed_ms: float
    distilled_facts: Dict[str, Any] = field(default_factory=dict)

    def to_summary(self) -> Dict[str, Any]:
        """Compact summary for context injection into subsequent steps."""
        return {
            "step_id": self.step.step_id,
            "task": self.step.task[:200],
            "verdict": self.evaluation.verdict,
            "summary": getattr(self.output, "summary", "")[:300],
        }


@dataclass
class _ResumedStep:
    """A completed step rehydrated from a persisted snapshot (issue #73).

    Duck-types the parts of CompletedStep that downstream code reads after
    the fact — ``.step``, ``.evaluation``, ``.elapsed_ms``, ``to_summary()``.
    The live AgentOutput is gone; its summary survives.
    """
    step: PlannedStep
    verdict: str
    evaluator_note: str
    summary: str
    elapsed_ms: float = 0.0

    @property
    def evaluation(self) -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(
            verdict=self.verdict,
            evaluator_note=self.evaluator_note,
            confidence=0.0,
        )

    @property
    def output(self) -> Any:
        from types import SimpleNamespace
        return SimpleNamespace(summary=self.summary, metadata={})

    def to_summary(self) -> Dict[str, Any]:
        return {
            "step_id": self.step.step_id,
            "task": self.step.task[:200],
            "verdict": self.verdict,
            "summary": self.summary[:300],
        }

    @classmethod
    def from_snapshot_entry(cls, entry: Dict[str, Any]) -> "_ResumedStep":
        return cls(
            step=PlannedStep(
                step_id=str(entry.get("step_id", "?")),
                task=str(entry.get("task", "")),
                success_criterion="",
            ),
            verdict=str(entry.get("verdict", "pass")),
            evaluator_note=str(entry.get("evaluator_note", "")),
            summary=str(entry.get("summary", "")),
            elapsed_ms=float(entry.get("elapsed_ms", 0.0) or 0.0),
        )


# ── Goal execution state ──────────────────────────────────────────────────────

@dataclass
class GoalExecution:
    """
    Live execution state for a long-horizon goal.

    Created once per AutoAgent.execute_goal() call. Carries all state
    through the Plan → Execute → Evaluate loop:

    - plan:      Current ordered list of PlannedSteps (may be revised).
    - truth:     Live TruthContext — shared knowledge accumulating as steps
                 complete. This is what crosses step boundaries cleanly.
    - completed: Full history of executed steps with evaluations.
    - result:    Final synthesised output (set when status == "complete").

    The truth field is the key innovation. Every step's distilled facts
    and goal-scoped scratchpad entries are merged into it. Subsequent steps
    receive truth.to_flat_dict() in their enriched_context — structured,
    typed, not str()'d to 500 characters.

    Usage:
        # Returned by AutoAgent.execute_goal()
        execution = await agent.execute_goal("Produce Q2 market analysis")

        execution.result          # str — final answer / output path
        execution.truth           # TruthContext — all discovered facts
        execution.completed       # List[CompletedStep] — full history
        execution.to_summary_dict() # compact dict for APIs / logging
    """
    goal: str
    agent_id: str
    goal_id: str = field(default_factory=lambda: f"goal-{uuid.uuid4().hex[:10]}")

    # Plan state
    plan: List[PlannedStep] = field(default_factory=list)
    plan_revision: int = 0
    current_step_index: int = 0

    # Execution state
    completed: List[CompletedStep] = field(default_factory=list)
    status: Literal[
        "planning", "executing", "complete", "blocked", "hitl", "failed"
    ] = "planning"

    # Live shared knowledge — grows as each step completes
    truth: TruthContext = field(default_factory=TruthContext)

    # Final outcome
    result: Optional[Any] = None
    error: Optional[str] = None

    # Timing
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def remaining_steps(self) -> List[PlannedStep]:
        """Steps not yet completed (by step_id)."""
        completed_ids = {cs.step.step_id for cs in self.completed}
        return [s for s in self.plan if s.step_id not in completed_ids]

    @property
    def is_done(self) -> bool:
        return self.status in ("complete", "failed", "blocked", "hitl")

    @property
    def steps_completed(self) -> int:
        return len(self.completed)

    @property
    def elapsed_ms(self) -> float:
        end = self.completed_at or time.time()
        return (end - self.started_at) * 1000

    # ── Context building ──────────────────────────────────────────────────────

    def context_for_next_step(
        self, base_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build the enriched context dict to inject into Kernel.execute()
        for the next step.

        Key design: goal facts are passed as a structured flat dict
        (_goal_facts), not as str()'d text. The downstream step's
        ContextManager renders these properly with budget awareness.

        Args:
            base_context: Caller's initial context (auth, config, etc.)

        Returns:
            Dict ready to pass as Kernel.execute(context=...)
        """
        ctx = dict(base_context) if base_context else {}

        # Accumulated knowledge — structured, not str()'d
        ctx["_goal_id"] = self.goal_id
        ctx["_goal"] = self.goal
        ctx["_goal_facts"] = self.truth.to_flat_dict()
        ctx["_goal_facts_high_confidence"] = {
            k: v.value
            for k, v in self.truth.high_confidence_facts(threshold=0.7).items()
        }

        # Completed step summaries — enough for the agent to not duplicate work
        ctx["_completed_steps"] = [cs.to_summary() for cs in self.completed]
        ctx["_plan_revision"] = self.plan_revision

        return ctx

    # ── Mutation ──────────────────────────────────────────────────────────────

    def record_completed(
        self,
        step: PlannedStep,
        output: Any,
        evaluation: StepEvaluation,
        elapsed_ms: float,
    ) -> None:
        """
        Record a completed step and merge its facts into the shared truth.

        Merges two fact sources:
        1. output.metadata["distilled_facts"]  — Kernel-distilled from payload
        2. evaluation.additional_findings      — Evaluator-extracted from output
        """
        distilled = {}
        if hasattr(output, "metadata") and output.metadata:
            distilled = output.metadata.get("distilled_facts", {})

        self.completed.append(CompletedStep(
            step=step,
            output=output,
            evaluation=evaluation,
            elapsed_ms=elapsed_ms,
            distilled_facts=distilled,
        ))

        # Merge kernel-distilled facts into truth
        if distilled:
            try:
                from jarviscore.context.distillation import merge_facts
                from jarviscore.context.truth import TruthFact
                typed_facts = {}
                for k, v in distilled.items():
                    if isinstance(v, dict) and "value" in v:
                        typed_facts[k] = TruthFact(**v)
                    else:
                        typed_facts[k] = TruthFact(value=v, source=step.step_id)
                merge_facts(self.truth, typed_facts, source=step.step_id)
            except Exception as exc:
                logger.warning(
                    "Failed to merge distilled facts for step %s into goal truth: %s",
                    step.step_id,
                    exc,
                )

        # Merge evaluator-extracted additional findings
        if evaluation.additional_findings:
            try:
                from jarviscore.context.distillation import distill_output, merge_facts
                new_facts = distill_output(
                    raw_output=evaluation.additional_findings,
                    source=f"evaluator:{step.step_id}",
                    confidence=evaluation.confidence,
                )
                merge_facts(self.truth, new_facts, source=f"evaluator:{step.step_id}")
            except Exception as exc:
                logger.warning(
                    "Failed to merge evaluator findings for step %s into goal truth: %s",
                    step.step_id,
                    exc,
                )

    # ── Serialisation ─────────────────────────────────────────────────────────

    def to_summary_dict(self) -> Dict[str, Any]:
        """Compact summary for logging and API responses."""
        return {
            "goal_id": self.goal_id,
            "goal": self.goal,
            "status": self.status,
            "steps_completed": self.steps_completed,
            "total_steps_planned": len(self.plan),
            "plan_revision": self.plan_revision,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "result_preview": str(self.result)[:300] if self.result else None,
            "error": self.error,
            "fact_count": len(self.truth.facts),
        }

    def to_full_dict(self) -> Dict[str, Any]:
        """Full serialisable representation for blob persistence / debugging."""
        return {
            **self.to_summary_dict(),
            "agent_id": self.agent_id,
            "facts": self.truth.to_flat_dict(),
            "plan": [s.to_dict() for s in self.plan],
            "truth_facts_full": {
                k: f.model_dump() for k, f in self.truth.facts.items()
            },
            "completed_steps": [
                {
                    "step_id": cs.step.step_id,
                    "task": cs.step.task,
                    "verdict": cs.evaluation.verdict,
                    "evaluator_note": cs.evaluation.evaluator_note,
                    "summary": str(getattr(cs.output, "summary", "") or "")[:300],
                    "elapsed_ms": round(cs.elapsed_ms, 1),
                }
                for cs in self.completed
            ],
        }

    @classmethod
    def from_snapshot(cls, data: Dict[str, Any]) -> "GoalExecution":
        """Rehydrate a persisted execution for resume (issue #73).

        Restores the goal, the full plan, the truth facts (with confidence
        and evidence), and the completed-step history as lightweight records
        that satisfy everything downstream reads (``.step``, ``.evaluation``,
        ``.to_summary()``). Live ``AgentOutput`` objects are not — and need
        not be — reconstructed.
        """
        from jarviscore.context.truth import TruthFact

        execution = cls(
            goal=str(data.get("goal", "")),
            agent_id=str(data.get("agent_id", "unknown")),
            goal_id=str(data.get("goal_id") or f"goal-{uuid.uuid4().hex[:10]}"),
        )
        execution.plan = [PlannedStep.from_dict(s) for s in data.get("plan") or []]
        execution.plan_revision = int(data.get("plan_revision", 0))
        execution.status = str(data.get("status", "planning"))

        for key, fact in (data.get("truth_facts_full") or {}).items():
            try:
                execution.truth.facts[key] = TruthFact(**fact)
            except Exception:  # noqa: BLE001 - a bad fact must not void the rest
                logger.warning("Skipping unrehydratable fact %r on resume", key)

        for cs in data.get("completed_steps") or []:
            execution.completed.append(_ResumedStep.from_snapshot_entry(cs))
        return execution
