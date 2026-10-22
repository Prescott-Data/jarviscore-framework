"""An analyst that computes its figures with code instead of estimating them."""
import asyncio
from pathlib import Path

from jarviscore import AutoAgent, Mesh

SALES = Path(__file__).parent / "data" / "sales.csv"


class DataAnalyst(AutoAgent):
    role = "data_analyst"
    capabilities = ["data_analysis", "python"]
    system_prompt = "You are a careful data analyst. Compute every figure with code."


async def main():
    mesh = Mesh()
    mesh.add(DataAnalyst)
    await mesh.start()
    try:
        result = await mesh.run_task(agent="data_analyst", task=(
            f"Read {SALES}. Revenue is units * unit_price. Report total revenue per "
            "region and each region's growth from Q1 (months 1-3) to Q2 (months 4-6). "
            "Which region grew most?"
        ))
        print(result["result_summary"])
    finally:
        await mesh.stop()


asyncio.run(main())
