from jarviscore.memory import UnifiedMemory
from agents.base import CommitteeAutoAgent


class RiskOfficerAgent(CommitteeAutoAgent):
    role = "risk_officer"
    capabilities = ["risk_analysis", "mandate_compliance", "position_sizing"]
    system_prompt = """
You are the Risk Officer and Mandate Compliance guardian.

Context variables available: ticker, amount, mandate, portfolio, previous_step_results

Your job:
1. Check if the proposed position passes mandate rules
2. Compute simple historical VaR (95%, 1-day)
3. Check sector concentration after adding the position
4. Recommend final position size (may reduce from requested amount)
5. Store final dict in `result`

Write Python code:

import yfinance as yf
import numpy as np

t = yf.Ticker(ticker)
hist = t.history(period='1y')
returns = hist['Close'].pct_change().dropna()

var_95 = float(np.percentile(returns, 5)) * amount
avg_daily_vol = hist['Volume'].mean() * hist['Close'].iloc[-1]

max_pos_usd = mandate['max_position_usd']
sector_cap = mandate['sector_cap_pct']
min_volume = mandate['min_daily_volume_usd']

market_result = previous_step_results.get('market_analysis', {}).get('output', {})
ticker_sector = market_result.get('sector', 'Unknown')

portfolio_data = portfolio if isinstance(portfolio, dict) else {}
sector_exposure = portfolio_data.get('sector_exposure', {})
aum = portfolio_data.get('total_aum', 10_000_000)
current_sector_pct = sector_exposure.get(ticker_sector, 0)
new_sector_pct = current_sector_pct + (amount / aum)

passes_size   = amount <= max_pos_usd
passes_sector = new_sector_pct <= sector_cap
passes_liquid = avg_daily_vol >= min_volume

recommended = amount
if not passes_size:
    recommended = max_pos_usd
if not passes_sector:
    slack = max(0, (sector_cap - current_sector_pct) * aum)
    recommended = min(recommended, slack)

overall_pass = passes_size and passes_sector and passes_liquid

notes = []
if not passes_size:
    notes.append(f"Size reduced from ${amount:,.0f} to ${recommended:,.0f} (max position cap)")
if not passes_sector:
    notes.append(f"Sector {ticker_sector} at {new_sector_pct*100:.1f}% exceeds cap of {sector_cap*100:.0f}%")
if not passes_liquid:
    notes.append(f"Avg daily volume ${avg_daily_vol:,.0f} below minimum ${min_volume:,.0f}")

result = {
    "ticker": ticker,
    "requested_amount": amount,
    "recommended_amount": round(recommended, -3),
    "var_95_1day_usd": round(var_95, 0),
    "avg_daily_volume_usd": round(avg_daily_vol, 0),
    "ticker_sector": ticker_sector,
    "sector_exposure_after": round(new_sector_pct * 100, 1),
    "mandate_checks": {
        "position_size": passes_size,
        "sector_cap": passes_sector,
        "liquidity": passes_liquid,
    },
    "mandate_pass": overall_pass,
    "risk_rating": "LOW" if abs(var_95) < amount * 0.02 else
                   "MEDIUM" if abs(var_95) < amount * 0.04 else "HIGH",
    "notes": notes,
}
"""

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id="committee",
            step_id="risk_assessment",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
