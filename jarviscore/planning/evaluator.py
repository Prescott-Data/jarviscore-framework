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
from typing import Any, Optional

from .goal_context import GoalExecution, PlannedStep, StepEvaluation

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
  "hitl"    — reserved for decisions only a human can make. Use it ONLY when:
                • an irreversible or risky action needs human approval, or
                • credentials, permissions, or access the agent cannot obtain
                  are required to proceed, or
                • facts genuinely conflict and no further agent work can
                  resolve them.
              Do NOT use "hitl" because the output is unverifiable, incomplete,
              missing its artifact, or you simply lack evidence. Those are
              "partial" or "fail" — the loop can retry or replan to demand the
              artifact. A verification gap is never a human's problem.

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
            # ── Triage: routine budget yields vs genuine HITL needs ────────
            # Budget exhaustion is a normal operational event — the agent
            # simply ran out of tokens/turns/time.  Treat as partial success
            # so the goal loop replans with simpler steps instead of pausing
            # for human review.
            #
            # Only convergence stalls (agent tried different strategies and
            # still can't make progress) warrant genuine HITL escalation.
            meta = getattr(output, "metadata", None) or {}
            typed_outcome = meta.get("typed_outcome", "")
            _ROUTINE_YIELDS = {
                "YIELD_BUDGET_EXHAUSTED",
                "YIELD_LEASE_EXHAUSTED",
                "YIELD_EMERGENCY_TURN_FUSE",
            }
            if typed_outcome in _ROUTINE_YIELDS:
                return StepEvaluation(
                    verdict="partial",
                    confidence=0.80,
                    evaluator_note=(
                        f"Step yielded due to routine budget limit "
                        f"({typed_outcome}). Partial output available: "
                        f"{getattr(output, 'summary', 'yield triggered')}"
                    ),
                    additional_findings={},
                )
            # Genuine HITL: convergence stall or unknown yield reason
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

        # Evaluator is a fast 4-way classification task (pass/partial/fail/hitl).
        # Route to the nano/fast tier — cheaper, lower latency, no quality loss.
        # nano_model reads from TASK_MODEL_NANO config; falls back to the
        # default deployment if not set. Any model works here — it is
        # the developer's choice via env var, not hardcoded in the framework.
        eval_model = getattr(self.llm, "nano_model", None)

        call_kwargs: dict = {
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        if eval_model:
            call_kwargs["model"] = eval_model

        try:
            response = await self.llm.generate(**call_kwargs)
        except TypeError:
            # LLM client does not support response_format kwarg
            fallback_kwargs: dict = {"messages": [{"role": "user", "content": prompt}]}
            if eval_model:
                fallback_kwargs["model"] = eval_model
            try:
                response = await self.llm.generate(**fallback_kwargs)
            except Exception as exc:
                raise EvaluatorError(
                    f"Evaluator LLM call failed: {exc}"
                ) from exc
        except Exception as exc:
            raise EvaluatorError(f"Evaluator LLM call failed: {exc}") from exc

        content = (
            response.get("content", "") if isinstance(response, dict) else str(response)
        )
        try:
            return self._parse_evaluation(content, step)
        except EvaluatorError as first_error:
            repaired = await self._repair_evaluation_response(
                invalid_content=content,
                parse_error=first_error,
                eval_model=eval_model,
            )
            return self._parse_evaluation(repaired, step)

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

    async def _repair_evaluation_response(
        self,
        invalid_content: str,
        parse_error: EvaluatorError,
        eval_model: Optional[str],
    ) -> str:
        """Ask the evaluator model to repair its response to the strict schema once."""
        repair_prompt = (
            "Your previous evaluation response violated the required contract.\n\n"
            f"Parse error:\n{parse_error}\n\n"
            f"Invalid response:\n{invalid_content[:1200]}\n\n"
            "Rewrite it as valid JSON that obeys this exact schema. Do not change "
            "the assessment, only repair the envelope and enum values.\n\n"
            f"{_EVAL_SCHEMA}"
        )
        call_kwargs: dict = {
            "messages": [{"role": "user", "content": repair_prompt}],
            "response_format": {"type": "json_object"},
        }
        if eval_model:
            call_kwargs["model"] = eval_model

        try:
            response = await self.llm.generate(**call_kwargs)
        except TypeError:
            fallback_kwargs: dict = {"messages": [{"role": "user", "content": repair_prompt}]}
            if eval_model:
                fallback_kwargs["model"] = eval_model
            try:
                response = await self.llm.generate(**fallback_kwargs)
            except Exception as exc:
                raise EvaluatorError(
                    f"Evaluator repair LLM call failed after invalid response: {exc}"
                ) from exc
        except Exception as exc:
            raise EvaluatorError(
                f"Evaluator repair LLM call failed after invalid response: {exc}"
            ) from exc

        return response.get("content", "") if isinstance(response, dict) else str(response)

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

        Tries two strategies in order:
          1. Direct JSON parse
          2. Extract balanced { } block from prose (handles markdown wrappers)
        Raises EvaluatorError if both fail. Prose verdict guessing is
        intentionally rejected so planner loops see malformed evaluator output.
        """
        content = content.strip()

        # Strip markdown fences if inadvertently added
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()

        # ── Strategy 1: direct JSON parse ─────────────────────────────────────
        parsed = None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            pass

        # ── Strategy 2: extract balanced { } block from prose ─────────────────
        # Handles models that return markdown evaluation prose containing JSON.
        if parsed is None:
            brace_start = content.find("{")
            if brace_start != -1:
                depth = 0
                brace_end = brace_start
                for i, ch in enumerate(content[brace_start:], start=brace_start):
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            brace_end = i
                            break
                candidate = content[brace_start: brace_end + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    pass

        if parsed is None:
            raise EvaluatorError(
                f"Evaluator response is not valid JSON.\n"
                f"Response (first 400 chars):\n{content[:400]}"
            )


        if not isinstance(parsed, dict):
            raise EvaluatorError(
                f"Evaluator response must be a JSON object, got {type(parsed).__name__}"
            )

        if "verdict" not in parsed and isinstance(parsed.get("evaluation"), dict):
            evaluation = parsed["evaluation"]
            success_value = str(evaluation.get("success_criterion_met", "")).lower().strip()
            verdict_map = {
                "true": "pass",
                "yes": "pass",
                "met": "pass",
                "pass": "pass",
                "partial": "partial",
                "partially_met": "partial",
                "partially met": "partial",
                "some": "partial",
                "false": "fail",
                "no": "fail",
                "not_met": "fail",
                "not met": "fail",
                "fail": "fail",
                "unknown": "hitl",
                "ambiguous": "hitl",
                "hitl": "hitl",
            }
            if success_value in verdict_map:
                reason = evaluation.get("reason", "")
                if isinstance(reason, list):
                    reason = " ".join(str(item) for item in reason)
                parsed = {
                    "verdict": verdict_map[success_value],
                    "confidence": evaluation.get("confidence", parsed.get("confidence", 0.7)),
                    "evaluator_note": evaluation.get(
                        "evaluator_note",
                        reason or parsed.get("evaluator_note", ""),
                    ),
                    "additional_findings": parsed.get("additional_findings", {}),
                }

        if "verdict" not in parsed and "success_criterion_met" in parsed:
            success_value = str(parsed.get("success_criterion_met", "")).lower().strip()
            verdict_map = {
                "true": "pass",
                "yes": "pass",
                "met": "pass",
                "pass": "pass",
                "partial": "partial",
                "partially_met": "partial",
                "partially met": "partial",
                "some": "partial",
                "false": "fail",
                "no": "fail",
                "not_met": "fail",
                "not met": "fail",
                "fail": "fail",
                "unknown": "hitl",
                "ambiguous": "hitl",
                "hitl": "hitl",
            }
            if success_value in verdict_map:
                parsed = {
                    "verdict": verdict_map[success_value],
                    "confidence": parsed.get("confidence", 0.7),
                    "evaluator_note": parsed.get(
                        "evaluator_note",
                        parsed.get("evaluation", parsed.get("reason", "")),
                    ),
                    "additional_findings": parsed.get("additional_findings", {}),
                }

        if "verdict" not in parsed and "status" in parsed:
            status_value = str(parsed.get("status", "")).lower().strip()
            status_map = {
                "success": "pass",
                "passed": "pass",
                "pass": "pass",
                "partial": "partial",
                "partially_met": "partial",
                "partially met": "partial",
                "failure": "fail",
                "failed": "fail",
                "fail": "fail",
                "blocked": "hitl",
                "yield": "hitl",
                "hitl": "hitl",
                "needs_human": "hitl",
                "needs human": "hitl",
            }
            if status_value in status_map:
                parsed = {
                    "verdict": status_map[status_value],
                    "confidence": parsed.get("confidence", 0.7),
                    "evaluator_note": parsed.get("evaluator_note", parsed.get("reason", "")),
                    "additional_findings": parsed.get("additional_findings", {}),
                }

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
