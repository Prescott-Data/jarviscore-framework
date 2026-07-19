#!/usr/bin/env python3
"""Production harness: an AutoAgent swarm with plan mode on (REAL LLM).

Persona: a developer building a research swarm with AutoAgent and
goal_oriented=True, then running it the way production traffic arrives:
simple asks mixed with genuinely complex goals, repeated sessions on
the same agent, and a mixed-profile swarm workflow.

Targets the two reported production failures directly:
1. "Plan mode plans everything" - simple asks must route direct to the
   Kernel (planner_mode=direct_kernel); only complex work may plan.
2. "Context grows unendingly" - per-step input tokens inside a goal must
   stay bounded, and repeated tasks on one agent must not inflate.

Requires live LLM credentials (source billy/.env).
"""
import asyncio
import sys

PASS, FAIL = "✅", "❌"
failures = []


def check(name, cond, detail=""):
    print(f"  {PASS if cond else FAIL} {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def step_input_tokens(execution):
    """Per-step input token trajectory from a GoalExecution."""
    out = []
    for cs in getattr(execution, "completed", []) or []:
        meta = getattr(getattr(cs, "output", None), "metadata", None) or {}
        toks = meta.get("tokens") or {}
        out.append(int(toks.get("input", 0) or 0))
    return out


async def main():
    from jarviscore import Mesh, AutoAgent

    class ResearchLead(AutoAgent):
        role = "research_lead"
        capabilities = ["research", "analysis", "writing"]
        goal_oriented = True
        system_prompt = (
            "You are a concise research analyst. Keep every answer under "
            "150 words. Never use web search - reason from knowledge."
        )

    class BriefWriter(AutoAgent):
        role = "brief_writer"
        capabilities = ["writing"]
        system_prompt = "You write tight one-paragraph executive briefs."

    print("== Production AutoAgent swarm (live LLM) ==")
    mesh = Mesh()
    mesh.add(ResearchLead)
    mesh.add(BriefWriter)
    await mesh.start()

    try:
        lead = mesh.get_agent("research_lead")

        # ── Phase 1: triage - plan mode must NOT plan everything ──────
        print("\n-- Phase 1: triage under goal_oriented=True --")
        simple_asks = [
            "What does ETL stand for? One sentence.",
            "Is this sentence positive or negative: 'The rollout went smoothly.' One word.",
            "Summarize in one line: caching reduces repeated computation by storing results.",
        ]
        misplanned = []
        for ask in simple_asks:
            r = await lead.execute_task({"task": ask})
            ge = r.get("goal_execution") or {}
            if ge.get("planner_mode") != "direct_kernel":
                misplanned.append((ask[:40], ge.get("planner_mode"),
                                   ge.get("total_steps_planned")))
            print(f"      [{ge.get('complexity', '?')}] {ask[:60]}")
        check("simple asks route direct to Kernel, never the Planner",
              not misplanned, f"misplanned: {misplanned}")

        complex_ask = (
            "Create a complete incident-response playbook for a small trading "
            "desk covering data, execution, and infrastructure failures. "
            "Part 1: inventory at least six failure modes across the three "
            "areas. Part 2: define detection signals for each failure mode "
            "from part 1. Part 3: write a response runbook for each failure "
            "mode, drawing on parts 1 and 2. Part 4: write an executive "
            "summary that references every earlier part. Each part depends "
            "on the ones before it - this cannot be answered in one response."
        )
        r = await lead.execute_task({"task": complex_ask})
        ge = r.get("goal_execution") or {}
        planned = ge.get("planner_mode") != "direct_kernel" and ge.get("total_steps_planned", 0) >= 2
        check("genuinely complex work does plan",
              r.get("status") == "success" and planned,
              f"status={r.get('status')} goal_execution={ge}")
        check("planned goal reports real token telemetry (#63)",
              (r.get("tokens") or {}).get("total", 0) > 0)

        # ── Phase 2: context stays bounded inside a goal ──────────────
        print("\n-- Phase 2: context growth inside a goal --")
        execution = await lead.execute_goal(
            "Write a four-part operations handbook for a small trading desk: "
            "(1) data-quality checks, (2) execution risk controls, "
            "(3) incident response steps, (4) a summary page that draws on "
            "all three earlier parts.",
            max_steps=8,
        )
        check("goal completes", execution.status == "complete",
              f"status={execution.status} error={execution.error}")
        traj = step_input_tokens(execution)
        real = [t for t in traj if t > 0]
        print(f"      input-token trajectory per step: {traj}")
        check("per-step input tokens stay under budget ceiling",
              all(t < 40_000 for t in traj), f"trajectory={traj}")
        # Per-step totals are cumulative across a step's OODA turns, so they
        # vary with turn count. Unbounded context growth has a distinct
        # signature: a compounding monotonic climb that ends far above where
        # it started. Oscillation is turn-count variance, not growth.
        if len(real) >= 3:
            climbing = all(real[i + 1] > real[i] * 1.15 for i in range(len(real) - 1))
            check("context does not compound step over step",
                  not (climbing and real[-1] > real[0] * 3),
                  f"monotonic climb, trajectory={traj}")
        check("facts accumulate without exploding the prompt",
              0 < len(execution.truth.facts) <= 50,
              f"{len(execution.truth.facts)} facts")

        # ── Phase 3: repeated sessions on one agent stay flat ─────────
        print("\n-- Phase 3: repeated sessions, same agent --")
        flat_ask = "Name one benefit of code review. One sentence."
        inputs = []
        for i in range(4):
            r = await lead.execute_task({"task": flat_ask})
            toks = (r.get("tokens") or {}).get("input", 0)
            inputs.append(int(toks or 0))
            ok = r.get("status") == "success"
            if not ok:
                check(f"repeat {i + 1} succeeds", False, str(r)[:150])
        print(f"      input tokens across identical asks: {inputs}")
        pos = [t for t in inputs if t > 0]
        check("no state bleeds across tasks (flat input tokens)",
              len(pos) >= 2 and max(pos) < min(pos) * 2 + 1500,
              f"inputs={inputs}")

        # ── Phase 4: mixed-profile swarm workflow ─────────────────────
        print("\n-- Phase 4: mixed swarm workflow --")
        results = await mesh.workflow("swarm-brief", [
            {"id": "facts", "agent": "research_lead",
             "task": "List three facts about rate limiting in APIs. Be brief."},
            {"id": "brief", "agent": "brief_writer",
             "task": "Write a one-paragraph brief on why APIs need rate limiting.",
             "context": {"execution_contract": {"execution_shape": "single_response"}}},
        ])
        by_id = {r.get("step_id"): r for r in results}
        check("swarm workflow: both agents succeed",
              all(r.get("status") == "success" for r in results),
              f"{[(r.get('step_id'), r.get('status'), str(r.get('error'))[:80]) for r in results]}")
        check("swarm workflow: single_response bypassed the kernel",
              by_id.get("brief", {}).get("execution_shape") == "single_response",
              f"envelope keys: {list(by_id.get('brief', {}).keys())}")
        check("swarm workflow: telemetry present on both steps",
              all((r.get("tokens") or {}).get("total", 0) > 0 for r in results))
    finally:
        await mesh.stop()

    print()
    if failures:
        print(f"{FAIL} AutoAgent swarm: {len(failures)} failure(s): {failures}")
        sys.exit(1)
    print(f"{PASS} AutoAgent swarm: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
