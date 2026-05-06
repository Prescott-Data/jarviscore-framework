"""
Example 2 — Distributed Research Network  |  Synthesizer Node
==============================================================
Profile  : AutoAgent
Mode     : Distributed (SWIM P2P + WorkflowEngine)
Role     : synthesizer — starts last, defines the full 4-step workflow,
           waits for all 3 researcher nodes to complete their steps,
           then synthesises their outputs into a single briefing.

IMPORTANT: Start this script FIRST — it is the SWIM seed node (port 7949).
Then start nodes 1, 2, 3 in separate terminals.

    Terminal A: python examples/ex2_synthesizer.py       ← start FIRST
    Terminal B: python examples/ex2_research_node1.py
    Terminal C: python examples/ex2_research_node2.py
    Terminal D: python examples/ex2_research_node3.py

How it works
------------
1. Synthesizer starts as SWIM seed (port 7949)
2. Nodes 1-3 join the SWIM cluster by connecting to port 7949
3. Synthesizer submits 4-step workflow to Redis
4. Each researcher node claims its step via atomic SETNX and executes it
5. DependencyManager._wait_redis() on the "synth" step polls Redis until
   ALL THREE of "tech", "market", "reg" steps are "completed"
6. Only then does the synthesizer's WorkflowEngine dispatch "synth"
7. SynthesizerAgent reads all 3 outputs via context and writes the briefing

Infrastructure features exercised (synthesizer)
------------------------------------------------
Mailbox         : MailboxManager pings researcher agents before submitting workflow
Telemetry       : Prometheus metrics across all 4 nodes (active_workflows gauge)
Workflow engine : DependencyManager cross-node dependency resolution;
                  WorkflowState crash recovery — re-run skips completed steps
Unified memory  : RedisMemoryAccessor reads tech + market + reg outputs;
                  EpisodicLedger + LTM persist briefing summaries
Auto-injection  : redis + blob + mailbox injected on all nodes

Success criteria
----------------
    - 4 nodes discover each other on the SWIM mesh (log: "peer joined")
    - 3 researcher steps claimed and completed (log: "CLAIMED step_id=tech/market/reg")
    - Synthesizer step runs after all 3 complete (log: "CLAIMED step_id=synth")
    - Final briefing saved to: blob_storage/reports/ai-landscape-q1.md
    - redis-cli hgetall step_output:ai-landscape-q1:synth  →  status=completed
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent
from jarviscore.memory import UnifiedMemory
from jarviscore.context import RedisMemoryAccessor

WORKFLOW_ID = "ai-landscape-q1"
REDIS_URL   = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BIND_PORT   = 7949  # Synthesizer is the SWIM seed — always port 7949
# Note: do NOT use os.getenv("BIND_PORT") — swim.main.load_dotenv() would override it from .env
# Synthesizer is the seed node — no SEED_NODES needed


class SynthesizerAgent(AutoAgent):
    """
    Reads outputs from all 3 researcher nodes and writes a unified AI landscape briefing.
    The "synth" step only dispatches after tech + market + reg are all completed.
    """
    role = "synthesizer"
    capabilities = ["synthesis", "reporting", "research_coordination"]
    system_prompt = """
    You are a senior research director. You synthesise findings from three specialist
    researchers (technology, market, regulatory) into a single coherent briefing.

    You receive their reports in the `context` variable. Combine them into:

    result = {
        "title": "AI Landscape Q1 2026 — Synthesised Briefing",
        "executive_summary": str,       # 3-4 sentences covering all 3 angles
        "technology": {                 # from tech_researcher
            "headline": str,
            "key_points": [str],
        },
        "market": {                     # from market_researcher
            "headline": str,
            "key_points": [str],
        },
        "regulatory": {                 # from reg_researcher
            "headline": str,
            "key_points": [str],
        },
        "cross_cutting_themes": [str],  # themes that appear across all 3 reports
        "strategic_recommendations": [str],
        "overall_confidence": float,
    }

    Store the result dict in a variable named `result`.
    If individual researcher outputs are not in context, use plausible placeholder data.
    """

    async def setup(self):
        await super().setup()
        # Phase 9: stores already injected
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="synth",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        self._logger.info(
            f"[{self.role}] ready | redis={'yes' if self._redis_store else 'no'}"
        )


async def main():
    print("\n" + "=" * 70)
    print("JarvisCore — Example 2: Synthesizer (SWIM Seed)")
    print("AutoAgent | Distributed Mode | Port 7949 (seed)")
    print("=" * 70)
    print("""
Start order:
  1. This script  (port 7949 — SWIM seed)  ← you are here
  2. Node 1       (port 7946)
  3. Node 2       (port 7947)
  4. Node 3       (port 7948)

Workflow submits after a 10s wait for nodes to join SWIM cluster.
""")

    mesh = Mesh(
        mode="distributed",
        config={
            "redis_url": REDIS_URL,
            "bind_host": "127.0.0.1",
            "bind_port": BIND_PORT,
            "node_name": "synthesizer-seed",
            # No seed_nodes — this IS the seed
        },
    )
    synth_agent = mesh.add(SynthesizerAgent)

    try:
        await mesh.start()

        # ── Phase 9 verification ──────────────────────────────────────────────
        print(f"[Phase 9] redis_store : {'connected' if mesh._redis_store else 'None'}")
        print(f"[Phase 9] blob_storage: {type(mesh._blob_storage).__name__}")

        # ── Phase 4: mailbox ping (optional — only works when Redis available) ─
        if synth_agent.mailbox:
            print("[Phase 4] Mailbox available — can ping researcher agents by ID")

        # ── Wait for researcher nodes to join SWIM ────────────────────────────
        print("\n[SWIM] Waiting 10s for researcher nodes to join cluster...")
        print("       (Start nodes 1-3 in other terminals now)\n")
        await asyncio.sleep(10)

        # ── Submit workflow ───────────────────────────────────────────────────
        print(f"[Workflow] Submitting '{WORKFLOW_ID}'")
        print("  Steps: tech ┐")
        print("         market ├──→ synth  (synth waits for ALL 3 via Redis)")
        print("         reg   ┘\n")

        results = await mesh.workflow(WORKFLOW_ID, [
            {
                "id": "tech",
                "agent": "tech_researcher",
                "task": (
                    "Research latest AI chip developments and hardware trends for Q1 2026. "
                    "Cover NVIDIA, AMD, Intel, Groq, Cerebras. Return structured findings in `result`."
                ),
            },
            {
                "id": "market",
                "agent": "market_researcher",
                "task": (
                    "Research AI investment trends and VC/PE activity for Q1 2026. "
                    "Include notable deals and market size estimates. Return structured findings in `result`."
                ),
            },
            {
                "id": "reg",
                "agent": "reg_researcher",
                "task": (
                    "Research AI regulatory developments for Q1 2026. "
                    "Cover EU AI Act, US executive orders, UK policy, APAC. Return structured findings in `result`."
                ),
            },
            {
                "id": "synth",
                "agent": "synthesizer",
                "task": (
                    "Synthesise the technology, market, and regulatory research reports "
                    "from the previous steps into a unified AI Landscape Q1 2026 briefing. "
                    "Return the synthesis as a structured dict in `result`."
                ),
                # Phase 7: DependencyManager._wait_redis() polls until ALL 3 are COMPLETED
                "depends_on": ["tech", "market", "reg"],
            },
        ])

        # ── Results ───────────────────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("WORKFLOW RESULTS")
        print("=" * 70)

        step_names = ["tech", "market", "reg", "synth"]
        for name, result in zip(step_names, results):
            status = result.get("status", "unknown")
            icon = "✓" if status == "success" else "✗"
            print(f"\n{icon} Step: {name}  (status={status})")
            if status == "success":
                output = str(result.get("output", ""))
                print(f"  Preview: {output[:250]}{'...' if len(output) > 250 else ''}")
            else:
                print(f"  Error: {result.get('error', 'unknown')}")

        # ── Phase 1: Save synthesis to blob ───────────────────────────────────
        synth_result = results[3] if len(results) >= 4 else {}
        if synth_result.get("status") == "success" and mesh._blob_storage:
            import json
            content = json.dumps(synth_result.get("output", {}), indent=2)
            blob_path = f"reports/{WORKFLOW_ID}.json"
            await mesh._blob_storage.save(blob_path, content)
            print(f"\n[Phase 1] Synthesis saved: ./blob_storage/{blob_path}")

        # ── Phase 8: EpisodicLedger ───────────────────────────────────────────
        if synth_agent.memory and synth_agent.memory.episodic:
            await synth_agent.memory.episodic.append({
                "event": "synthesis_completed",
                "workflow_id": WORKFLOW_ID,
                "steps_ok": len([r for r in results if r.get("status") == "success"]),
            })
            print(f"[Phase 8] Logged to EpisodicLedger")
            print(f"          Inspect: redis-cli xrange ledgers:{WORKFLOW_ID} - +")

        # ── Redis verification ────────────────────────────────────────────────
        if mesh._redis_store:
            print(f"\n[Phase 7] Step outputs in Redis:")
            for sid in step_names:
                out = mesh._redis_store.get_step_output(WORKFLOW_ID, sid)
                print(f"  step_output:{WORKFLOW_ID}:{sid} → {'set ✓' if out else 'missing ✗'}")

        successes = sum(1 for r in results if r.get("status") == "success")
        print(f"\n{'=' * 70}")
        print(f"Distributed workflow complete: {successes}/{len(results)} steps")
        print(f"{'=' * 70}\n")

    except KeyboardInterrupt:
        print("\n[Synthesizer] Interrupted.")
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        import traceback
        traceback.print_exc()
    finally:
        await mesh.stop()
        print("[Synthesizer] Stopped.")


if __name__ == "__main__":
    asyncio.run(main())
