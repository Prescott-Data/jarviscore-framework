"""
Example 1 — Financial Intelligence Pipeline
============================================
Profile  : AutoAgent
Mode     : Autonomous (single process, workflow engine only — no P2P)
Workflow : fetch → analyse → report  (sequential with depends_on)

Phases exercised
----------------
Phase 1  : LocalBlobStorage saves the final Markdown report
Phase 5  : Prometheus counters (set PROMETHEUS_ENABLED=true in .env)
Phase 7  : WorkflowEngine reactive dispatch; crash recovery via deterministic
           workflow_id="financial-daily-001" (re-run skips completed steps)
Phase 8  : UnifiedMemory (WorkingScratchpad + EpisodicLedger + LTM) initialised
           in each agent's setup() using Phase-9-injected stores
Phase 9  : Mesh.start() auto-injects self._redis_store, self._blob_storage,
           self.mailbox into every agent BEFORE setup() is called

Prerequisites
-------------
    docker compose -f docker-compose.infra.yml up -d   # Redis
    cp .env.example .env                               # then set CLAUDE_API_KEY
    pip install -e ".[redis,prometheus]"
    python examples/ex1_financial_pipeline.py

Verification
------------
    redis-cli keys "*financial-daily-001*"
    ls -la blob_storage/reports/
    curl -s http://localhost:9090/metrics | grep jarviscore   # if prometheus enabled
"""

import asyncio
import os
import sys
from pathlib import Path

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from jarviscore import Mesh
from jarviscore.profiles import AutoAgent
from jarviscore.memory import UnifiedMemory

# Deterministic workflow ID → crash recovery: re-run skips already-completed steps
WORKFLOW_ID = "financial-daily-001"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT DEFINITIONS
# Each agent overrides setup() to wire UnifiedMemory from Phase-9-injected stores.
# execute_task() is handled by AutoAgent (LLM code generation + sandbox execution).
# ═══════════════════════════════════════════════════════════════════════════════

class MarketDataAgent(AutoAgent):
    """
    Step 1 — Fetch synthetic market data.

    Generates realistic OHLCV prices and news sentiment for AAPL, MSFT, NVDA
    using Python's standard library only. Returns a dict stored in `result`.
    """
    role = "market_data"
    capabilities = ["market_data", "data_collection", "finance"]
    system_prompt = """
    You are a financial data specialist. Your job is to generate realistic synthetic
    market data for a set of technology tickers.

    Generate the following using ONLY Python standard library (random, datetime):

    result = {
        "date": "2026-02-18",
        "tickers": {
            "AAPL": {"close": float, "volume": int, "pct_change": float},
            "MSFT": {"close": float, "volume": int, "pct_change": float},
            "NVDA": {"close": float, "volume": int, "pct_change": float},
        },
        "news_sentiment": {
            "AAPL": float,   # -1.0 to 1.0
            "MSFT": float,
            "NVDA": float,
        },
        "market_index": {"SPY": float, "QQQ": float},
    }

    Use realistic price ranges: AAPL ~$180-220, MSFT ~$400-440, NVDA ~$800-950.
    Randomise pct_change in range [-3.0, 3.0].
    Store the dict in a variable named `result`.
    """

    async def setup(self):
        await super().setup()
        # Phase 9: self._redis_store and self._blob_storage are already injected here
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="fetch",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        tiers = []
        if self.memory.working:   tiers.append("scratchpad")
        if self.memory.episodic:  tiers.append("episodic")
        if self.memory.ltm:       tiers.append("ltm")
        self._logger.info(f"[{self.role}] UnifiedMemory active tiers: {tiers or ['none']}")


class AnalysisAgent(AutoAgent):
    """
    Step 2 — Compute technical signals from the fetched data.

    Reads the market data from context (injected by the workflow engine from
    the fetch step output) and computes RSI approximation, 5-day MA placeholder,
    and overbought/oversold classification.
    """
    role = "analyst"
    capabilities = ["analysis", "technical_analysis", "finance"]
    system_prompt = """
    You are a quantitative analyst. You receive market data from the previous step
    in your execution context as the variable `context` (a dict).

    Compute the following using ONLY Python standard library (no numpy/pandas):

    For each ticker in the context data:
    - Classify momentum as "overbought" (pct_change > 2.0), "oversold"
      (pct_change < -2.0), or "neutral"
    - Compute a simple signal score: news_sentiment * 0.4 + normalised_pct_change * 0.6
    - Flag tickers where abs(pct_change) > 2.5 as "alert"

    result = {
        "signals": {
            "AAPL": {"momentum": str, "score": float, "alert": bool},
            "MSFT": {"momentum": str, "score": float, "alert": bool},
            "NVDA": {"momentum": str, "score": float, "alert": bool},
        },
        "market_bias": "bullish" | "bearish" | "neutral",
        "alert_count": int,
        "date": str,
    }

    Store the result in a variable named `result`.
    If context is not available, generate plausible mock signals.
    """

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="analyse",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        self._logger.info(f"[{self.role}] memory initialised (redis={'yes' if self._redis_store else 'no'})")


class ReportAgent(AutoAgent):
    """
    Step 3 — Write an executive Markdown briefing.

    Reads both the market data and analysis signals from context and produces a
    structured Markdown report. The report text is returned as `result` and then
    saved to blob storage by main().
    """
    role = "reporter"
    capabilities = ["reporting", "writing", "finance"]
    system_prompt = """
    You are a financial communications specialist. You receive market data and
    analysis signals from the previous workflow steps in `context`.

    Write a concise executive Markdown briefing with these sections:

    # Daily Market Intelligence — {date}

    ## Market Overview
    (2-3 sentences on overall market bias)

    ## Ticker Signals
    | Ticker | Close | Δ% | Momentum | Score | Alert |
    |--------|-------|-----|----------|-------|-------|
    (one row per ticker)

    ## Key Alerts
    (list any tickers flagged as alert with brief note)

    ## Recommendation
    (1-2 sentences action summary)

    ---
    *Generated by JarvisCore Financial Intelligence Pipeline*

    Store the complete Markdown string in a variable named `result`.
    If context data is not available, use plausible placeholder values.
    """

    async def setup(self):
        await super().setup()
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="report",
            agent_id=self.role,
            redis_store=self._redis_store,
            blob_storage=self._blob_storage,
        )
        self._logger.info(f"[{self.role}] memory initialised (blob={'yes' if self._blob_storage else 'no'})")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "=" * 70)
    print("JarvisCore — Example 1: Financial Intelligence Pipeline")
    print("AutoAgent | Autonomous Mode | Phases 1, 5, 7, 8, 9")
    print("=" * 70)

    # ── Mesh setup ────────────────────────────────────────────────────────────
    # redis_url in config dict takes priority over REDIS_URL env var (Phase 9)
    # Prometheus is controlled by PROMETHEUS_ENABLED / PROMETHEUS_PORT in .env
    mesh = Mesh(
        mode="autonomous",
        config={
            "redis_url": REDIS_URL,
        },
    )

    market_agent = mesh.add(MarketDataAgent)
    analyst_agent = mesh.add(AnalysisAgent)
    report_agent  = mesh.add(ReportAgent)

    try:
        await mesh.start()

        # ── Phase 9 verification ──────────────────────────────────────────────
        print("\n[Phase 9] Infrastructure injection check:")
        print(f"  mesh._blob_storage  : {type(mesh._blob_storage).__name__}")
        print(f"  mesh._redis_store   : {'connected' if mesh._redis_store else 'None (set REDIS_URL)'}")
        for ag in [market_agent, analyst_agent, report_agent]:
            print(f"  {ag.role}.blob        : {'✓' if ag._blob_storage else '✗'}")
            print(f"  {ag.role}.redis       : {'✓' if ag._redis_store else '✗'}")

        # ── Workflow execution ────────────────────────────────────────────────
        print(f"\n[Workflow] Submitting '{WORKFLOW_ID}'...")
        print("  Steps: fetch → analyse → report  (sequential, depends_on)")
        print("  Crash recovery: re-run with same workflow_id skips completed steps\n")

        results = await mesh.workflow(WORKFLOW_ID, [
            {
                "id": "fetch",
                "agent": "market_data",
                "task": (
                    "Generate synthetic daily market data for AAPL, MSFT, NVDA "
                    "for 2026-02-18. Include closing price, volume, pct_change, "
                    "and news sentiment score (-1 to 1). Return as dict in `result`."
                ),
            },
            {
                "id": "analyse",
                "agent": "analyst",
                "task": (
                    "Analyse the market data from the fetch step. Compute momentum "
                    "classification, signal scores, and flag alerts for each ticker. "
                    "Return signals dict in `result`."
                ),
                "depends_on": ["fetch"],     # Phase 7: DependencyManager waits for fetch
            },
            {
                "id": "report",
                "agent": "reporter",
                "task": (
                    "Write an executive Markdown market briefing using the data and "
                    "signals from previous steps. Include ticker table and recommendations. "
                    "Return the full Markdown string in `result`."
                ),
                "depends_on": ["analyse"],   # Phase 7: waits for analyse
            },
        ])

        # ── Results summary ───────────────────────────────────────────────────
        print("\n" + "=" * 70)
        print("WORKFLOW RESULTS")
        print("=" * 70)

        step_names = ["fetch", "analyse", "report"]
        for name, result in zip(step_names, results):
            status = result.get("status", "unknown")
            icon = "✓" if status == "success" else "✗"
            print(f"\n{icon} Step: {name}  (status={status})")
            if status == "success":
                output = result.get("output", "")
                preview = str(output)[:300]
                print(f"  Output preview: {preview}{'...' if len(str(output)) > 300 else ''}")
            else:
                print(f"  Error: {result.get('error', 'unknown')}")

        # ── Phase 1: Save report to blob storage ─────────────────────────────
        report_result = results[2] if len(results) >= 3 else {}
        if report_result.get("status") == "success":
            report_text = str(report_result.get("output", ""))
            if mesh._blob_storage and report_text:
                blob_path = f"reports/{WORKFLOW_ID}.md"
                saved_path = await mesh._blob_storage.save(blob_path, report_text)
                print(f"\n[Phase 1] Report saved to blob: {saved_path}")
                print(f"          Full path: ./blob_storage/{blob_path}")

        # ── Phase 8: Log to episodic ledger ───────────────────────────────────
        if report_agent.memory and report_agent.memory.episodic:
            await report_agent.memory.episodic.append({
                "event": "pipeline_completed",
                "workflow_id": WORKFLOW_ID,
                "steps_completed": len([r for r in results if r.get("status") == "success"]),
            })
            print("[Phase 8] Pipeline completion logged to EpisodicLedger")

        # ── Redis verification ────────────────────────────────────────────────
        if mesh._redis_store:
            print(f"\n[Phase 7] Redis keys (workflow state):")
            for step_id in step_names:
                output = mesh._redis_store.get_step_output(WORKFLOW_ID, step_id)
                print(f"  step_output:{WORKFLOW_ID}:{step_id} → {'set ✓' if output else 'not found'}")

        # ── Summary ───────────────────────────────────────────────────────────
        successes = sum(1 for r in results if r.get("status") == "success")
        print(f"\n{'=' * 70}")
        print(f"Pipeline complete: {successes}/{len(results)} steps successful")
        print(f"Workflow ID: {WORKFLOW_ID}  (re-run to test crash recovery)")
        print(f"Blob report: ./blob_storage/reports/{WORKFLOW_ID}.md")
        if mesh._redis_store:
            print(f"Redis keys : redis-cli keys '*{WORKFLOW_ID}*'")
        print(f"{'=' * 70}\n")

    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        import traceback
        traceback.print_exc()

    finally:
        await mesh.stop()


if __name__ == "__main__":
    asyncio.run(main())
