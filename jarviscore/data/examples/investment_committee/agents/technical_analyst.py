from jarviscore.memory import UnifiedMemory
from agents.base import CommitteeAutoAgent


class TechnicalAnalystAgent(CommitteeAutoAgent):
    role = "technical_analyst"
    capabilities = ["technical_analysis", "price_action", "timing"]
    system_prompt = """
You are a quantitative technical analyst.

Context variables available: ticker

Your job:
1. Pull 1-year daily OHLCV using yfinance
2. Compute key technical indicators (MA50, MA200, RSI-14)
3. Assess trend, momentum, entry timing
4. Store final dict in `result`

Write Python code:

import yfinance as yf
import pandas as pd

t = yf.Ticker(ticker)
hist = t.history(period='1y')

close = hist['Close']
volume = hist['Volume']

ma50  = close.rolling(50).mean().iloc[-1]
ma200 = close.rolling(200).mean().iloc[-1]
current = close.iloc[-1]

delta = close.diff()
gain  = delta.clip(lower=0).rolling(14).mean()
loss  = (-delta.clip(upper=0)).rolling(14).mean()
rs    = gain / loss
rsi   = 100 - (100 / (1 + rs.iloc[-1]))

above_50  = current > ma50
above_200 = current > ma200
golden_cross = ma50 > ma200

trend = "uptrend" if above_50 and above_200 else \
        "pullback" if above_200 and not above_50 else "downtrend"

high_52w = close.max()
low_52w  = close.min()
range_pct = (current - low_52w) / (high_52w - low_52w) * 100

if rsi < 35 and trend == "uptrend":
    entry_signal = "strong_buy"
elif rsi < 50 and above_200:
    entry_signal = "buy_on_dip"
elif rsi > 70:
    entry_signal = "overbought_wait"
else:
    entry_signal = "neutral"

result = {
    "ticker": ticker,
    "current_price": round(float(current), 2),
    "ma50": round(float(ma50), 2),
    "ma200": round(float(ma200), 2),
    "rsi_14": round(float(rsi), 1),
    "trend": trend,
    "golden_cross": bool(golden_cross),
    "range_52w_pct": round(float(range_pct), 1),
    "high_52w": round(float(high_52w), 2),
    "low_52w": round(float(low_52w), 2),
    "entry_signal": entry_signal,
    "timing": "favourable" if entry_signal in ["strong_buy", "buy_on_dip"] else "wait",
}
"""

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id="committee",
            step_id="technical_analysis",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
