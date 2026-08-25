import glob
import os
import time

from jarviscore.profiles import CustomAgent
from jarviscore.memory import UnifiedMemory

MEMO_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "memos")


class KnowledgeAgent(CustomAgent):
    role = "knowledge_agent"
    capabilities = ["knowledge_retrieval", "research_library", "memo_archive"]

    async def setup(self):
        await super().setup()
        os.makedirs(MEMO_DIR, exist_ok=True)
        self.memory = UnifiedMemory(
            workflow_id="committee",
            step_id="knowledge_retrieval",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        self._learnings = ""
        if self.memory.ltm:
            prior = await self.memory.ltm.load_summary()
            if prior:
                self._learnings = prior
                self._logger.info(f"[{self.role}] Loaded institutional learnings from LTM")

    async def execute_task(self, task):
        ctx = task.get("context", {})
        params = task.get("params", {})
        ticker = ctx.get("ticker") or params.get("ticker", "")

        prior_memos = []
        pattern = os.path.join(MEMO_DIR, f"*{ticker}*.md")
        for path in sorted(glob.glob(pattern), reverse=True)[:3]:
            with open(path) as f:
                prior_memos.append({"file": os.path.basename(path), "content": f.read()})

        precedents = []
        for memo in prior_memos:
            lines = memo["content"].split("\n")
            decision_line = next(
                (l for l in lines if "Decision:" in l or "**Action:**" in l or "BUY" in l or "HOLD" in l or "PASS" in l),
                ""
            )
            precedents.append({
                "file": memo["file"],
                "decision": decision_line.strip(),
                "excerpt": "\n".join(lines[:10]),
            })

        result = {
            "ticker": ticker,
            "prior_memos_found": len(prior_memos),
            "precedents": precedents,
            "institutional_learnings": self._learnings,
            "research_summary": (
                f"Found {len(prior_memos)} prior memo(s) for {ticker}. "
                + (f"Most recent decision: {precedents[0]['decision']}" if precedents else "No prior coverage.")
            ),
        }

        if self.memory.episodic:
            await self.memory.episodic.append({
                "event": "knowledge_retrieved",
                "ticker": ticker,
                "memos_found": len(prior_memos),
                "ts": time.time(),
            })

        return {"status": "success", "output": result}
