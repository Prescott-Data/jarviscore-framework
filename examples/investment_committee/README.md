# Investment Committee — Multi-Agent System

A 7-agent investment committee built on **JarvisCore v0.4.0** that evaluates public-equity
opportunities and produces auditable allocation decisions for a $10M portfolio.
Each run produces a formal markdown memo. Institutional memory (LTM) compounds across runs.

---

## How It Works

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

The engine executes independent steps in parallel, then gates each subsequent
step on its declared dependencies. The final output is a markdown investment memo
written to `data/memos/YYYYMMDD_HHMM_{TICKER}_{ACTION}.md`.

---

## Running Without the Dashboard (CLI)

This is the core example. No dashboard needed — results are written to `data/memos/`.

### Prerequisites

- Python 3.10+
- Redis running on `localhost:6379`
- `ANTHROPIC_API_KEY` (or another supported LLM provider key)

### Setup

```bash
# From the investment_committee directory
pip install -r requirements.txt

# Copy and fill in your keys
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY and REDIS_URL
```

### Run

```bash
# Single analyst, fast check
python committee.py --mode quick --ticker AAPL

# Full 7-agent committee
python committee.py --mode full --ticker NVDA --amount 1500000

# Repeat ticker — KnowledgeAgent will find and surface prior memos
python committee.py --mode full --ticker NVDA --amount 1500000

# Sector cap stress test
python committee.py --mode full --ticker AMD --amount 2000000
```

### Expected Output

```
  ┌─ COMMITTEE DECISION ──────────────────────────────────────────────────
  │  Ticker:     NVDA
  │  Action:     BUY
  │  Amount:     $1,500,000
  │  Conviction: HIGH
  │  Risk:       MEDIUM
  └───────────────────────────────────────────────────────────────────────

Memo saved → data/memos/20260223_1430_NVDA_BUY.md
```

The memo contains the full analysis from all 7 agents — market, fundamental,
technical, risk, prior research, and the chair's final rationale.

---

## Web Dashboard (Optional)

The dashboard is a separate FastAPI app that provides a browser UI for triggering
runs and reading memos. It is **not required** to run the committee — `committee.py`
works entirely standalone.

The dashboard and `committee.py` share the same Redis instance and `data/memos/`
directory, so memos produced by the CLI are immediately visible in the UI.

### Run Locally

```bash
# Terminal 1 — start the dashboard (port 8004)
python dashboard.py

# Terminal 2 — run the committee as normal (CLI still works alongside the dashboard)
python committee.py --mode full --ticker AAPL --amount 1000000
```

Open `http://localhost:8004` to view the portfolio, trigger runs from the UI,
and browse memos with rendered markdown.

### Dashboard Pages

| Route | Description |
|---|---|
| `/` | Portfolio overview — holdings, sector exposure, AUM |
| `/run` | Trigger a new committee run from the browser |
| `/memos` | Browse all saved memos |
| `/history` | Decision history and outcome log |
| `/system` | Redis health, workflow state, LTM summary |

---

## Docker (Dashboard + Redis Together)

`docker-compose.yml` packages the dashboard and a dedicated Redis instance
into a single stack. The committee CLI (`committee.py`) is not included in the
container — it is intended to run on the host, connecting to the containerised Redis.

```bash
# Start Redis (port 6380) and dashboard (port 8004)
docker compose up -d

# Point the CLI at the containerised Redis
REDIS_URL=redis://localhost:6380/0 python committee.py --mode full --ticker NVDA --amount 1500000
```

> Redis is exposed on port **6380** (not 6379) to avoid colliding with any
> existing local Redis instance.

### Stop and clean up

```bash
docker compose down          # stop containers, keep volumes
docker compose down -v       # stop and remove all volumes (wipes memos + LTM)
```

---

## Project Structure

```
investment_committee/
├── README.md
├── committee.py               # Entry point — Mesh setup + workflow runner (CLI)
├── dashboard.py               # Optional web UI — FastAPI on port 8004
├── portfolio.json             # $10M mandate, holdings, sector exposure
├── requirements.txt
├── .env.example               # Copy to .env and fill in your keys
├── Dockerfile                 # Builds the dashboard container
├── docker-compose.yml         # Redis + dashboard stack
├── supervisord.conf           # Process manager used inside the container
├── static/                    # Dashboard CSS + JS
├── templates/                 # Jinja2 HTML templates
├── data/
│   └── memos/                 # Memo archive — created at runtime (gitignored)
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
Agent profile that auto-generates and executes function tools under Kernel supervision.
Given a task description and system prompt, it:
1. Calls `codegen.generate()` → produces Python code
2. Runs code in `sandbox.execute()` → captures `result` variable (or return value of `async def main()`)
3. On failure, calls `repair.repair_with_retries()` (up to 3 attempts)
4. Registers successful code in the `FunctionRegistry` for reuse

The sandbox injects `task["context"]` keys as namespace variables, so
`previous_step_results`, `ticker`, `amount` etc. are available directly in
generated code.

### CustomAgent (`jarviscore.profiles.CustomAgent`)
Deterministic Python profile. No code generation, no sandbox. Implements `execute_task(task)`
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

On the second run for the same ticker, the KnowledgeAgent will surface both:
1. Prior memos scanned from `data/memos/` (file-system archive)
2. Institutional learnings from LTM (compressed decision history)

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

## Redis Keys Created Per Run

| Key Pattern | Type | Content |
|---|---|---|
| `workflow_graph:{wf_id}` | Hash | Step definitions + status |
| `workflow_state:{wf_id}` | String | Full workflow state (crash recovery) |
| `step_output:{wf_id}:{step_id}` | Hash | Step result metadata |
| `ledgers:committee` | Stream | Episodic event log (KnowledgeAgent) |
| `ltm:committee` | String | LTM summary (Chair → LTM) |

