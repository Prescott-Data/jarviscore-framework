"""
jarviscore.planning
====================
Long-horizon goal execution for JarvisCore AutoAgents.

This module adds the Plan → Execute → Evaluate loop that enables agents
to work autonomously on complex, multi-step goals — not just single tasks.

Core components:
    GoalExecution   — live state spanning the full goal execution
    PlannedStep     — one step in the agent-generated plan
    StepEvaluation  — verdict + findings after each step runs
    CompletedStep   — immutable record of an executed + evaluated step
    Planner         — LLM call: goal → List[PlannedStep]
    PlannerError    — raised when planning or replanning fails
    StepEvaluator   — LLM call: (step, output) → StepEvaluation
    EvaluatorError  — raised when evaluation fails

Entry point:
    Developers do not use this module directly. Use AutoAgent.execute_goal():

        class MyAgent(AutoAgent):
            system_prompt = "You are a market researcher..."
            goal_oriented = True   # all tasks routed through execute_goal()

        result = await agent.execute_goal(
            goal="Produce a competitive analysis for sector X",
            context={"output_dir": "reports/"},
        )
        print(result.result)        # final output
        print(result.truth.facts)   # all discovered facts

See also:
    AutoAgent.execute_goal()    — the orchestration loop
    AutoAgent.goal_oriented     — class attribute to auto-route all tasks
"""
from .goal_context import (
    GoalExecution,
    PlannedStep,
    StepEvaluation,
    CompletedStep,
)
from .planner import Planner, PlannerError
from .evaluator import StepEvaluator, EvaluatorError

__all__ = [
    "GoalExecution",
    "PlannedStep",
    "StepEvaluation",
    "CompletedStep",
    "Planner",
    "PlannerError",
    "StepEvaluator",
    "EvaluatorError",
]
