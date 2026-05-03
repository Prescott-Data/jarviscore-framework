---
icon: material/cash-multiple
---

# Investment Committee

[:fontawesome-brands-github: View full source](https://github.com/Prescott-Data/jarviscore-framework/tree/main/examples/investment_committee){ .md-button }

| | |
|---|---|
| **Profile** | `AutoAgent` + `CustomAgent` (mixed) |
| **Infra required** | Redis (auto-detected), `yfinance` |
| **Agents** | 7 specialist agents |
| **Run** | `cd examples/investment_committee && python committee.py --mode full --ticker NVDA` |

---

## What it does

The flagship example. Seven specialist agents form a real investment committee that deliberates over a stock allocation decision. Each agent plays a distinct professional role — market analyst, financial analyst, technical analyst, risk officer, knowledge agent, memo writer, and committee chair.

This is the only example that **mixes** `AutoAgent` and `CustomAgent` profiles in the same mesh, and uses the most complex workflow DAG across all examples.

```
market_analysis  ──┐
financial_analysis ─┼──→ risk_assessment ──┐
technical_analysis ─┤                      │
knowledge_retrieval┘   memo_draft ←────────┘
                            ↓
                      final_decision  (committee chair)
```

The committee chair reads the full memo and all prior analyses, then outputs a structured `BUY / HOLD / PASS` decision with allocation amount, conviction level, and conditions.

---

## Run modes

```bash
cd examples/investment_committee

# Quick mode — fundamentals only (1 step, fast)
python committee.py --mode quick --ticker AAPL

# Full mode — complete deliberation pipeline (6 steps)
python committee.py --mode full --ticker NVDA --amount 1500000
python committee.py --mode full --ticker AMD  --amount 2000000
```

---

## Key pattern: mixed profiles in one mesh

```python
from jarviscore import Mesh

mesh = Mesh(config={"redis_url": REDIS_URL})   # (1)!

for AgentClass in [
    MarketAnalystAgent,      # AutoAgent — uses yfinance + LLM analysis
    FinancialAnalystAgent,   # AutoAgent — pulls P/E, P/S, EV/EBITDA
    TechnicalAnalystAgent,   # AutoAgent — RSI, MA crossover, trend
    RiskOfficerAgent,        # AutoAgent — VaR, mandate compliance
    KnowledgeAgent,          # CustomAgent — reads from LTM, no LLM needed (2)!
    MemoWriterAgent,         # AutoAgent — synthesises all prior outputs
    CommitteeChairAgent,     # AutoAgent — final BUY/HOLD/PASS decision
]:
    mesh.add(AgentClass)

await mesh.start()
```

1. No `mode=` argument. `Mesh()` detects Redis and activates the workflow engine with persistence automatically.
2. `KnowledgeAgent` is a `CustomAgent` that reads from long-term memory — mixing profiles lets you use the right tool for each role.

---

## Key pattern: complex fan-in DAG

```python
steps = [
    {"id": "market_analysis",    "agent": "market_analyst",    "task": "..."},
    {"id": "financial_analysis", "agent": "financial_analyst",  "task": "..."},
    {"id": "technical_analysis", "agent": "technical_analyst",  "task": "..."},
    {"id": "knowledge_retrieval","agent": "knowledge_agent",    "task": "..."},
    {
        "id": "risk_assessment",
        "agent": "risk_officer",
        "task": "Assess risk for a {amount} USD position in {ticker} ...",
        "depends_on": ["market_analysis", "financial_analysis"],  # (1)! fan-in
        "params": params,
    },
    {
        "id": "memo_draft",
        "agent": "memo_writer",
        "task": "Write a formal investment memo ...",
        "depends_on": [                                           # (2)! convergence
            "market_analysis", "financial_analysis",
            "technical_analysis", "knowledge_retrieval", "risk_assessment",
        ],
        "params": params,
    },
    {
        "id": "final_decision",
        "agent": "committee_chair",
        "task": "Review the memo and make the final allocation decision ...",
        "depends_on": ["memo_draft"],
        "params": params,
    },
]

results = await mesh.workflow(wf_id, steps)
```

1. `risk_assessment` fans in from two parallel analyses. The `WorkflowEngine` waits for both before dispatching.
2. `memo_draft` is the convergence point — it waits for all five preceding steps and receives all their outputs as `previous_step_results` in the execution context.

---

## Expected output (full mode)

```
==============================
  Investment Committee | FULL | NVDA | $1,500,000
==============================

  ┌─ COMMITTEE DECISION ──────────────────────────
  │  Ticker:     NVDA
  │  Action:     BUY
  │  Allocation: $1,200,000
  │  Conviction: HIGH
  │  Rationale:  Strong AI infrastructure tailwinds, dominant market position,
  │              acceptable valuation given growth trajectory.
  │  Conditions: Monitor Q3 earnings; set stop-loss at $850
  └──────────────────────────────────────────────────────

  Full memo written to data/memos/
```

---

## File structure

```
examples/investment_committee/
├── committee.py             ← entry point (run this)
├── portfolio.json           ← mandate + current holdings
├── agents/
│   ├── base.py              ← shared CommitteeAutoAgent base class
│   ├── committee_chair.py
│   ├── financial_analyst.py
│   ├── knowledge_agent.py   ← CustomAgent (reads LTM)
│   ├── market_analyst.py
│   ├── memo_writer.py
│   ├── risk_officer.py
│   └── technical_analyst.py
└── dashboard.py             ← optional rich terminal dashboard
```
