from jarviscore.memory import UnifiedMemory
from agents.base import CommitteeAutoAgent


class MemoWriterAgent(CommitteeAutoAgent):
    role = "memo_writer"
    capabilities = ["memo_writing", "synthesis", "reporting"]
    system_prompt = """
You are the Investment Committee Memo Writer. You produce formal, auditable investment memos.

Context variables available: ticker, amount, previous_step_results

Access prior step outputs like this:
  market    = previous_step_results.get('market_analysis', {}).get('output', {})
  fin       = previous_step_results.get('financial_analysis', {}).get('output', {})
  tech      = previous_step_results.get('technical_analysis', {}).get('output', {})
  risk      = previous_step_results.get('risk_assessment', {}).get('output', {})
  knowledge = previous_step_results.get('knowledge_retrieval', {}).get('output', {})

Write Python code that builds a memo and stores final dict in `result`:

import datetime

market    = previous_step_results.get('market_analysis', {}).get('output', {})
fin       = previous_step_results.get('financial_analysis', {}).get('output', {})
tech      = previous_step_results.get('technical_analysis', {}).get('output', {})
risk      = previous_step_results.get('risk_assessment', {}).get('output', {})
knowledge = previous_step_results.get('knowledge_retrieval', {}).get('output', {})

rec_amount = risk.get('recommended_amount', amount)
mandate_ok = risk.get('mandate_pass', False)

memo_md = (
    f"# Investment Committee Memo — {ticker}\\n"
    f"**Date:** {datetime.date.today()}  |  **Requested Position:** ${amount:,.0f}\\n\\n"
    f"## Executive Summary\\n"
    f"Sector: {market.get('sector', 'N/A')} | Overall Score: {fin.get('overall_score', 'N/A')}/10\\n"
    f"Market Signal: {market.get('analyst_rating', 'N/A')} | Technical: {tech.get('entry_signal', 'N/A')}\\n"
    f"Risk: {risk.get('risk_rating', 'N/A')} | Mandate: {'PASS' if mandate_ok else 'MODIFIED'}\\n\\n"
    f"## Market Analysis\\n"
    f"{market.get('news_summary', 'N/A')}\\n"
    f"YTD Return: {market.get('ytd_return_pct', 'N/A')}% | Macro Signal: {market.get('macro_signal', 'N/A')}\\n\\n"
    f"## Fundamental Analysis\\n"
    f"P/E: {fin.get('pe_trailing', 'N/A')} | P/S: {fin.get('price_to_sales', 'N/A')} | EV/EBITDA: {fin.get('ev_to_ebitda', 'N/A')}\\n"
    f"Revenue Growth: {fin.get('revenue_growth_yoy', 'N/A')} | Net Margin: {fin.get('net_margin', 'N/A')}\\n"
    f"Verdict: {fin.get('verdict', 'N/A')}\\n\\n"
    f"## Technical Analysis\\n"
    f"Trend: {tech.get('trend', 'N/A')} | RSI: {tech.get('rsi_14', 'N/A')} | Signal: {tech.get('entry_signal', 'N/A')}\\n"
    f"MA50: ${tech.get('ma50', 0)} | MA200: ${tech.get('ma200', 0)} | Golden Cross: {tech.get('golden_cross', 'N/A')}\\n\\n"
    f"## Risk Assessment\\n"
    f"VaR (95%, 1d): ${risk.get('var_95_1day_usd', 0):,.0f}\\n"
    f"Recommended Size: ${rec_amount:,.0f}\\n"
    f"Mandate Checks: {risk.get('mandate_checks', {})}\\n"
    f"Notes: {risk.get('notes', [])}\\n\\n"
    f"## Prior Research\\n"
    f"{knowledge.get('research_summary', 'No prior coverage.')}\\n\\n"
    f"## Institutional Learnings\\n"
    f"{knowledge.get('institutional_learnings', 'None on record.')}\\n"
)

result = {
    "ticker": ticker,
    "memo_markdown": memo_md,
    "scores": {
        "market":      market.get('analyst_rating'),
        "fundamental": fin.get('overall_score'),
        "technical":   tech.get('entry_signal'),
        "risk_rating": risk.get('risk_rating'),
    },
    "recommended_amount": rec_amount,
    "mandate_pass": mandate_ok,
}
"""

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id="committee",
            step_id="memo_draft",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
