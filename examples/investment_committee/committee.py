"""
Investment Committee — Entry Point

Run modes:
  python committee.py --mode quick  --ticker AAPL
  python committee.py --mode full   --ticker NVDA --amount 1500000
  python committee.py --mode full   --ticker AMD  --amount 2000000
"""

import argparse
import asyncio
import json
import os
import time

from jarviscore import Mesh

from agents.committee_chair   import CommitteeChairAgent
from agents.financial_analyst import FinancialAnalystAgent
from agents.knowledge_agent   import KnowledgeAgent
from agents.market_analyst    import MarketAnalystAgent
from agents.memo_writer       import MemoWriterAgent
from agents.risk_officer      import RiskOfficerAgent
from agents.technical_analyst import TechnicalAnalystAgent

REDIS_URL      = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "portfolio.json")

# ── Step Definitions ─────────────────────────────────────────────────────────

FULL_STEPS = [
    {
        "id": "market_analysis",
        "agent": "market_analyst",
        "task": (
            "Analyse macro environment, sector rotation, and recent news for {ticker}. "
            "Use yfinance for price/volume data. ticker and mandate are in context."
        ),
    },
    {
        "id": "financial_analysis",
        "agent": "financial_analyst",
        "task": (
            "Analyse fundamentals and valuation for {ticker}. "
            "Pull P/E, P/S, EV/EBITDA, revenue growth, margins, FCF yield via yfinance. "
            "Score: valuation (1-10), growth_quality (1-10), overall (1-10). "
            "ticker and mandate are in context."
        ),
    },
    {
        "id": "technical_analysis",
        "agent": "technical_analyst",
        "task": (
            "Analyse price action for {ticker}: trend, momentum, RSI, "
            "50/200-day MA crossover, entry/exit framing. "
            "Use yfinance 1y daily data. ticker is in context."
        ),
    },
    {
        "id": "knowledge_retrieval",
        "agent": "knowledge_agent",
        "task": (
            "Retrieve prior committee research and memos for {ticker}. "
            "Summarise key precedents, past decisions, and known pitfalls. "
            "ticker is in context."
        ),
    },
    {
        "id": "risk_assessment",
        "agent": "risk_officer",
        "task": (
            "Assess risk for a {amount} USD position in {ticker}. "
            "Check mandate compliance (position limits, sector cap, liquidity). "
            "Compute simple VaR (95%, 1-day). Recommend position size. "
            "ticker, amount, mandate, portfolio, previous_step_results are in context."
        ),
        "depends_on": ["market_analysis", "financial_analysis"],
    },
    {
        "id": "memo_draft",
        "agent": "memo_writer",
        "task": (
            "Write a formal investment memo for the committee decision on {ticker}. "
            "Synthesise all prior step outputs from previous_step_results. "
            "Structure: Executive Summary, Market, Fundamentals, Technical, Risk, Prior Research."
        ),
        "depends_on": [
            "market_analysis", "financial_analysis", "technical_analysis",
            "knowledge_retrieval", "risk_assessment",
        ],
    },
    {
        "id": "final_decision",
        "agent": "committee_chair",
        "task": (
            "Review the memo and all analyses. Make the final allocation decision "
            "for {ticker}. State: BUY/HOLD/PASS, allocation_usd, rationale, conditions."
        ),
        "depends_on": ["memo_draft"],
    },
]

QUICK_STEPS = [
    {
        "id": "financial_analysis",
        "agent": "financial_analyst",
        "task": (
            "Quick check: current P/E, P/S, EV/EBITDA for {ticker} "
            "and score fundamentals 1-10. ticker is in context."
        ),
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def _index_results(results, steps) -> dict:
    """Map step id → result using step order (engine returns list in step order)."""
    if isinstance(results, dict):
        return results
    by_id = {}
    for i, r in enumerate(results):
        # Try explicit step_id first, fall back to step definition order
        sid = r.get("step_id") or r.get("id")
        if not sid and i < len(steps):
            sid = steps[i].get("id")
        if sid:
            by_id[sid] = r
    return by_id


def _print_results(results, mode: str, steps: list):
    by_id = _index_results(results, steps)

    if mode == "quick":
        fin = by_id.get("financial_analysis", {})
        out = fin.get("output", {})
        print(f"\n  Ticker financials:")
        print(f"  P/E:   {out.get('pe_trailing')}")
        print(f"  P/S:   {out.get('price_to_sales')}")
        print(f"  Score: {out.get('overall_score')}/10  ({out.get('verdict', '')})")
    else:
        dec = by_id.get("final_decision", {})
        out = dec.get("output", {})
        alloc = out.get("allocation_usd", 0)
        print(f"\n  ┌─ COMMITTEE DECISION {'─'*40}")
        print(f"  │  Ticker:     {out.get('ticker')}")
        print(f"  │  Action:     {out.get('action')}")
        print(f"  │  Allocation: ${alloc:,.0f}")
        print(f"  │  Conviction: {out.get('conviction')}")
        print(f"  │  Rationale:  {out.get('rationale')}")
        if out.get("conditions"):
            print(f"  │  Conditions: {'; '.join(out['conditions'])}")
        print(f"  └──────────────────────────────────────────────────────\n")
        print("  Full memo written to data/memos/")


# ── Main Runner ──────────────────────────────────────────────────────────────

async def run_committee(ticker: str, amount: float, mode: str = "full"):
    portfolio = load_portfolio()

    mesh = Mesh(mode="autonomous", config={"redis_url": REDIS_URL})
    for AgentClass in [
        MarketAnalystAgent,
        FinancialAnalystAgent,
        TechnicalAnalystAgent,
        RiskOfficerAgent,
        KnowledgeAgent,
        MemoWriterAgent,
        CommitteeChairAgent,
    ]:
        mesh.add(AgentClass)

    await mesh.start()

    print(f"\n{'='*60}")
    print(f"  Investment Committee | {mode.upper()} | {ticker} | ${amount:,.0f}")
    print(f"{'='*60}\n")

    base_steps = QUICK_STEPS if mode == "quick" else FULL_STEPS
    wf_id  = f"committee-{ticker}-{int(time.time())}"

    # Inject workflow-level vars via step["params"] — the CommitteeAutoAgent
    # base class merges these into task["context"] before sandbox execution.
    params = {
        "ticker":    ticker,
        "amount":    amount,
        "mandate":   portfolio.get("constraints", {}),
        "portfolio": portfolio,
    }
    steps = [{**s, "params": params} for s in base_steps]

    try:
        results = await mesh.workflow(wf_id, steps)
        print("\n[Committee] Workflow complete.")
        _print_results(results, mode, steps)
        return results
    finally:
        await mesh.stop()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Investment Committee")
    parser.add_argument("--mode",   default="full",    choices=["quick", "full", "portfolio"])
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--amount", type=float, default=1_500_000)
    args = parser.parse_args()

    asyncio.run(run_committee(args.ticker, args.amount, args.mode))
