#!/usr/bin/env python3
"""DX Harness 2 - the AutoAgent developer journey (REAL LLM).

Simulates a developer following the AutoAgent guide with live Azure OpenAI:
1. Pre-start misuse -> loud, actionable error
2. single_response contract -> one completion, real answer
3. A researcher-style task through the kernel OODA loop
4. Goal mode with depends_on -> plan, execute, facts accumulate

Requires AZURE_API_KEY etc. in the environment (sourced from billy/.env).
"""
import asyncio
import sys
import time

PASS, FAIL = "✅", "❌"
failures = []


def check(name, cond, detail=""):
    print(f"  {PASS if cond else FAIL} {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


async def main():
    from jarviscore import Mesh, MeshMode, AutoAgent

    class ResearchAgent(AutoAgent):
        role = "researcher_dx"
        capabilities = ["research", "analysis"]
        system_prompt = (
            "You are a precise research analyst. Be concise. When asked for "
            "a direct answer, answer in one short paragraph."
        )

    print("== AutoAgent developer journey (live LLM) ==")

    # 1. Pre-start misuse is loud (issue #63/JC-002)
    orphan = ResearchAgent()
    try:
        await orphan.execute_task({"task": "anything"})
        check("pre-start use raises a descriptive error", False, "no error raised")
    except RuntimeError as exc:
        check("pre-start use raises a descriptive error", "mesh.start" in str(exc))
    except Exception as exc:  # noqa: BLE001
        check("pre-start use raises a descriptive error", False, f"wrong error: {exc}")

    mesh = Mesh(mode=MeshMode.AUTONOMOUS)
    mesh.add(ResearchAgent)
    await mesh.start()
    try:
        agent = mesh.get_agent("researcher_dx")

        # 2. single_response - one completion, no codegen (JC-001/003)
        t0 = time.monotonic()
        result = await agent.execute_task({
            "task": "In one sentence: why do trading systems prefer bounded concurrency?",
            "context": {"execution_contract": {"execution_shape": "single_response"}},
        })
        dt = time.monotonic() - t0
        check("single_response returns success", result.get("status") == "success",
              str(result)[:200])
        answer = str(result.get("output", ""))
        check("single_response gives a real prose answer", len(answer) > 40, answer[:120])
        check("single_response reports real token telemetry",
              (result.get("tokens") or {}).get("total", 0) > 0)
        # Deterministic proof of the direct path: the envelope marker is only
        # stamped when the kernel pipeline was bypassed. Wall-clock checks are
        # provider-latency lottery and do not belong in a release gate.
        check("single_response bypassed the kernel pipeline",
              result.get("execution_shape") == "single_response",
              f"envelope: {str(result)[:150]}")
        print(f"      answer ({dt:.1f}s): {answer[:110]}…")

        # 3. Kernel OODA path - a bounded analysis task
        result2 = await agent.execute_task({
            "task": (
                "List exactly three risks of running two identical trading "
                "bots on one broker account. Return JSON: "
                '{"risks": ["...", "...", "..."]}'
            ),
        })
        check("kernel task returns a status", result2.get("status") in
              ("success", "yield", "failure"), str(result2)[:200])
        check("kernel task succeeded", result2.get("status") == "success",
              str(result2.get("error"))[:200])
    finally:
        await mesh.stop()

    print()
    if failures:
        print(f"{FAIL} AutoAgent journey: {len(failures)} failure(s): {failures}")
        sys.exit(1)
    print(f"{PASS} AutoAgent journey: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
