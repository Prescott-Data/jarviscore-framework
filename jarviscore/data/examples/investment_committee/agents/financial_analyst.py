from jarviscore.memory import UnifiedMemory
from agents.base import CommitteeAutoAgent


class FinancialAnalystAgent(CommitteeAutoAgent):
    role = "financial_analyst"
    capabilities = ["financial_analysis", "fundamentals", "valuation"]
    system_prompt = """
You are a senior buy-side financial analyst specialising in fundamental analysis.

Context variables available: ticker, mandate

Your job:
1. Pull fundamentals using yfinance (.info dict)
2. Score the stock on valuation, growth quality, financial health
3. Return a structured result dict stored in `result`

Write Python code:

import yfinance as yf

t = yf.Ticker(ticker)
info = t.info

pe = info.get('trailingPE')
forward_pe = info.get('forwardPE')
ps = info.get('priceToSalesTrailing12Months')
pb = info.get('priceToBook')
ev_ebitda = info.get('enterpriseToEbitda')
revenue_growth = info.get('revenueGrowth')
gross_margin = info.get('grossMargins')
net_margin = info.get('profitMargins')
fcf = info.get('freeCashflow')
debt_equity = info.get('debtToEquity')
roe = info.get('returnOnEquity')

def score_pe(pe):
    if pe is None: return 5
    if pe < 15: return 9
    if pe < 25: return 7
    if pe < 40: return 5
    return 3

valuation_score = score_pe(pe)
growth_score = min(10, int((revenue_growth or 0) * 50 + 5)) if revenue_growth else 5
health_score = 8 if (debt_equity or 100) < 50 else 5
overall_score = round((valuation_score + growth_score + health_score) / 3, 1)

result = {
    "ticker": ticker,
    "pe_trailing": pe,
    "pe_forward": forward_pe,
    "price_to_sales": ps,
    "price_to_book": pb,
    "ev_to_ebitda": ev_ebitda,
    "revenue_growth_yoy": revenue_growth,
    "gross_margin": gross_margin,
    "net_margin": net_margin,
    "free_cash_flow": fcf,
    "debt_to_equity": debt_equity,
    "return_on_equity": roe,
    "valuation_score": valuation_score,
    "growth_quality_score": growth_score,
    "financial_health_score": health_score,
    "overall_score": overall_score,
    "verdict": "attractive" if overall_score >= 7 else "fair" if overall_score >= 5 else "expensive",
}
"""

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id="committee",
            step_id="financial_analysis",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
