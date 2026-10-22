"""Two agents: a scout reads the live web, an analyst turns it into a brief."""
import asyncio

from jarviscore import AutoAgent, Mesh


class Scout(AutoAgent):
    role = "scout"
    capabilities = ["web_research"]
    system_prompt = "You find primary sources on the live web and cite every fact."


class Analyst(AutoAgent):
    role = "analyst"
    capabilities = ["analysis", "reporting"]
    system_prompt = "You turn sourced research into a short decision brief."


async def main():
    mesh = Mesh()
    mesh.add(Scout)
    mesh.add(Analyst)
    await mesh.start()
    try:
        results = await mesh.workflow("vector-db-brief", [
            {"agent": "scout",
             "task": "How do pgvector, Qdrant and Weaviate differ on hybrid search "
                     "and filtering? Read their official docs."},
            {"agent": "analyst", "depends_on": [0],
             "task": "Write a five-line brief: which to pick, for whom, with sources."},
        ])
        print(results[-1]["result_summary"])
    finally:
        await mesh.stop()


asyncio.run(main())
