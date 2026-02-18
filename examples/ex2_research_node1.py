"""
Example 2 — Distributed Research Network  |  Node 1: Technology Researcher
===========================================================================
Profile  : AutoAgent
Mode     : Distributed (SWIM P2P + WorkflowEngine)
Role     : tech_researcher — covers AI chip developments and hardware trends

Run order
---------
Start the synthesizer FIRST (it is the SWIM seed), then start nodes 1-3:

    Terminal A: python examples/ex2_synthesizer.py          # starts on port 7949
    Terminal B: python examples/ex2_research_node1.py       # connects to 7949
    Terminal C: python examples/ex2_research_node2.py       # connects to 7949
    Terminal D: python examples/ex2_research_node3.py       # connects to 7949

The synthesizer submits the 4-step workflow. The Mesh's built-in distributed
worker scans Redis for pending steps matching each node's capabilities and
claims them atomically — no manual wiring or step-ID knowledge needed.

Phases exercised (node 1)
--------------------------
Phase 2  : SWIM P2P joins synthesizer cluster, ZMQ messaging
Phase 5  : Prometheus metrics (PROMETHEUS_ENABLED=true in .env)
Phase 7  : Mesh._run_distributed_worker() claims "tech" step via Redis SETNX
Phase 8  : UnifiedMemory (EpisodicLedger tracks every search query made)
Phase 9  : Auto-injected redis + blob + mailbox before setup()
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
BIND_PORT    = 7946  # Node 1 — fixed port (swim.main.load_dotenv() would corrupt os.getenv)
SEED_NODES   = "127.0.0.1:7949"   # synthesizer is always the seed


class TechResearchAgent(AutoAgent):
    """
    Researches latest AI chip and hardware developments.
    Runs as node 1 in the distributed research network.
    """
    role = "tech_researcher"
    capabilities = ["tech_research", "ai_hardware", "research"]
    system_prompt = """
    You are a technology research specialist focused on AI infrastructure and chips.

    Research the following topic and produce a structured report using Python:

    result = {
        "topic": "AI chip developments",
        "key_findings": [str, ...],    # 3-5 bullet points
        "notable_companies": [str],    # e.g. NVIDIA, AMD, Intel, Groq, Cerebras
        "trends": [str],               # e.g. "inference chip market growing 40% YoY"
        "outlook": str,                # 2-3 sentence forward-looking summary
        "confidence": float,           # 0.0 - 1.0
    }

    Use your knowledge to generate realistic, informative findings.
    Store the result dict in a variable named `result`.
    """

    async def setup(self):
        await super().setup()
        # Phase 9: stores auto-injected before setup() is called
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="tech",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        self._logger.info(
            f"[{self.role}] ready | redis={'yes' if self._redis_store else 'no'}"
        )


async def main():
    print("\n" + "=" * 70)
    print("JarvisCore — Example 2: Node 1 (Technology Researcher)")
    print("AutoAgent | Distributed Mode | Port 7946 → Seed 7949")
    print("=" * 70)

    mesh = Mesh(
        mode="distributed",
        config={
            "redis_url": REDIS_URL,
            "bind_host": "127.0.0.1",
            "bind_port": BIND_PORT,
            "seed_nodes": SEED_NODES,
            "node_name": "research-node-1",
        },
    )
    mesh.add(TechResearchAgent)

    try:
        await mesh.start()
        print(f"\n[Node 1] Online at port {BIND_PORT}, seed={SEED_NODES}")
        print(f"[Node 1] Redis: {'connected' if mesh._redis_store else 'None'}")
        print(f"[Node 1] Distributed worker running — will claim 'tech' step automatically")
        print(f"         (capabilities: tech_researcher, tech_research, ai_hardware, research)\n")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        print("\n[Node 1] Shutting down...")
    finally:
        await mesh.stop()
        print("[Node 1] Stopped.")


if __name__ == "__main__":
    asyncio.run(main())
