"""
Example 2 — Distributed Research Network  |  Node 3: Regulatory Researcher
===========================================================================
Profile  : AutoAgent
Mode     : Distributed (SWIM P2P + WorkflowEngine)
Role     : reg_researcher — covers AI regulation and policy developments

Run after starting the synthesizer (port 7949):
    python examples/ex2_research_node3.py

Phases exercised (node 3)
--------------------------
Phase 2  : SWIM P2P joins synthesizer cluster
Phase 7  : Mesh._run_distributed_worker() claims "reg" step via atomic Redis SETNX
Phase 8  : EpisodicLedger + LTM (policy summaries persist across weekly runs)
Phase 9  : Auto-injected redis + blob + mailbox
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent
from jarviscore.memory import UnifiedMemory

WORKFLOW_ID  = "ai-landscape-q1"
REDIS_URL    = os.getenv("REDIS_URL", "redis://localhost:6379/0")
BIND_PORT    = 7948  # Node 3 — fixed port (swim.main.load_dotenv() would corrupt os.getenv)
SEED_NODES   = "127.0.0.1:7949"   # synthesizer is always the seed


class RegResearchAgent(AutoAgent):
    """
    Researches AI regulatory landscape and policy developments.
    Runs as node 3 in the distributed research network.
    """
    role = "reg_researcher"
    capabilities = ["regulatory_research", "policy_analysis", "research"]
    system_prompt = """
    You are a regulatory research specialist covering AI governance and policy.

    Research the following topic and produce a structured report using Python:

    result = {
        "topic": "AI regulation and governance",
        "key_findings": [str, ...],       # 3-5 bullet points on recent regulations
        "active_regulations": [           # 2-4 key regulations or frameworks
            {"name": str, "jurisdiction": str, "status": str, "impact": str}
        ],
        "risk_areas": [str],              # Areas of high regulatory risk for AI cos
        "compliance_outlook": str,        # "tightening" | "stable" | "uncertain"
        "regional_summary": {
            "EU": str,
            "US": str,
            "UK": str,
            "APAC": str,
        },
        "outlook": str,
        "confidence": float,
    }

    Use your knowledge to generate realistic, informative findings.
    Store the result dict in a variable named `result`.
    """

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="reg",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        # Phase 8: LTM persists regulatory summaries across runs
        if self.memory.ltm:
            prior = await self.memory.ltm.load_summary()
            if prior:
                self._logger.info(f"[{self.role}] LTM loaded from prior run")
        self._logger.info(
            f"[{self.role}] ready | redis={'yes' if self._redis_store else 'no'}"
        )


async def main():
    print("\n" + "=" * 70)
    print("JarvisCore — Example 2: Node 3 (Regulatory Researcher)")
    print("AutoAgent | Distributed Mode | Port 7948 → Seed 7949")
    print("=" * 70)

    mesh = Mesh(
        mode="distributed",
        config={
            "redis_url": REDIS_URL,
            "bind_host": "127.0.0.1",
            "bind_port": BIND_PORT,
            "seed_nodes": SEED_NODES,
            "node_name": "research-node-3",
        },
    )
    mesh.add(RegResearchAgent)

    try:
        await mesh.start()
        print(f"\n[Node 3] Online at port {BIND_PORT}, seed={SEED_NODES}")
        print(f"[Node 3] Redis: {'connected' if mesh._redis_store else 'None'}")
        print(f"[Node 3] Distributed worker running — will claim 'reg' step automatically\n")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n[Node 3] Shutting down...")
    finally:
        await mesh.stop()
        print("[Node 3] Stopped.")


if __name__ == "__main__":
    asyncio.run(main())
