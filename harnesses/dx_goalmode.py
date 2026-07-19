#!/usr/bin/env python3
"""DX Harness 3 - goal mode: plan -> depends_on -> execute -> persist (REAL LLM).

The long-horizon developer journey: goal_oriented AutoAgent plans a
multi-step task, the planner emits depends_on, execution honors it,
facts accumulate in truth, and the execution persists for resume.
"""
import asyncio
import json
import sys

PASS, FAIL = "✅", "❌"
failures = []


def check(name, cond, detail=""):
    print(f"  {PASS if cond else FAIL} {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def main():
    from jarviscore import Mesh, AutoAgent

    class PlannerAgent(AutoAgent):
        role = "planner_dx"
        capabilities = ["research", "analysis", "writing"]
        goal_oriented = True
        system_prompt = (
            "You are a concise research analyst. Keep every step's output "
            "under 150 words. Never use web search - reason from knowledge."
        )

    print("== Goal-mode developer journey (live LLM) ==")

    mesh = Mesh()
    mesh.add(PlannerAgent)
    await mesh.start()
    try:
        agent = mesh.get_agent("planner_dx")

        goal = (
            "Produce a three-part brief on running trading bots safely: "
            "(1) list the top three operational risks, (2) list three "
            "mitigations for those risks, (3) combine both into a short "
            "final brief. Parts 1 and 2 are independent of each other; "
            "part 3 needs both."
        )
        execution = await agent.execute_goal(goal, max_steps=8)

        check("goal completes", execution.status == "complete",
              f"status={execution.status} error={execution.error}")
        check("plan had 3+ steps", len(execution.plan) >= 3,
              f"{len(execution.plan)} steps")
        deps_declared = any(s.depends_on for s in execution.plan)
        check("planner declared depends_on (#74)", deps_declared,
              f"plan: {[(s.step_id, s.depends_on) for s in execution.plan]}")
        check("all steps completed", len(execution.completed) >= 3)
        check("truth accumulated facts", len(execution.truth.facts) > 0,
              f"{len(execution.truth.facts)} facts")
        check("final result synthesized", bool(execution.result) and len(str(execution.result)) > 50)

        print(f"      plan: {[(s.step_id, s.depends_on) for s in execution.plan]}")
        print(f"      facts: {list(execution.truth.facts.keys())[:6]}")

        # Persistence round-trip (#73) - snapshot -> rehydrate
        snapshot = json.loads(json.dumps(execution.to_full_dict(), default=str))
        from jarviscore.planning.goal_context import GoalExecution
        restored = GoalExecution.from_snapshot(snapshot)
        check("snapshot rehydrates plan + history (#73)",
              len(restored.plan) == len(execution.plan)
              and len(restored.completed) == len(execution.completed))
        ctx = restored.context_for_next_step()
        check("restored execution chains context (#72/#73)",
              isinstance(ctx.get("_goal_facts"), dict)
              and len(ctx.get("_completed_steps", [])) == len(execution.completed))
    finally:
        await mesh.stop()

    print()
    if failures:
        print(f"{FAIL} Goal-mode journey: {len(failures)} failure(s): {failures}")
        sys.exit(1)
    print(f"{PASS} Goal-mode journey: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
