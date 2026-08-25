from jarviscore.memory import UnifiedMemory
from agents.base import CommitteeAutoAgent


class MarketAnalystAgent(CommitteeAutoAgent):
    role = "market_analyst"
    capabilities = ["market_analysis", "macro", "news", "sector"]
    system_prompt = """
You are a senior buy-side market analyst covering macro and sector dynamics.

Context variables available: ticker, mandate, portfolio

Your job:
1. Pull 1-year daily price + volume for the ticker using yfinance
2. Search for recent macro news and sector developments
3. Identify key catalysts (positive and negative)
4. Assess sector rotation signal (overweight/underweight/neutral)

Write Python code and store the final dict in `result`:

import yfinance as yf

t = yf.Ticker(ticker)
hist = t.history(period='1y')
info = t.info

current_price = hist['Close'].iloc[-1]
ytd_return = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
avg_volume = hist['Volume'].mean()

result = {
    "ticker": ticker,
    "current_price": round(float(current_price), 2),
    "ytd_return_pct": round(float(ytd_return), 2),
    "avg_daily_volume": int(avg_volume),
    "sector": info.get("sector", "Unknown"),
    "industry": info.get("industry", "Unknown"),
    "market_cap": info.get("marketCap", 0),
    "macro_signal": "neutral",
    "key_catalysts": [
        f"52-week range: ${hist['Close'].min():.2f} - ${hist['Close'].max():.2f}",
        f"Current price vs 52w high: {((current_price / hist['Close'].max()) - 1) * 100:.1f}%",
    ],
    "risk_factors": [
        f"Avg daily volume: {int(avg_volume):,} shares",
    ],
    "news_summary": f"{ticker} in {info.get('sector', 'Unknown')} sector. Market cap: ${info.get('marketCap', 0)/1e9:.1f}B.",
    "analyst_rating": "bullish" if ytd_return > 10 else "bearish" if ytd_return < -10 else "neutral",
    "confidence": 0.75,
}
"""

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id="committee",
            step_id="market_analysis",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
