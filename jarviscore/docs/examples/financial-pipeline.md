---
icon: material/trending-up
---

# Financial Intelligence Pipeline

[:fontawesome-brands-github: View full source](https://github.com/Prescott-Data/jarviscore-framework/blob/main/examples/ex1_financial_pipeline.py){ .md-button }

| | |
|---|---|
| **Profile** | `AutoAgent` |
| **Infra required** | Redis (auto-detected from `REDIS_URL`) |
| **Workflow** | `fetch → analyse → report` |
| **Run** | `python examples/ex1_financial_pipeline.py` |

---

## What it does

Three `AutoAgent` specialists form a sequential workflow. The `WorkflowEngine` dispatches steps in dependency order, passing outputs from each step into the next agent's execution context automatically.

```
MarketDataAgent  →  AnalysisAgent  →  ReportAgent
    fetch              analyse            report
    (OHLCV data)    (signals, alerts)  (Markdown briefing)
```

The final Markdown briefing is saved to `blob_storage/reports/financial-daily-001.md`.

---

## Key pattern: workflow DAG

```python
from jarviscore import Mesh
from jarviscore.profiles import AutoAgent

mesh = Mesh()           # No mode — Mesh auto-detects Redis from REDIS_URL (1)
mesh.add(MarketDataAgent)
mesh.add(AnalysisAgent)
mesh.add(ReportAgent)
await mesh.start()

results = await mesh.workflow("financial-daily-001", [
    {
        "id": "fetch",
        "agent": "market_data",
        "task": "Generate synthetic daily market data for AAPL, MSFT, NVDA ...",
    },
    {
        "id": "analyse",
        "agent": "analyst",
        "task": "Analyse the market data from the fetch step ...",
        "depends_on": ["fetch"],   # (2)!
    },
    {
        "id": "report",
        "agent": "reporter",
        "task": "Write an executive Markdown market briefing ...",
        "depends_on": ["analyse"],  # (3)!
    },
])
```

1. `Mesh()` with no arguments. Set `REDIS_URL` in `.env` and the Mesh connects automatically. No need to specify a mode.
2. `depends_on` tells the `WorkflowEngine` to wait until `fetch` succeeds. The `fetch` output is injected into the analyst's execution context automatically.
3. Chained dependency — `report` waits for `analyse`. Context includes both prior step outputs.

---

## Key pattern: auto-injected infrastructure

```python
class MarketDataAgent(AutoAgent):
    role = "market_data"
    capabilities = ["market_data", "data_collection", "finance"]
    system_prompt = "..."  # LLM prompt — store result in variable named 'result'

    async def setup(self):
        await super().setup()
        # self._redis_store and self._blob_storage are injected
        # by Mesh.start() BEFORE setup() is called.
        self.memory = UnifiedMemory(
            workflow_id=WORKFLOW_ID,
            step_id="fetch",
            agent_id=self.role,
            redis_store=self._redis_store,      # (1)!
            blob_storage=self._blob_storage,    # (2)!
        )
```

1. `self._redis_store` — a live `RedisMemoryStore`, ready to use. `None` if Redis is unavailable (example degrades gracefully).
2. `self._blob_storage` — a `LocalBlobStorage` instance. On cloud deployments swap for `S3BlobStorage` via config.

---

## Key pattern: crash recovery

The workflow uses a deterministic `workflow_id`. Re-running skips already-completed steps:

```bash
python examples/ex1_financial_pipeline.py   # crashes after "fetch"
python examples/ex1_financial_pipeline.py   # re-run: skips "fetch", continues from "analyse"
```

Verify in Redis:
```bash
redis-cli keys "*financial-daily-001*"
# → step_output:financial-daily-001:fetch   ← already set, will be skipped
```

---

## Success criteria

- [ ] All 3 steps complete: `fetch → analyse → report`
- [ ] Report saved to `blob_storage/reports/financial-daily-001.md`
- [ ] Console prints `Pipeline complete: 3/3 steps successful`
- [ ] Re-running skips completed steps (crash recovery)
