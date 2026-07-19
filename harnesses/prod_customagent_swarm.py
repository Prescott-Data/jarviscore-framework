#!/usr/bin/env python3
"""Production harness: a CustomAgent swarm under sustained load.

Persona: a developer building a market-data processing desk with
CustomAgent. Four agents with real (deterministic) brains, wired into
DAG pipelines, dynamic fan-out, and then 30 back-to-back workflows on
one mesh to prove the swarm is stable: no cross-workflow contamination,
no timing drift, no unbounded memory growth.

No LLM required. This is the infrastructure contract under load.
"""
import asyncio
import resource
import sys
import time

PASS, FAIL = "✅", "❌"
failures = []


def check(name, cond, detail=""):
    print(f"  {PASS if cond else FAIL} {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def rss_mb():
    # ru_maxrss is bytes on macOS, KB on Linux
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return v / (1024 * 1024) if sys.platform == "darwin" else v / 1024


async def main():
    from jarviscore import Mesh, CustomAgent
    from jarviscore.orchestration.workflow_builder import WorkflowBuilder

    # ── Dana's desk: four agents, real deterministic brains ──────────

    class IngestorAgent(CustomAgent):
        role = "ingestor"
        capabilities = ["ingest"]

        async def on_peer_request(self, msg):
            raw = str(msg.data.get("payload") or msg.data.get("task", ""))
            return {"status": "success", "records": raw.strip().lower().split(",")}

    class AnalystAgent(CustomAgent):
        role = "desk_analyst"
        capabilities = ["analysis"]

        async def on_peer_request(self, msg):
            text = str(msg.data.get("payload") or msg.data.get("task", ""))
            if "poison" in text:
                raise ValueError("upstream feed corrupt for this symbol")
            return {"status": "success", "score": sum(ord(c) for c in text) % 100, "echo": text}

    class RiskAgent(CustomAgent):
        role = "risk"
        capabilities = ["risk"]

        async def on_peer_request(self, msg):
            text = str(msg.data.get("payload") or msg.data.get("task", ""))
            return {"status": "success", "flag": "HIGH" if "9" in text else "LOW", "seen": text[:120]}

    class ReporterAgent(CustomAgent):
        role = "reporter"
        capabilities = ["report"]

        async def on_peer_request(self, msg):
            text = str(msg.data.get("payload") or msg.data.get("task", ""))
            return {"status": "success", "report": f"REPORT[{text[:200]}]"}

    print("== Production CustomAgent swarm ==")
    mesh = Mesh()
    for cls in (IngestorAgent, AnalystAgent, RiskAgent, ReporterAgent):
        mesh.add(cls)
    await mesh.start()

    try:
        # ── Phase 1: DAG pipeline with result references ──────────────
        print("\n-- Phase 1: DAG pipeline --")
        wf = (
            WorkflowBuilder()
            .step("ingest", "ingestor", "AAPL,MSFT,NVDA")
            .step("analyse", "desk_analyst", "analyse: {ingest.result}", depends_on=["ingest"])
            .step("risk", "risk", "risk-check: {analyse.result}", depends_on=["analyse"])
            .step("report", "reporter", "final: {risk.result}", depends_on=["risk"])
            .build(title="desk-pipeline", team="desk")
        )
        results = await wf.execute(mesh)
        by_id = {r["step_id"]: r for r in results}
        check("pipeline: all 4 steps returned", len(results) == 4,
              f"got {[r.get('step_id') for r in results]}")
        check("pipeline: every step succeeded",
              all(r["status"] == "success" for r in results),
              f"{[(r['step_id'], r['status'], r.get('error')) for r in results]}")
        # WorkflowBuilder wraps: result["output"] == {"status", "output": <agent dict>}
        risk_seen = str(by_id.get("risk", {}).get("output", ""))
        check("pipeline: downstream step received upstream output",
              "risk-check" in risk_seen and "score" in risk_seen,
              f"risk saw: {risk_seen[:200]!r}")

        # ── Phase 2: dynamic fan-out with a poison item ───────────────
        print("\n-- Phase 2: fan-out board scan (24 symbols, 1 poison) --")
        symbols = [f"SYM{i:02d}" for i in range(23)] + ["poison-feed"]
        fan = await mesh.fanout(
            "board-scan",
            agent="analysis",
            items=symbols,
            task=lambda s: f"deep-read {s}",
            context=lambda s: {"payload": s},
            concurrency=6,
            budget=20,
            on_error="collect",
        )
        check("fanout: budget honored with skipped reported",
              len(fan.results) == 20 and len(fan.skipped) == 4,
              f"results={len(fan.results)} skipped={fan.skipped}")
        check("fanout: results in item order with identity",
              [r["item"] for r in fan.results] == symbols[:20]
              and all("step_id" in r for r in fan.results))
        check("fanout: partial failure is honest, siblings unaffected",
              len(fan.failed) == 0 and len(fan.succeeded) == 20,
              f"failed={[(f.get('item'), str(f.get('error'))[:60]) for f in fan.failed]}")
        # NOTE: fanout results carry the agent dict under "output" (the
        # workflows guide's fanout example says r["payload"] - doc bug, filed)
        scores = fan.aggregate(lambda rs: [r["output"]["score"] for r in rs if r.get("output")])
        check("fanout: aggregation over typed payloads", len(scores) == 20)

        # poison actually poisons when selected
        fan2 = await mesh.fanout(
            "poison-scan",
            agent="analysis",
            items=["SYMOK", "poison-feed", "SYMOK2"],
            task=lambda s: f"deep-read {s}",
            context=lambda s: {"payload": s},
            concurrency=3,
            on_error="collect",
        )
        check("fanout: poison item fails alone, in collect mode",
              len(fan2.failed) == 1 and len(fan2.succeeded) == 2
              and fan2.failed[0].get("item") == "poison-feed",
              f"failed={[(f.get('item'), str(f.get('error'))[:80]) for f in fan2.failed]}")

        # ── Phase 3: sustained load, 30 workflows on one mesh ─────────
        print("\n-- Phase 3: sustained load (30 workflows, same mesh) --")
        rss_before = rss_mb()
        durations = []
        bleed = 0
        for w in range(30):
            token = f"wf{w:03d}-token"
            t0 = time.monotonic()
            res = await mesh.workflow(f"load-{w}", [
                {"id": "a", "agent": "desk_analyst", "task": f"tick {token}",
                 "context": {"payload": f"tick {token}"}},
                {"id": "b", "agent": "risk", "task": f"risk {token}",
                 "context": {"payload": f"risk {token}"}},
                {"id": "c", "agent": "reporter", "task": f"report {token}",
                 "context": {"payload": f"report {token}"}},
            ])
            durations.append(time.monotonic() - t0)
            ok = (len(res) == 3 and all(r["status"] == "success" for r in res))
            if not ok:
                bleed += 1
                continue
            # cross-workflow contamination check: each payload must carry
            # THIS workflow's token and no other workflow's token
            for r in res:
                blob = str(r.get("output", ""))
                if token not in blob or any(
                    f"wf{x:03d}-token" in blob for x in range(30) if f"wf{x:03d}" != f"wf{w:03d}"
                ):
                    bleed += 1
        rss_after = rss_mb()
        first5 = sum(durations[:5]) / 5
        last5 = sum(durations[-5:]) / 5
        check("load: all 30 workflows correct, zero cross-workflow bleed",
              bleed == 0, f"bleed count={bleed}")
        check("load: no timing drift across the run",
              last5 < max(first5 * 3, first5 + 0.5),
              f"first5={first5:.3f}s last5={last5:.3f}s")
        check("load: memory growth bounded",
              (rss_after - rss_before) < 200,
              f"rss grew {rss_after - rss_before:.1f} MB")
        print(f"      timing: first5={first5 * 1000:.0f}ms last5={last5 * 1000:.0f}ms "
              f"rss: {rss_before:.0f} -> {rss_after:.0f} MB")

        # ── Phase 4: failure semantics do not wedge the mesh ──────────
        print("\n-- Phase 4: failure semantics --")
        wf_fail = (
            WorkflowBuilder()
            .step("bad", "desk_analyst", "poison this one", depends_on=[])
            .step("dependent", "reporter", "needs: {bad.result}", depends_on=["bad"])
            .step("sibling", "risk", "independent risk pass")
            .build(title="failure-semantics", team="desk")
        )
        fres = await wf_fail.execute(mesh)
        fby = {r["step_id"]: r for r in fres}
        check("failure: bad step reports failure with identity",
              fby.get("bad", {}).get("status") == "failure",
              f"bad={fby.get('bad')}")
        check("failure: dependent step is blocked, not silently run",
              fby.get("dependent", {}).get("status") != "success",
              f"dependent={fby.get('dependent', {}).get('status')}")
        check("failure: independent sibling still runs",
              fby.get("sibling", {}).get("status") == "success",
              f"sibling={fby.get('sibling', {}).get('status')}")
        # mesh still healthy after the failure
        after = await mesh.workflow("post-failure", [
            {"id": "ok", "agent": "reporter", "task": "still alive",
             "context": {"payload": "still alive"}},
        ])
        check("failure: mesh healthy after a failed workflow",
              after[0]["status"] == "success")
    finally:
        await mesh.stop()

    print()
    if failures:
        print(f"{FAIL} CustomAgent swarm: {len(failures)} failure(s): {failures}")
        sys.exit(1)
    print(f"{PASS} CustomAgent swarm: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
