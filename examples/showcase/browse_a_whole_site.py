"""A browser agent reads a whole catalogue, page after page, and reports on it."""
import asyncio

from jarviscore import AutoAgent, Mesh


class Analyst(AutoAgent):
    role = "analyst"
    capabilities = ["web_research", "data_analysis", "reporting"]
    system_prompt = "You collect complete data, compute with code and report clearly."
    goal_oriented = True


async def main():
    mesh = Mesh()
    mesh.add(Analyst)
    await mesh.start()
    try:
        result = await mesh.run_task(agent="analyst", task=(
            "Collect every book in the Mystery category of https://books.toscrape.com, "
            "across all pages, with its title, price and star rating. Report how many "
            "there are, the count per rating, the average price and the three most "
            "expensive, and save the report as mystery_report.md."
        ))
        print(result["result_summary"])
    finally:
        await mesh.stop()


asyncio.run(main())
