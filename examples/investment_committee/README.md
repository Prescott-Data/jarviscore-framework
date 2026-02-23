# Investment Committee — Multi-Agent System

A 7-agent investment committee built on **JarvisCore v0.4.0** that evaluates public-equity
opportunities and produces auditable allocation decisions for a $10M portfolio.
Each run produces a formal markdown memo. Institutional memory (LTM) compounds across runs.

---

## Quick Start

```bash
# Prerequisites: Redis running, .env configured with LLM API key
source venv/bin/activate

# Single analyst, fast check
python committee.py --mode quick --ticker AAPL

# Full 7-agent committee
python committee.py --mode full --ticker NVDA --amount 1500000

# Repeat ticker — KnowledgeAgent will find prior memos
python committee.py --mode full --ticker NVDA --amount 1500000

# Sector cap stress test
python committee.py --mode full --ticker AMD --amount 2000000
```

---

## Project Structure

```
investment_committee/
├── PLAN.md                    # Original implementation plan
├── README.md                  # This file
├── committee.py               # Entry point — Mesh setup + workflow runner
├── portfolio.json             # $10M mandate, holdings, sector exposure
├── requirements.txt
├── .env                       # LLM API key + REDIS_URL
├── venv/                      # Python 3.12 virtualenv
├── data/
│   └── memos/                 # Memo archive (YYYYMMDD_HHMM_{TICKER}_{ACTION}.md)
└── agents/
    ├── base.py                # CommitteeAutoAgent — shared base for all AutoAgents
    ├── __init__.py
    ├── market_analyst.py      # AutoAgent
    ├── financial_analyst.py   # AutoAgent
    ├── technical_analyst.py   # AutoAgent
    ├── risk_officer.py        # AutoAgent
    ├── knowledge_agent.py     # CustomAgent
    ├── memo_writer.py         # AutoAgent
    └── committee_chair.py     # CustomAgent
```

---

## Workflow DAG

```
Step 1 — Parallel (no dependencies):
  ├── market_analysis      → MarketAnalystAgent
  ├── financial_analysis   → FinancialAnalystAgent
  ├── technical_analysis   → TechnicalAnalystAgent
  └── knowledge_retrieval  → KnowledgeAgent

Step 2 — depends on market_analysis + financial_analysis:
  └── risk_assessment      → RiskOfficerAgent

Step 3 — depends on all 5 above:
  └── memo_draft           → MemoWriterAgent

Step 4 — depends on memo_draft:
  └── final_decision       → CommitteeChairAgent
```

The engine executes independent steps in parallel (Steps 1), then gates the
remaining steps on their declared dependencies.

---

## Agents

### 1. MarketAnalystAgent — `agents/market_analyst.py`
**Profile:** `CommitteeAutoAgent` (AutoAgent subclass)
**Capabilities:** `market_analysis`, `macro`, `news`, `sector`

Pulls 1-year daily OHLCV from yfinance, extracts sector/industry/market-cap from `.info`.
Computes YTD return, average daily volume, 52-week range. Derives a `macro_signal`
(overweight/neutral/underweight) and `analyst_rating` (bullish/neutral/bearish) from price
performance. Includes a `news_summary` field from the ticker's info block.

**Output keys:** `ticker`, `current_price`, `ytd_return_pct`, `avg_daily_volume`,
`sector`, `industry`, `market_cap`, `macro_signal`, `key_catalysts`, `risk_factors`,
`news_summary`, `analyst_rating`, `confidence`

---

### 2. FinancialAnalystAgent — `agents/financial_analyst.py`
**Profile:** `CommitteeAutoAgent`
**Capabilities:** `financial_analysis`, `fundamentals`, `valuation`

Fetches fundamental data from `yfinance.Ticker.info`. Scores the stock on three
dimensions (valuation 1–10, growth quality 1–10, financial health 1–10) using simple
rule-based heuristics, then averages to an `overall_score`. This score drives the
final committee decision.

**Scoring rules:**
- `valuation_score`: PE < 15 → 9, PE < 25 → 7, PE < 40 → 5, else 3
- `growth_quality_score`: `revenue_growth * 50 + 5`, capped at 10
- `financial_health_score`: debt/equity < 50 → 8, else 5

**Output keys:** `pe_trailing`, `pe_forward`, `price_to_sales`, `price_to_book`,
`ev_to_ebitda`, `revenue_growth_yoy`, `gross_margin`, `net_margin`, `free_cash_flow`,
`debt_to_equity`, `return_on_equity`, `valuation_score`, `growth_quality_score`,
`financial_health_score`, `overall_score`, `verdict`

---

### 3. TechnicalAnalystAgent — `agents/technical_analyst.py`
**Profile:** `CommitteeAutoAgent`
**Capabilities:** `technical_analysis`, `price_action`, `timing`

Computes MA50, MA200, RSI-14, golden-cross signal, and 52-week range percentile from
1-year daily close data. Derives `entry_signal` from RSI × trend logic:

| Condition | Signal |
|---|---|
| RSI < 35 and in uptrend | `strong_buy` |
| RSI < 50 and above MA200 | `buy_on_dip` |
| RSI > 70 | `overbought_wait` |
| Otherwise | `neutral` |

**Output keys:** `current_price`, `ma50`, `ma200`, `rsi_14`, `trend`,
`golden_cross`, `range_52w_pct`, `high_52w`, `low_52w`, `entry_signal`, `timing`

---

### 4. RiskOfficerAgent — `agents/risk_officer.py`
**Profile:** `CommitteeAutoAgent`
**Capabilities:** `risk_analysis`, `mandate_compliance`, `position_sizing`

Reads `previous_step_results.market_analysis.output.sector` to determine ticker sector.
Computes historical VaR at 95% confidence (1-day, dollar amount) using 1-year daily
returns. Checks three mandate rules against `portfolio.json` constraints:

| Check | Rule |
|---|---|
| Position size | `amount <= max_position_usd` ($3M cap) |
| Sector cap | `current_sector_pct + amount/AUM <= 40%` |
| Liquidity | `avg_daily_volume_usd >= $1M` |

If any check fails, `recommended_amount` is reduced (not blocked outright, unless
no capital can fit). Assigns `risk_rating` LOW/MEDIUM/HIGH from VaR as % of position.

**Depends on:** `market_analysis`, `financial_analysis`

**Output keys:** `requested_amount`, `recommended_amount`, `var_95_1day_usd`,
`avg_daily_volume_usd`, `ticker_sector`, `sector_exposure_after`,
`mandate_checks`, `mandate_pass`, `risk_rating`, `notes`

---

### 5. KnowledgeAgent — `agents/knowledge_agent.py`
**Profile:** `CustomAgent` (no LLM, deterministic code)
**Capabilities:** `knowledge_retrieval`, `research_library`, `memo_archive`

Scans `data/memos/` for `*{TICKER}*.md` files (up to 3 most recent). Extracts a
decision line from each memo by searching for `**Action:**`, `BUY`, `HOLD`, or `PASS`.
Also loads the LTM summary from Redis/blob on `setup()` — this is the institutional
memory that accumulates across all runs.

**Output keys:** `prior_memos_found`, `precedents` (list of file+decision+excerpt),
`institutional_learnings` (LTM summary string), `research_summary`

---

### 6. MemoWriterAgent — `agents/memo_writer.py`
**Profile:** `CommitteeAutoAgent`
**Capabilities:** `memo_writing`, `synthesis`, `reporting`

Reads all five upstream step outputs from `previous_step_results` and synthesises them
into a structured markdown memo and a machine-readable `scores` dict. The `scores`
dict is critical — it is the data source the CommitteeChairAgent reads, because the
Chair only has `memo_draft` in its dependency chain.

**Memo sections:** Executive Summary, Market Analysis, Fundamental Analysis,
Technical Analysis, Risk Assessment, Prior Research, Institutional Learnings

**Output keys:** `memo_markdown`, `scores` (market/fundamental/technical/risk_rating),
`recommended_amount`, `mandate_pass`

**Depends on:** all 5 previous steps

---

### 7. CommitteeChairAgent — `agents/committee_chair.py`
**Profile:** `CustomAgent` (deterministic decision logic)
**Capabilities:** `decision_making`, `orchestration`, `allocation`

Applies a three-tier decision rule using data from `memo.scores`:

| Condition | Action | Allocation |
|---|---|---|
| `fin_score >= 7` AND tech bullish AND risk LOW/MEDIUM AND mandate pass | `BUY` | `recommended_amount` |
| `fin_score >= 5` AND mandate pass | `HOLD` | `recommended_amount × 50%` |
| Otherwise | `PASS` | `$0` |

Appends a `## Committee Decision` block to the memo markdown and writes the full
document to `data/memos/YYYYMMDD_HHMM_{TICKER}_{ACTION}.md`. Saves a one-line
learning to LTM via `self.memory.ltm.save_summary()`.

**Depends on:** `memo_draft`

---

## Framework Components Used

### Mesh (`jarviscore.Mesh`)
Autonomous-mode orchestrator. Registered agents are looked up by `role` string when
a step specifies `"agent": "market_analyst"` etc. `mesh.add(AgentClass)` registers
the class; `mesh.start()` calls each agent's `setup()` coroutine; `mesh.workflow()`
delegates to the `WorkflowEngine`.

```python
mesh = Mesh(mode="autonomous", config={"redis_url": REDIS_URL})
mesh.add(MarketAnalystAgent)
await mesh.start()
results = await mesh.workflow(wf_id, steps)
```

### WorkflowEngine (`jarviscore.orchestration.engine`)
Reactive dependency-aware step scheduler. Runs a loop: find all steps whose
`depends_on` are satisfied → launch them in parallel as `asyncio.Task` → wait for
any completion → record result in `self.memory[step_id]` → repeat.

Builds `dep_outputs = {dep_id: self.memory[dep_id] for dep_id in step.depends_on}`
and injects it into `task["context"]["previous_step_results"]`.

Persists step state to Redis (`step_output:*`, `workflow_state:*`, `workflow_graph:*`)
for crash recovery.

### AutoAgent (`jarviscore.profiles.AutoAgent`)
LLM-driven code-generation profile. Given a task description and system prompt, it:
1. Calls `codegen.generate()` → produces Python code
2. Runs code in `sandbox.execute()` → captures `result` variable (or return value of `async def main()`)
3. On failure, calls `repair.repair_with_retries()` (up to 3 attempts)
4. Registers successful code in the `FunctionRegistry` for reuse

The sandbox injects `task["context"]` keys as namespace variables, so
`previous_step_results`, `ticker`, `amount` etc. are available directly in
generated code.

### CustomAgent (`jarviscore.profiles.CustomAgent`)
Deterministic Python profile. No LLM, no sandbox. Implements `execute_task(task)`
directly. Used for agents with rule-based logic (KnowledgeAgent, CommitteeChair)
where predictability matters more than flexibility.

### UnifiedMemory (`jarviscore.memory.UnifiedMemory`)
Three-tier memory system composed per-agent:

| Tier | Backend | Purpose |
|---|---|---|
| `working` (WorkingScratchpad) | Blob (JSONL file) | Per-step reasoning notes |
| `episodic` (EpisodicLedger) | Redis Stream | Chronological event log |
| `ltm` (LongTermMemory) | Redis + Blob (dual-write) | Compressed cross-run summaries |

```python
self.memory = UnifiedMemory(
    workflow_id="committee",
    step_id="knowledge_retrieval",
    agent_id=self.role,
    redis_store=self._redis_store,
    blob_storage=self._blob_storage,
)
```

---

## Why Blob Storage Only Has Summary

This is an intentional architectural choice, not a limitation.

The three memory tiers have distinct responsibilities:

**Episodic Ledger** (Redis Stream `ledgers:{workflow_id}`) owns the raw
chronological record — every append is an atomic XADD. It preserves full event
history and is the source of truth.

**LTM** is a *compression* layer, not a *storage* layer. Its job is to distil
the episodic ledger into a bounded-size semantic digest that can fit in an LLM
prompt without blowing the context window. Full structured data would defeat
this purpose — a 50-run workflow's ledger could have thousands of entries; a
summary is always ~200 tokens.

Blob storage in LTM holds `workflows/{wf_id}/ltm/summary.txt` — the durable
cold-cache copy of the Redis LTM string. Redis has a 7-day TTL; blob has no
expiry. When Redis misses, LTM reads from blob and rehydrates Redis. This
dual-write pattern means the summary survives Redis restarts, TTL expiry, and
cluster failures.

**Full structured data lives elsewhere:**
- Per-step outputs → `step_output:*` Redis hashes (workflow engine)
- Working notes → `workflows/{wf_id}/scratchpads/` blob files
- Commit history → `data/memos/` (our own archive, outside the framework)

---

## Issues Encountered & Fixes

### Issue 1 — `mesh.workflow()` does not accept `context=` keyword argument

**Symptom:** `TypeError: Mesh.workflow() got an unexpected keyword argument 'context'`

**Root cause:** `mesh.workflow(workflow_id, steps)` only accepts two positional
arguments. There is no mechanism to pass workflow-level variables (ticker, amount,
mandate, portfolio) through the public API.

**What we tried first:** Passing `context=context` directly — rejected at runtime.

**Fix:** Each step definition is built dynamically with a `"params"` key containing
the workflow-level variables:
```python
params = {"ticker": ticker, "amount": amount, "mandate": ..., "portfolio": ...}
steps = [{**s, "params": params} for s in base_steps]
```
The `WorkflowEngine` preserves all step keys in `task = step.copy()`, so `params`
survives and is readable inside each agent's `execute_task`. A shared base class
(`CommitteeAutoAgent`) merges `task["params"]` into `task["context"]` before the
sandbox runs, making `ticker`, `amount` etc. available as direct variables in
LLM-generated code.

---

### Issue 2 — `mesh.workflow()` returns a list, not a dict

**Symptom:** `AttributeError: 'list' object has no attribute 'get'`

**Root cause:** The engine returns results in step-definition order as a Python list.
The plan assumed a dict keyed by step ID.

**Fix:** `_index_results(results, steps)` matches each result to its step ID using
position index as fallback (successful results have no `step_id` field — only
failures do):
```python
def _index_results(results, steps) -> dict:
    for i, r in enumerate(results):
        sid = r.get("step_id") or (steps[i].get("id") if i < len(steps) else None)
        if sid:
            by_id[sid] = r
```

---

### Issue 3 — `numpy.bool_` not JSON-serializable, crashes Redis save

**Symptom:** `TypeError: Object of type bool is not JSON serializable` inside
`redis_store.save_step_output()` when saving TechnicalAnalyst or MarketAnalyst results.

**Root cause:** pandas/numpy boolean comparisons (`current > ma50`, `ma50 > ma200`)
return `numpy.bool_` objects. The class name in CPython is `'bool'`, but the standard
`json` encoder does not recognise it as a Python `bool`. The framework calls
`json.dumps(output)` with no custom encoder.

**Fix:** `CommitteeAutoAgent.execute_task()` sanitises the output dict after the
sandbox returns, recursively converting all numpy scalar types to Python natives:
```python
def _to_python(obj):
    if isinstance(obj, np.bool_):   return bool(obj)
    if isinstance(obj, np.integer): return int(obj)
    if isinstance(obj, np.floating): return float(obj)
    if isinstance(obj, np.ndarray): return obj.tolist()
    if isinstance(obj, dict):  return {k: _to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):  return [_to_python(v) for v in obj]
    return obj
```

---

### Issue 4 — CommitteeChair cannot see individual step results

**Symptom:** Chair produced PASS with `fin_score=5, mandate=fail` even when memo
showed score 7.0 and mandate PASS.

**Root cause:** `final_decision` only declares `depends_on: ["memo_draft"]`.
The engine therefore only puts `memo_draft` in `task["context"]["previous_step_results"]`.
The Chair was trying to read `risk_assessment`, `financial_analysis`, `technical_analysis`
directly from `previous_step_results` — those keys didn't exist, so it got empty
dicts and fell through to defaults.

**Fix:** The `MemoWriterAgent` already aggregates all analysis into a `scores` dict
in its output. The Chair now reads from that pre-aggregated structure:
```python
memo_entry = prev.get("memo_draft") or {}
memo  = memo_entry.get("output") or {}
scores = memo.get("scores") or {}

fin_score   = scores.get("fundamental") or 5
tech_signal = scores.get("technical") or "neutral"
risk_rating = scores.get("risk_rating") or "HIGH"
mandate_ok  = memo.get("mandate_pass", False)
```
This eliminates the need to add all steps to `depends_on` (which would be redundant
since memo_writer already read them all).

---

### Issue 5 — `task["context"]` overwritten by the engine, params not reaching sandbox

**Symptom:** Variables like `ticker` and `amount` were `NameError` in LLM-generated
code despite being passed as workflow context.

**Root cause:** The `WorkflowEngine._execute_step()` always sets:
```python
task["context"] = {
    "previous_step_results": dep_outputs,
    "workflow_id": workflow_id,
    "step_id": step_id,
}
```
This overwrites any `"context"` key already in the step dict. Only these three
variables reach the sandbox namespace.

**Fix:** Same as Issue 1 — inject via `step["params"]` and merge in the base class:
```python
class CommitteeAutoAgent(AutoAgent):
    async def execute_task(self, task):
        ctx = task.setdefault("context", {})
        ctx.update(task.get("params", {}))          # merge params → context
        result = await super().execute_task(task)   # sandbox now sees ticker, amount, etc.
        if isinstance(result.get("output"), dict):
            result["output"] = _to_python(result["output"])
        return result
```

---

## Decision Logic

```
fin_score >= 7  AND  tech ∈ {strong_buy, buy_on_dip}  AND
risk ∈ {LOW, MEDIUM}  AND  mandate_pass == True
    → BUY   @ recommended_amount

fin_score >= 5  AND  mandate_pass == True
    → HOLD  @ recommended_amount × 50%

Otherwise
    → PASS  @ $0
```

---

## LTM & Institutional Memory

The `KnowledgeAgent` loads a cross-run LTM summary at `setup()` time:
```python
prior = await self.memory.ltm.load_summary()
```

The `CommitteeChairAgent` writes a one-line learning after each decision:
```python
await self.memory.ltm.save_summary(
    f"2026-02-19: NVDA → HOLD ($750,000, conviction=MEDIUM, fin_score=7.0)"
)
```

LTM uses a dual-write strategy:
- **Redis** (`ltm:committee`, 7-day TTL) — fast hot path
- **Blob** (`workflows/committee/ltm/summary.txt`) — durable cold path, survives TTL

On the second run for the same ticker, the KnowledgeAgent will include both:
1. Prior memos scanned from `data/memos/` (file-system archive)
2. Institutional learnings from LTM (compressed decision history)

---

## Redis Keys Created Per Run

| Key Pattern | Type | Content |
|---|---|---|
| `workflow_graph:{wf_id}` | Hash | Step definitions + status |
| `workflow_state:{wf_id}` | String | Full workflow state (crash recovery) |
| `step_output:{wf_id}:{step_id}` | Hash | Step result metadata |
| `ledgers:committee` | Stream | Episodic event log (KnowledgeAgent) |
| `ltm:committee` | String | LTM summary (Chair → LTM) |

---

## Environment

```bash
# .env keys needed
ANTHROPIC_API_KEY=sk-ant-...   # or AZURE_API_KEY / GEMINI_API_KEY
REDIS_URL=redis://localhost:6379/0

# Start Redis
docker compose -f /home/mutua/Documents/P2P/jarviscore/docker-compose.infra.yml up -d redis

# Verify setup
venv/bin/python -c "from jarviscore import Mesh; import yfinance; print('OK')"
```

---

*JarvisCore Investment Committee — v0.4.0 | Built 2026-02-19*
