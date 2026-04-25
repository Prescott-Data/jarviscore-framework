"""
jarviscore.planning.evaluator
==============================
StepEvaluator — evaluates whether a completed step met its success criterion.

Design principles:
- Single responsibility: (step, output, goal_context) → StepEvaluation.
- Cheap: one focused LLM call per step, not a full subagent dispatch.
- Strict: EvaluatorError is raised if the response cannot be parsed into
  a valid verdict. Callers (execute_goal) handle this explicitly.
- Fact extraction: the evaluator pulls additional_findings from the output
  that the agent didn't explicitly label — these are merged into GoalExecution.truth.

Short-circuit rules (no LLM call needed):
- output.status == "failure" → verdict = "fail" immediately
- output.status == "yield"   → verdict = "hitl" immediately

Only "success" outputs go through the LLM evaluation call.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from .goal_context import GoalExecution, PlannedStep, StepEvaluation

logger = logging.getLogger(__name__)


_EVAL_SCHEMA = """\
Return ONLY a JSON object with exactly these fields:
{
  "verdict"             : "<pass|partial|fail|hitl>",
  "confidence"          : <float 0.0 to 1.0>,
  "evaluator_note"      : "<concise explanation of verdict — 1-2 sentences>",
  "additional_findings" : {
    "<snake_case_key>" : "<value extracted from the output that future steps should know>"
  }
}

Verdict guide:
  "pass"    — success_criterion is clearly met. Continue to next step.
  "partial" — criterion partially met. Continue, but note what is missing.
  "fail"    — criterion not met. The goal loop will trigger replanning.
  "hitl"    — cannot determine without human judgement (ambiguous, risky, or conflicting).

additional_findings:
  Key facts you extract from the output that should inform future steps.
  Keys must be short snake_case (e.g. "api_base_url", "record_count").
  Return an empty object {} if there is nothing new to add.
  Do NOT duplicate facts already listed in accumulated_goal_facts.
"""


class EvaluatorError(Exception):
    """
    Raised when the evaluator cannot produce a valid verdict.

    Attributes:
        message: Explanation including the raw LLM response snippet.
    """


class StepEvaluator:
    """
    Evaluates whether a completed step met its success criterion.

    Stateless — instantiate once per agent, call evaluate() per step.

    Args:
        llm_client: The LLM client (same instance the Kernel uses).

    Usage:
        evaluator = StepEvaluator(llm_client)
        evaluation = await evaluator.evaluate(step, output, goal_execution)
        if evaluation.needs_replan:
            new_plan = await planner.replan(goal_execution, cs, evaluation.evaluator_note)
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def evaluate(
        self,
        step: PlannedStep,
        output: Any,                # AgentOutput
        goal_execution: GoalExecution,
    ) -> StepEvaluation:
        """
        Evaluate a completed step against its success criterion.

        Short-circuits for failed/yield outputs without an LLM call.
        Raises EvaluatorError if the evaluation LLM call fails or
        returns an unparseable/invalid response.

        Args:
            step:           The PlannedStep that was executed.
            output:         AgentOutput returned by Kernel.execute().
            goal_execution: Full GoalExecution (for goal context and accumulated facts).

        Returns:
            StepEvaluation with verdict, confidence, note, and additional findings.

        Raises:
            EvaluatorError: on LLM call failure or invalid JSON response.
        """
        # ── Short-circuit: no LLM call needed for clear failures ──────────────
        output_status = getattr(output, "status", "unknown")

        if output_status == "failure":
            return StepEvaluation(
                verdict="fail",
                confidence=0.95,
                evaluator_note=(
                    f"Step execution failed: "
                    f"{getattr(output, 'summary', 'no summary provided')}"
                ),
                additional_findings={},
            )

        if output_status == "yield":
            return StepEvaluation(
                verdict="hitl",
                confidence=0.98,
                evaluator_note=(
                    f"Step triggered a human-in-the-loop pause: "
                    f"{getattr(output, 'summary', 'yield triggered')}"
                ),
                additional_findings={},
            )

        # ── LLM evaluation for "success" outputs ──────────────────────────────
        prompt = self._build_prompt(step, output, goal_execution)

        try:
            response = await self.llm.generate(
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
        except TypeError:
            # LLM client does not support response_format kwarg
            try:
                response = await self.llm.generate(
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as exc:
                raise EvaluatorError(
                    f"Evaluator LLM call failed: {exc}"
                ) from exc
        except Exception as exc:
            raise EvaluatorError(f"Evaluator LLM call failed: {exc}") from exc

        content = (
            response.get("content", "") if isinstance(response, dict) else str(response)
        )
        return self._parse_evaluation(content, step)

    # ── Prompt ────────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        step: PlannedStep,
        output: Any,
        goal_execution: GoalExecution,
    ) -> str:
        output_repr = self._format_output(output)
        known = json.dumps(
            goal_execution.truth.to_flat_dict(), default=str
        )[:500]

        return (
            f"Evaluate whether this agent step met its success criterion.\n\n"
            f"Overall goal: {goal_execution.goal}\n\n"
            f"Step task: {step.task}\n"
            f"Success criterion: {step.success_criterion}\n"
            f"Expected findings: {step.expected_findings}\n\n"
            f"Step output:\n{output_repr}\n\n"
            f"Accumulated goal facts (do not re-extract these): {known}\n\n"
            f"{_EVAL_SCHEMA}"
        )

    def _format_output(self, output: Any) -> str:
        """
        Render AgentOutput fields for the evaluation prompt.
        Keeps it focused: status, summary, and payload (capped).
        """
        parts = []
        status = getattr(output, "status", "unknown")
        summary = getattr(output, "summary", None)
        payload = getattr(output, "payload", None)

        parts.append(f"status: {status}")
        if summary:
            parts.append(f"summary: {summary[:600]}")
        if payload is not None:
            if isinstance(payload, dict):
                payload_str = json.dumps(payload, default=str)
            else:
                payload_str = str(payload)
            parts.append(f"payload: {payload_str[:1000]}")

        return "\n".join(parts)

    # ── Response parsing ──────────────────────────────────────────────────────

    def _parse_evaluation(self, content: str, step: PlannedStep) -> StepEvaluation:
        """
        Parse LLM JSON response into StepEvaluation.
        Raises EvaluatorError if the response is invalid or verdict is unrecognised.
        """
        content = content.strip()

        # Strip markdown fences if inadvertently added
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise EvaluatorError(
                f"Evaluator response is not valid JSON.\n"
                f"JSON error: {exc}\n"
                f"Response (first 400 chars):\n{content[:400]}"
            ) from exc

        if not isinstance(parsed, dict):
            raise EvaluatorError(
                f"Evaluator response must be a JSON object, got {type(parsed).__name__}"
            )

        verdict = str(parsed.get("verdict", "")).lower().strip()
        if verdict not in ("pass", "partial", "fail", "hitl"):
            raise EvaluatorError(
                f"Evaluator returned invalid verdict: {verdict!r} for step {step.step_id!r}.\n"
                f"Must be one of: pass, partial, fail, hitl.\n"
                f"Full response: {content[:300]}"
            )

        raw_confidence = parsed.get("confidence", 0.7)
        try:
            confidence = float(raw_confidence)
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.7

        additional = parsed.get("additional_findings")
        if not isinstance(additional, dict):
            additional = {}

        return StepEvaluation(
            verdict=verdict,
            confidence=confidence,
            evaluator_note=str(parsed.get("evaluator_note", ""))[:600],
            additional_findings=additional,
        )
