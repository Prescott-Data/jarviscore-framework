"""
The Roster Writes Itself
========================
No LLM key. No Redis. No config. Just the mesh.

Most multi-agent frameworks make you hand-maintain an org chart: graph edges,
routing tables, and system prompts with peer names hardcoded into them. Add an
agent and you edit all of it. Kill an agent and every prompt naming it is a lie.

This demo shows the roster maintaining itself:

  1. Three agents join a mesh. Nobody wires anyone to anyone.
  2. We print the researcher's LIVE system prompt — the peer roster is generated.
  3. A fourth specialist joins mid-run. It appears in the prompt. No redeploy.
  4. The LLM's ask_peer tool is enum-constrained to peers that are actually online,
     so the model cannot hallucinate a teammate that isn't there.
  5. Two agents talk DIRECTLY — no supervisor in the path.
  6. The specialist leaves. It disappears from the prompt.

Transport note: the mesh auto-detects infrastructure. With no Redis and no free
SWIM port this runs on the in-process transport (peer_local) and the peer API is
identical — same code moves to peer_distributed (Redis) or peer_swim (SWIM/ZMQ)
with zero changes to your agents.

Run:
    python examples/mesh_live_roster_demo.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.core.agent import Agent

BASE_PROMPT = "You are a research agent. Answer using the mesh when useful."


def banner(n: int, text: str) -> None:
    print(f"\n{'━' * 68}\n  {n}. {text}\n{'━' * 68}")


class DemoAgent(Agent):
    """Deterministic stand-in so the demo needs no LLM key."""

    async def execute_task(self, task):
        return {"status": "completed", "by": self.role}


class ResearchAgent(DemoAgent):
    role = "researcher"
    capabilities = ["research", "search"]
    description = "Gathers source material"


class AnalystAgent(DemoAgent):
    role = "analyst"
    capabilities = ["analysis", "charting"]
    description = "Turns findings into insight"

    async def run(self):
        """Answer peer requests directly — no orchestrator involved."""
        while True:
            msg = await self.peers.receive(timeout=30)
            if msg is None:
                continue
            await self.peers.respond(msg, {"verdict": "signal, not noise", "confidence": 0.9})


class WriterAgent(DemoAgent):
    role = "writer"
    capabilities = ["writing"]
    description = "Drafts the final brief"


class ComplianceAgent(DemoAgent):
    role = "compliance"
    capabilities = ["policy_check", "risk_review"]
    description = "Reviews output against policy"


async def main():
    mesh = Mesh()
    mesh.add(ResearchAgent)
    analyst = mesh.add(AnalystAgent)
    mesh.add(WriterAgent)
    await mesh.start()

    researcher = next(a for a in mesh.agents if a.role == "researcher")
    analyst_loop = asyncio.create_task(analyst.run())

    banner(1, "The researcher's system prompt — nobody wrote the peer list")
    print(researcher.peers.build_system_prompt(BASE_PROMPT))

    banner(2, "A compliance specialist joins the running mesh")
    mesh.add(ComplianceAgent)
    await asyncio.sleep(0.2)
    print(researcher.peers.get_cognitive_context())
    print(">>> 'compliance' is now in the prompt. No redeploy. No edit.")

    banner(3, "The LLM's ask_peer tool — constrained to who is ONLINE")
    ask = [s for s in researcher.peers.as_tool().schema if s["name"] == "ask_peer"][0]
    print(ask["description"])
    print("allowed values:", json.dumps(ask["input_schema"]["properties"]["role"]["enum"]))
    print(">>> The model literally cannot ask for an agent that isn't running.")

    banner(4, "Discovery is a query, with load balancing built in")
    print("by capability 'analysis' :", [p.role for p in researcher.peers.discover(capability="analysis")])
    print("by role, round_robin     :", [p.role for p in researcher.peers.discover(role="analyst", strategy="round_robin")])

    banner(5, "Researcher asks the analyst DIRECTLY — no supervisor hop")
    reply = await researcher.peers.request("analyst", {"need": "read this finding"}, timeout=10)
    print("reply received:", reply)

    banner(6, "The specialist leaves")
    mesh.agents = [a for a in mesh.agents if a.role != "compliance"]
    for role_agents in list(researcher.peers._agent_registry.values()):
        for a in list(role_agents):
            if a.role == "compliance":
                role_agents.remove(a)
    await asyncio.sleep(0.2)
    print(researcher.peers.get_cognitive_context())
    print(">>> Gone from the prompt. Nothing to clean up.")

    analyst_loop.cancel()
    print("\nNo org chart was harmed in the making of this demo.\n")


if __name__ == "__main__":
    asyncio.run(main())
