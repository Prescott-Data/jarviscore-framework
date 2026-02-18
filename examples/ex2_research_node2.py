"""
Example 2 — Distributed Research Network  |  Node 2: Market Researcher
=======================================================================
Profile  : AutoAgent
Mode     : Distributed (SWIM P2P + WorkflowEngine)
Role     : market_researcher — covers AI investment and venture trends

Run after starting the synthesizer (port 7949):
    python examples/ex2_research_node2.py

Phases exercised (node 2)
--------------------------
Phase 2  : SWIM P2P joins synthesizer cluster
Phase 7  : Mesh._run_distributed_worker() claims "market" step via Redis SETNX;
           crash recovery: kill and restart — SETNX prevents double-execution
Phase 8  : EpisodicLedger tracks research queries per session
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
BIND_PORT    = 7947  # Node 2 — fixed port (swim.main.load_dotenv() would corrupt os.getenv)
SEED_NODES   = "127.0.0.1:7949"   # synthesizer is always the seed


class MarketResearchAgent(AutoAgent):
    """
    Researches AI investment trends and venture capital activity.
    Runs as node 2 in the distributed research network.
    """
    role = "market_researcher"
    capabilities = ["market_research", "investment_analysis", "research"]
    system_prompt = """
    You are a market research specialist covering AI investment and VC activity.

    Research the following topic and produce a structured report using Python:

    result = {
        "topic": "AI investment trends",
        "key_findings": [str, ...],        # 3-5 bullet points on VC/PE activity
        "top_funded_areas": [str],          # e.g. "Inference infrastructure", "AI agents"
        "market_size_estimate": str,        # e.g. "$500B TAM by 2028"
        "investor_sentiment": str,          # "bullish" | "cautious" | "mixed"
        "notable_deals": [                  # 2-3 recent notable investments
            {"company": str, "amount": str, "stage": str}
        ],
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
            step_id="market",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        self._logger.info(
            f"[{self.role}] ready | redis={'yes' if self._redis_store else 'no'}"
        )


async def main():
    print("\n" + "=" * 70)
    print("JarvisCore — Example 2: Node 2 (Market Researcher)")
    print("AutoAgent | Distributed Mode | Port 7947 → Seed 7949")
    print("=" * 70)

    mesh = Mesh(
        mode="distributed",
        config={
            "redis_url": REDIS_URL,
            "bind_host": "127.0.0.1",
            "bind_port": BIND_PORT,
            "seed_nodes": SEED_NODES,
            "node_name": "research-node-2",
        },
    )
    mesh.add(MarketResearchAgent)

    try:
        await mesh.start()
        print(f"\n[Node 2] Online at port {BIND_PORT}, seed={SEED_NODES}")
        print(f"[Node 2] Redis: {'connected' if mesh._redis_store else 'None'}")
        print(f"[Node 2] Distributed worker running — will claim 'market' step automatically")
        print(f"         (crash recovery: kill and restart — SETNX prevents double-execution)\n")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n[Node 2] Shutting down...")
    finally:
        await mesh.stop()
        print("[Node 2] Stopped.")


if __name__ == "__main__":
    asyncio.run(main())
