"""
jarviscore.planning.planner
============================
Planner — decomposes a goal into an ordered list of PlannedSteps.

Design principles:
- Single responsibility: goal → typed step list. No execution, no evaluation.
- Structured JSON output: the LLM is prompted for JSON and the response is
  validated against a strict schema. Ambiguous or malformed output raises
  PlannerError immediately — no silent degradation.
- Stateless: instantiate once, call plan() or replan() many times.
- Used twice per goal: initial planning and adaptive replanning after failure.

The prompt gives the LLM:
  1. The agent's identity (system_prompt excerpt)
  2. Available subagent types and their capabilities
  3. The goal
  4. Accumulated facts from GoalExecution.truth (empty on first plan)
  5. Completed step history (only on replan)

Output validation is strict: missing required fields raise PlannerError.
The caller (execute_goal) decides how to handle the error — typically by
surfacing it as a terminal failure for the goal, not silently retrying.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from .goal_context import GoalExecution, PlannedStep

logger = logging.getLogger(__name__)


# ── Prompt constants ──────────────────────────────────────────────────────────

_VALID_HINTS = frozenset({"coder", "researcher", "communicator", "browser"})

_SUBAGENT_GUIDE = """\
Available subagent types (set subagent_hint to route directly):
- "researcher"   : web search, document retrieval, data gathering, investigation, analysis
- "coder"        : code generation, data processing, API calls, file I/O, computation
- "communicator" : drafting text, reports, emails, structured documents
- "browser"      : web automation, form filling, UI interaction, screenshots
If subagent_hint is null, the kernel obtains a structured routing decision.
"""

_OUTPUT_SCHEMA = """\
Return ONLY JSON. No prose, no markdown fences, no explanation.
Preferred shape:
{
  "steps": [
    {
      "step_id"           : "<unique slug, e.g. step_01_gather_data>",
      "task"              : "<complete, self-contained task the agent can act on immediately>",
      "success_criterion" : "<concrete, observable condition that means this step is done>",
      "expected_findings" : ["<snake_case key this step should produce>", ...],
      "subagent_hint"     : "<MUST be exactly one of: researcher, coder, communicator, browser, null>"
    }
  ]
}

Each step must have exactly these fields:
{
  "step_id"           : "<unique slug, e.g. step_01_gather_data>",
  "task"              : "<complete, self-contained task the agent can act on immediately>",
  "success_criterion" : "<concrete, observable condition that means this step is done>",
  "expected_findings" : ["<snake_case key this step should produce>", ...],
  "subagent_hint"     : "<MUST be exactly one of: researcher, coder, communicator, browser, null>"
}

CRITICAL — subagent_hint rules:
  "researcher"   → web search, analysis, investigation, strategy, planning, architecture
  "coder"        → code generation, data processing, computation, API calls, file I/O
  "communicator" → drafting text, reports, emails, documents, writing
  "browser"      → web automation, form filling, UI interaction, screenshots
  null           → let the kernel decide automatically
  NO other values are accepted. Do not invent new types (e.g. 'analyst', 'architect', 'writer').

Rules:
- 3 to 10 steps. No more. Each step must be atomic and clearly bounded.
- Each task must be self-contained — assume the executing agent has no other context.
- success_criterion must be observable and verifiable, not vague.
- expected_findings are short snake_case keys (e.g. "api_auth_method", "row_count").
- Do NOT include steps that are already completed (listed in completed_steps).
"""


# ── Errors ────────────────────────────────────────────────────────────────────

class PlannerError(Exception):
    """
    Raised when the Planner cannot produce a valid structured plan.

    This is a hard failure — the caller should surface it as a goal-level
    error, not retry with a degraded plan.

    Attributes:
        message: Human-readable explanation including the raw LLM response
                 snippet (first 500 chars) for debugging.
    """


# ── Planner ───────────────────────────────────────────────────────────────────

class Planner:
    """
    Decomposes a goal into an ordered list of PlannedSteps via a
    structured JSON LLM call.

    Instantiate once per agent; stateless between calls.

    Args:
        llm_client:            The LLM client (same instance the Kernel uses).
        system_prompt_excerpt: First ~400 chars of the agent's system_prompt,
                               used to give the planner the agent's identity
                               and domain context.

    Usage:
        planner = Planner(llm_client, system_prompt_excerpt=agent.system_prompt[:400])

        # Initial plan
        steps = await planner.plan(goal="Run the weekly market analysis", goal_execution=exec)

        # Revised plan after a step failure
        steps = await planner.replan(goal_execution=exec, failed_step=cs, reason="API timeout")
    """

    def __init__(self, llm_client, system_prompt_excerpt: str = ""):
        self.llm = llm_client
        self._identity = system_prompt_excerpt[:400] if system_prompt_excerpt else ""

    async def plan(
        self,
        goal: str,
        goal_execution: GoalExecution,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[PlannedStep]:
        """
        Initial planning: decompose a goal into an ordered step list.

        Args:
            goal:           The goal string.
            goal_execution: Current GoalExecution (truth may be empty at this point).
            context:        Optional initial context (auth, config, output_dir, etc.).
                            Non-private keys are included as hints in the prompt.

        Returns:
            List[PlannedStep] — ordered plan ready for execution.

        Raises:
            PlannerError: if the LLM call fails or the response cannot be
                          parsed into a valid plan.
        """
        known_facts = goal_execution.truth.to_flat_dict()
        known_str = json.dumps(known_facts, default=str)[:800] if known_facts else "None yet."

        ctx_note = ""
        if context:
            public = {k: v for k, v in context.items() if not str(k).startswith("_")}
            if public:
                ctx_note = f"\nAvailable context:\n{json.dumps(public, default=str)[:300]}\n"

        prompt = self._build_initial_prompt(goal, known_str, ctx_note)
        return await self._call_and_parse(prompt, goal)

    async def replan(
        self,
        goal_execution: GoalExecution,
        failed_step: Any,           # CompletedStep
        reason: str,
    ) -> List[PlannedStep]:
        """
        Recovery planning after a step failure.

        Produces a revised plan for the REMAINING work only — already-completed
        steps are not re-listed. The planner is given the full failure context
        so it can change approach, not just retry the same strategy.

        Args:
            goal_execution: Full GoalExecution state at the point of failure.
            failed_step:    The CompletedStep that received a "fail" verdict.
            reason:         StepEvaluation.evaluator_note — why it failed.

        Returns:
            Revised List[PlannedStep] for the remaining work.

        Raises:
            PlannerError: if the LLM call fails or response is unparseable.
        """
        completed_summary = "\n".join(
            f"  - [{cs.evaluation.verdict.upper()}] {cs.step.step_id}: {cs.step.task[:120]}"
            for cs in goal_execution.completed
        )

        known_facts = goal_execution.truth.to_flat_dict()
        known_str = json.dumps(known_facts, default=str)[:800] if known_facts else "None."

        prompt = self._build_replan_prompt(
            goal=goal_execution.goal,
            completed_summary=completed_summary,
            failed_step_task=failed_step.step.task,
            failure_reason=reason,
            known_facts_str=known_str,
        )
        return await self._call_and_parse(prompt, goal_execution.goal)

    # ── Prompt builders ───────────────────────────────────────────────────────

    def _build_initial_prompt(
        self,
        goal: str,
        known_facts_str: str,
        ctx_note: str,
    ) -> str:
        parts = ["You are planning an autonomous multi-step agent execution.\n"]
        if self._identity:
            parts.append(f"Agent identity: {self._identity}\n\n")
        parts.append(_SUBAGENT_GUIDE)
        parts.append(f"\nGoal: {goal}\n")
        parts.append(f"Known facts so far: {known_facts_str}\n")
        parts.append(ctx_note)
        parts.append(f"\n{_OUTPUT_SCHEMA}")
        return "".join(parts)

    def _build_replan_prompt(
        self,
        goal: str,
        completed_summary: str,
        failed_step_task: str,
        failure_reason: str,
        known_facts_str: str,
    ) -> str:
        parts = [
            "An autonomous agent execution has partially failed. Produce a REVISED plan.\n\n",
        ]
        if self._identity:
            parts.append(f"Agent identity: {self._identity}\n\n")
        parts.append(_SUBAGENT_GUIDE)
        parts.append(f"\nOriginal goal: {goal}\n")
        parts.append(f"\nCompleted steps (do NOT re-include these):\n{completed_summary}\n")
        parts.append(f"\nFailed step: {failed_step_task}\n")
        parts.append(f"Failure reason: {failure_reason}\n")
        parts.append(f"Accumulated facts: {known_facts_str}\n")
        parts.append(
            "\nProduce a revised plan for the REMAINING work only. "
            "Change approach — do not repeat the same failed strategy.\n\n"
        )
        parts.append(_OUTPUT_SCHEMA)
        return "".join(parts)

    # ── LLM call + parsing ────────────────────────────────────────────────────

    async def _call_and_parse(self, prompt: str, goal: str) -> List[PlannedStep]:
        """
        Call the LLM and parse the response into PlannedSteps.
        Raises PlannerError on any failure — no silent fallbacks.
        """
        content = await self._call_llm(prompt)
        return self._parse_plan(content, goal)

    async def _call_llm(self, prompt: str) -> str:
        """Call the LLM. Try JSON mode first, fall back if not supported.

        Model tier: planner requires deep multi-step reasoning — uses
        TASK_MODEL_HEAVY → TASK_MODEL_STANDARD from config (planner_model
        property on the LLM client). Falls back to AZURE_DEPLOYMENT if
        neither is configured.
        """
        messages = [{"role": "user", "content": prompt}]

        # Resolve planner model explicitly — never rely on AZURE_DEPLOYMENT default
        call_kwargs: dict = {"messages": messages, "response_format": {"type": "json_object"}}
        planner_model = getattr(self.llm, "planner_model", None)
        if planner_model:
            call_kwargs["model"] = planner_model

        try:
            response = await self.llm.generate(**call_kwargs)
        except TypeError:
            # LLM client does not support response_format kwarg
            fallback_kwargs: dict = {"messages": messages}
            if planner_model:
                fallback_kwargs["model"] = planner_model
            try:
                response = await self.llm.generate(**fallback_kwargs)
            except Exception as exc:
                raise PlannerError(f"Planner LLM call failed: {exc}") from exc
        except Exception as exc:
            raise PlannerError(f"Planner LLM call failed: {exc}") from exc

        if isinstance(response, dict):
            return response.get("content", "")
        return str(response)

    def _parse_plan(self, content: str, goal: str) -> List[PlannedStep]:
        """
        Parse the LLM JSON response into a validated list of PlannedSteps.

        Accepts:
          - A raw JSON array: [{"step_id": ..., "task": ..., ...}, ...]
          - A JSON object wrapping an array: {"steps": [...]} or {"plan": [...]}
          - A single strict step object: {"step_id": ..., "task": ..., ...}
          - A single named step object: {"step_01_name": {"step_id": ..., "task": ..., ...}}

        Raises PlannerError if:
          - The response is not valid JSON
          - No steps array is found
          - Any step is missing required fields ("task", "success_criterion")
          - The plan is empty
        """
        content = content.strip()

        # Strip markdown fences if the model added them despite instructions
        if content.startswith("```"):
            lines = content.splitlines()
            content = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            ).strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise PlannerError(
                f"Planner response is not valid JSON.\n"
                f"JSON error: {exc}\n"
                f"Response (first 500 chars):\n{content[:500]}"
            ) from exc

        # Resolve to a list
        raw: Optional[List] = None
        if isinstance(parsed, list):
            raw = parsed
        elif isinstance(parsed, dict):
            for key in ("steps", "plan", "tasks", "items"):
                if key in parsed and isinstance(parsed[key], list):
                    raw = parsed[key]
                    break
            if raw is None and "task" in parsed and "success_criterion" in parsed:
                raw = [parsed]
            if raw is None and len(parsed) == 1:
                only_value = next(iter(parsed.values()))
                if isinstance(only_value, dict) and "task" in only_value and "success_criterion" in only_value:
                    raw = [only_value]
            if raw is None:
                raise PlannerError(
                    f"Planner returned a JSON object with no recognisable steps array.\n"
                    f"Keys found: {list(parsed.keys())}\n"
                    f"Response: {content[:400]}"
                )
        else:
            raise PlannerError(
                f"Planner response is neither a JSON array nor object. "
                f"Got type: {type(parsed).__name__}"
            )

        if not raw:
            raise PlannerError(
                f"Planner produced an empty plan for goal: {goal!r}"
            )

        steps: List[PlannedStep] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise PlannerError(
                    f"Step {i} is not a JSON object: {item!r}"
                )
            if "task" not in item:
                raise PlannerError(
                    f"Step {i} is missing required field 'task': {item!r}"
                )
            if "success_criterion" not in item:
                raise PlannerError(
                    f"Step {i} is missing required field 'success_criterion': {item!r}"
                )

            hint = item.get("subagent_hint")
            if hint in (None, "null", ""):
                hint = None
            elif hint not in _VALID_HINTS:
                raise PlannerError(
                    f"Step {i} has invalid subagent_hint {hint!r}. "
                    f"Expected one of {sorted(_VALID_HINTS)} or null."
                )

            step_id = item.get("step_id") or f"step_{i+1:02d}_{uuid.uuid4().hex[:4]}"
            steps.append(PlannedStep(
                step_id=str(step_id),
                task=str(item["task"]),
                success_criterion=str(item["success_criterion"]),
                expected_findings=list(item.get("expected_findings") or []),
                subagent_hint=hint,
            ))

        logger.info(
            "[Planner] Produced %d-step plan for goal: %s",
            len(steps), goal[:80],
        )
        return steps
