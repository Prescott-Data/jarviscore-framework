"""kill -9 this workflow halfway, run it again: it finishes without redoing work.

Needs Redis: REDIS_URL=redis://localhost:6379/0
"""
import asyncio

from jarviscore import AutoAgent, Mesh


class Researcher(AutoAgent):
    role = "researcher"
    capabilities = ["research"]
    system_prompt = "You are a rigorous research analyst. Be concise and factual."


class Writer(AutoAgent):
    role = "writer"
    capabilities = ["writing"]
    system_prompt = "You turn analysis into crisp bullet points."


async def main():
    mesh = Mesh()
    mesh.add(Researcher)
    mesh.add(Writer)
    await mesh.start()
    results = await mesh.workflow("incident-brief", [
        {"agent": "researcher",
         "task": "In four sentences: why do multi-agent systems fail in production?"},
        {"agent": "writer", "depends_on": [0],
         "task": "Turn the research into three short bullets for an engineering lead."},
    ])
    for number, step in enumerate(results, 1):
        state = "recovered, not re-run" if step.get("recovered") else step["status"]
        print(f"step {number}: {state}")
    print("\n" + results[-1]["result_summary"])
    await mesh.stop()


asyncio.run(main())
