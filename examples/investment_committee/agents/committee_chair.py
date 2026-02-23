import os
import time

from jarviscore.profiles import CustomAgent
from jarviscore.memory import UnifiedMemory

MEMO_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "memos")


class CommitteeChairAgent(CustomAgent):
    role = "committee_chair"
    capabilities = ["decision_making", "orchestration", "allocation"]

    async def setup(self):
        await super().setup()
        os.makedirs(MEMO_DIR, exist_ok=True)
        self.memory = UnifiedMemory(
            workflow_id="committee",
            step_id="final_decision",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )

    async def execute_task(self, task):
        ctx = task.get("context", {})
        params = task.get("params", {})
        ticker = ctx.get("ticker") or params.get("ticker", "UNKNOWN")
        amount = ctx.get("amount") or params.get("amount", 0)
        prev = ctx.get("previous_step_results", {})

        # final_decision only depends_on memo_draft, so prev only has memo_draft.
        # The MemoWriter aggregates all scores — read from there.
        memo_entry = prev.get("memo_draft") or {}
        memo = memo_entry.get("output") or {}
        scores = memo.get("scores") or {}

        fin_score   = scores.get("fundamental") or 5
        tech_signal = scores.get("technical") or "neutral"
        risk_rating = scores.get("risk_rating") or "HIGH"
        mandate_ok  = memo.get("mandate_pass", False)
        rec_amount  = memo.get("recommended_amount", 0)

        bullish_tech = tech_signal in ["strong_buy", "buy_on_dip"]
        low_risk     = risk_rating in ["LOW", "MEDIUM"]

        if fin_score >= 7 and bullish_tech and low_risk and mandate_ok:
            action = "BUY"
            allocation = rec_amount
            conviction = "HIGH"
        elif fin_score >= 5 and mandate_ok:
            action = "HOLD"
            allocation = rec_amount * 0.5
            conviction = "MEDIUM"
        else:
            action = "PASS"
            allocation = 0
            conviction = "LOW"

        decision = {
            "ticker": ticker,
            "action": action,
            "allocation_usd": allocation,
            "conviction": conviction,
            "rationale": (
                f"Fundamental score {fin_score}/10, technical '{tech_signal}', "
                f"risk {risk_rating}, mandate {'pass' if mandate_ok else 'fail'}."
            ),
            "conditions": (
                [] if action == "BUY" else
                ["Re-evaluate if fundamental score improves to >=7"] if action == "HOLD" else
                ["Position does not meet mandate or quality threshold"]
            ),
            "timestamp": time.strftime("%Y-%m-%d %H:%M UTC"),
        }

        # Append decision block to memo and write to disk
        memo_md = memo.get("memo_markdown", f"# Investment Committee Memo — {ticker}\n")
        decision_block = (
            f"\n## Committee Decision\n"
            f"**Action:** {action}  |  **Allocation:** ${allocation:,.0f}  |  **Conviction:** {conviction}\n"
            f"**Rationale:** {decision['rationale']}\n"
            f"**Conditions:** {decision['conditions']}\n"
            f"**Timestamp:** {decision['timestamp']}\n"
        )
        full_memo = memo_md + decision_block
        filename = f"{time.strftime('%Y%m%d_%H%M')}_{ticker}_{action}.md"
        memo_path = os.path.join(MEMO_DIR, filename)
        with open(memo_path, "w") as f:
            f.write(full_memo)
        self._logger.info(f"[Chair] Memo written → data/memos/{filename}")

        # Save learning to LTM
        if self.memory.ltm:
            learning = (
                f"{time.strftime('%Y-%m-%d')}: {ticker} → {action} "
                f"(${allocation:,.0f}, conviction={conviction}, fin_score={fin_score})"
            )
            await self.memory.ltm.save_summary(learning)
            self._logger.info(f"[Chair] Learning saved to LTM")

        return {"status": "success", "output": decision}
