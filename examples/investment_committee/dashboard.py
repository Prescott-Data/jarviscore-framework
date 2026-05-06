"""
Investment Committee Dashboard — FastAPI + SSE
Port: 8004

Run: python dashboard.py
"""

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiofiles
import markdown as md_lib
import redis as redis_module
import uvicorn
from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Paths ─────────────────────────────────────────────────────────────────

BASE_DIR       = Path(__file__).parent
PORTFOLIO_PATH = BASE_DIR / "portfolio.json"
MEMO_DIR       = BASE_DIR / "data" / "memos"
STATIC_DIR     = BASE_DIR / "static"
TEMPLATE_DIR   = BASE_DIR / "templates"
REDIS_URL      = os.getenv("REDIS_URL", "redis://localhost:6379/0")

MEMO_DIR.mkdir(parents=True, exist_ok=True)

# ── FastAPI app ───────────────────────────────────────────────────────────

app = FastAPI(title="Investment Committee", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# ── Redis client ──────────────────────────────────────────────────────────

def _make_redis() -> redis_module.Redis:
    m = re.match(r"rediss?://(?:[^:@]*:[^:@]*@)?([^:]+):(\d+)/(\d+)", REDIS_URL)
    host, port, db = (m.group(1), int(m.group(2)), int(m.group(3))) if m else ("localhost", 6379, 0)
    return redis_module.Redis(
        host=host, port=port, db=db, decode_responses=True,
        socket_timeout=3, socket_connect_timeout=3,
    )

redis_client = _make_redis()

# ── Run registry ──────────────────────────────────────────────────────────

RUN_REGISTRY: Dict[str, Dict] = {}

ALL_STEPS_FULL  = [
    "market_analysis", "financial_analysis", "technical_analysis",
    "knowledge_retrieval", "risk_assessment", "memo_draft", "final_decision",
]
ALL_STEPS_QUICK = ["financial_analysis"]

# ── Helpers ───────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def _recalc_sector_exposure(data: dict) -> dict:
    total_aum = data.get("total_aum", 1)
    totals: Dict[str, float] = {}
    for h in data.get("holdings", {}).values():
        s = h.get("sector", "Unknown")
        totals[s] = totals.get(s, 0) + h.get("value", 0)
    data["sector_exposure"] = {s: round(v / total_aum, 4) for s, v in totals.items()}
    return data


async def save_portfolio(data: dict) -> None:
    data = _recalc_sector_exposure(data)
    tmp = str(PORTFOLIO_PATH) + ".tmp"
    async with aiofiles.open(tmp, "w") as f:
        await f.write(json.dumps(data, indent=2))
    os.rename(tmp, str(PORTFOLIO_PATH))


MEMO_RE   = re.compile(r"(\d{8})_(\d{4})_([A-Z0-9]+)_(BUY|HOLD|PASS)\.md$")
_SCORE_RE = re.compile(r"Overall Score[:\s]+(\d+\.?\d*)/10")
_ALLOC_RE = re.compile(r"\*\*Allocation:\*\*\s*\$([\d,]+)")
_CONV_RE  = re.compile(r"\*\*Conviction:\*\*\s*(\w+)")
_RAT_RE   = re.compile(r"\*\*Rationale:\*\*\s*(.+)")


def parse_memo_index() -> List[dict]:
    rows = []
    for f in sorted(MEMO_DIR.glob("*.md"), reverse=True):
        m = MEMO_RE.match(f.name)
        if not m:
            continue
        date_s, time_s, ticker, action = m.groups()
        try:
            content = f.read_text()
        except Exception:
            content = ""
        sm = _SCORE_RE.search(content)
        am = _ALLOC_RE.search(content)
        cm = _CONV_RE.search(content)
        rm = _RAT_RE.search(content)
        rows.append({
            "file":           f.name,
            "timestamp":      f"{date_s[:4]}-{date_s[4:6]}-{date_s[6:]} {time_s[:2]}:{time_s[2:]}",
            "ticker":         ticker,
            "action":         action,
            "allocation_usd": int(am.group(1).replace(",", "")) if am else 0,
            "overall_score":  float(sm.group(1)) if sm else None,
            "conviction":     cm.group(1) if cm else None,
            "rationale":      rm.group(1)[:120] if rm else "",
        })
    return rows


async def _redis_ok() -> bool:
    try:
        return bool(await asyncio.to_thread(redis_client.ping))
    except Exception:
        return False


async def _ltm_content() -> str:
    try:
        return await asyncio.to_thread(redis_client.get, "ltm:committee") or ""
    except Exception:
        return ""


async def _redis_key_counts() -> dict:
    try:
        patterns = {
            "workflow_state": "workflow_state:*",
            "step_output":    "step_output:*",
            "workflow_graph": "workflow_graph:*",
            "ledgers":        "ledgers:*",
            "ltm":            "ltm:*",
        }
        counts = {}
        for k, v in patterns.items():
            keys = await asyncio.to_thread(redis_client.keys, v)
            counts[k] = len(keys)
        return counts
    except Exception:
        return {}

# ── Background run task ───────────────────────────────────────────────────

async def _run_background(run_id: str) -> None:
    import sys
    sys.path.insert(0, str(BASE_DIR))
    from jarviscore import Mesh
    from agents.market_analyst    import MarketAnalystAgent
    from agents.financial_analyst import FinancialAnalystAgent
    from agents.technical_analyst import TechnicalAnalystAgent
    from agents.risk_officer      import RiskOfficerAgent
    from agents.knowledge_agent   import KnowledgeAgent
    from agents.memo_writer       import MemoWriterAgent
    from agents.committee_chair   import CommitteeChairAgent
    from committee                import FULL_STEPS, QUICK_STEPS

    run    = RUN_REGISTRY[run_id]
    ticker = run["ticker"]
    amount = run["amount"]
    mode   = run["mode"]
    wf_id  = run["wf_id"]

    try:
        portfolio  = load_portfolio()
        mesh = Mesh(mode="autonomous", config={"redis_url": REDIS_URL})
        for AgentClass in [MarketAnalystAgent, FinancialAnalystAgent,
                           TechnicalAnalystAgent, RiskOfficerAgent,
                           KnowledgeAgent, MemoWriterAgent, CommitteeChairAgent]:
            mesh.add(AgentClass)

        await mesh.start()

        base_steps = QUICK_STEPS if mode == "quick" else FULL_STEPS
        params = {
            "ticker":    ticker,
            "amount":    amount,
            "mandate":   portfolio.get("constraints", {}),
            "portfolio": portfolio,
        }
        steps   = [{**s, "params": params} for s in base_steps]
        results = await mesh.workflow(wf_id, steps)
        await mesh.stop()

        step_ids = [s["id"] for s in base_steps]
        by_id: Dict[str, Any] = {}
        for i, r in enumerate(results):
            sid = r.get("step_id") or (step_ids[i] if i < len(step_ids) else None)
            if sid:
                by_id[sid] = r

        dec = by_id.get("final_decision", {})
        out = dec.get("output", {})

        memos     = sorted(MEMO_DIR.glob(f"*_{ticker}_*.md"), reverse=True)
        memo_file = memos[0].name if memos else None

        run["status"] = "complete"
        run["result"] = {
            "action":         out.get("action", "—"),
            "allocation_usd": out.get("allocation_usd", 0),
            "conviction":     out.get("conviction", "—"),
            "rationale":      out.get("rationale", ""),
            "ticker":         ticker,
            "memo_file":      memo_file,
        }

        if mode == "quick":
            fin = by_id.get("financial_analysis", {}).get("output", {})
            run["result"].update({
                "action":         "QUICK",
                "pe_trailing":    fin.get("pe_trailing"),
                "price_to_sales": fin.get("price_to_sales"),
                "overall_score":  fin.get("overall_score"),
                "verdict":        fin.get("verdict"),
            })

    except Exception as exc:
        run["status"] = "error"
        run["error"]  = str(exc)

# ── SSE generator ─────────────────────────────────────────────────────────

async def _sse_generator(run_id: str):
    if run_id not in RUN_REGISTRY:
        yield f"event: error\ndata: {json.dumps({'message': 'Unknown run'})}\n\n"
        return

    run      = RUN_REGISTRY[run_id]
    wf_id    = run["wf_id"]
    mode     = run["mode"]
    step_ids = ALL_STEPS_QUICK if mode == "quick" else ALL_STEPS_FULL
    reported: Dict[str, str] = {}
    deadline = time.time() + 600

    while time.time() < deadline:
        for sid in step_ids:
            try:
                raw = await asyncio.to_thread(redis_client.hget, f"workflow_graph:{wf_id}", sid)
                if raw:
                    data    = json.loads(raw)
                    status  = data.get("status", "pending")
                    updated = data.get("updated_at", 0)
                    elapsed = round(updated - run["started_at"], 1) if updated else None
                    if reported.get(sid) != status:
                        reported[sid] = status
                        payload = json.dumps({"step": sid, "status": status, "elapsed": elapsed})
                        yield f"event: step_update\ndata: {payload}\n\n"
            except Exception:
                pass

        reg_status = run.get("status")
        if reg_status == "complete":
            yield f"event: complete\ndata: {json.dumps(run['result'])}\n\n"
            return
        if reg_status == "error":
            yield f"event: error\ndata: {json.dumps({'message': run.get('error', 'Unknown error')})}\n\n"
            return

        await asyncio.sleep(0.5)

    yield f"event: error\ndata: {json.dumps({'message': 'Timeout after 10 minutes'})}\n\n"

# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    portfolio = load_portfolio()
    memos     = parse_memo_index()[:5]
    holdings  = [{"ticker": t, **v} for t, v in portfolio.get("holdings", {}).items()]
    return templates.TemplateResponse("index.html", {
        "request":      request,
        "portfolio":    portfolio,
        "holdings":     holdings,
        "sector_exp":   portfolio.get("sector_exposure", {}),
        "sector_cap":   portfolio.get("constraints", {}).get("sector_cap_pct", 0.40),
        "recent_memos": memos,
        "last_run":     memos[0]["timestamp"] if memos else "—",
        "page":         "home",
    })


@app.get("/run", response_class=HTMLResponse)
async def run_form(request: Request):
    return templates.TemplateResponse("run.html", {
        "request": request,
        "page":    "run",
        "run":     None,
    })


@app.post("/run")
async def run_submit(
    background_tasks: BackgroundTasks,
    ticker: str  = Form(...),
    amount: float = Form(...),
    mode:   str  = Form("full"),
):
    ticker = ticker.strip().upper()
    ts     = int(time.time())
    run_id = f"{ticker}-{ts}"
    wf_id  = f"committee-{ticker}-{ts}"

    RUN_REGISTRY[run_id] = {
        "ticker":     ticker,
        "amount":     amount,
        "mode":       mode,
        "wf_id":      wf_id,
        "status":     "running",
        "result":     None,
        "error":      None,
        "started_at": time.time(),
    }
    background_tasks.add_task(_run_background, run_id)
    return RedirectResponse(f"/run/{run_id}", status_code=303)


@app.get("/run/{run_id}", response_class=HTMLResponse)
async def run_progress(request: Request, run_id: str):
    run = RUN_REGISTRY.get(run_id)
    if not run:
        return RedirectResponse("/run")
    step_ids = ALL_STEPS_QUICK if run["mode"] == "quick" else ALL_STEPS_FULL
    return templates.TemplateResponse("run.html", {
        "request":  request,
        "page":     "run",
        "run":      run,
        "run_id":   run_id,
        "step_ids": step_ids,
    })


@app.get("/run/{run_id}/stream")
async def run_stream(run_id: str):
    return StreamingResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/memos", response_class=HTMLResponse)
async def memos_page(request: Request, file: Optional[str] = None):
    all_memos     = parse_memo_index()
    selected_file = file or (all_memos[0]["file"] if all_memos else None)
    memo_html     = ""
    if selected_file:
        path = MEMO_DIR / selected_file
        if path.exists():
            raw       = path.read_text()
            memo_html = md_lib.markdown(raw, extensions=["tables", "fenced_code"])
    return templates.TemplateResponse("memos.html", {
        "request":       request,
        "page":          "memos",
        "all_memos":     all_memos,
        "selected_file": selected_file,
        "memo_html":     memo_html,
    })


@app.get("/memos/download/{filename}")
async def memo_download(filename: str):
    path = MEMO_DIR / filename
    if not path.exists():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(str(path), filename=filename, media_type="text/markdown")


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio_page(request: Request, saved: Optional[str] = None):
    portfolio = load_portfolio()
    holdings  = [{"ticker": t, **v} for t, v in portfolio.get("holdings", {}).items()]
    sectors   = [
        "Technology", "Financials", "Healthcare", "Energy", "Consumer",
        "Industrials", "Materials", "Utilities", "Real Estate", "Communication", "Unknown",
    ]
    return templates.TemplateResponse("portfolio.html", {
        "request":   request,
        "page":      "portfolio",
        "portfolio": portfolio,
        "holdings":  holdings,
        "sectors":   sectors,
        "raw_json":  json.dumps(portfolio, indent=2),
        "saved":     saved == "1",
        "error":     None,
    })


@app.post("/portfolio")
async def portfolio_save(request: Request):
    form     = await request.form()
    raw_json = form.get("raw_json", "").strip()

    sectors = [
        "Technology", "Financials", "Healthcare", "Energy", "Consumer",
        "Industrials", "Materials", "Utilities", "Real Estate", "Communication", "Unknown",
    ]

    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            portfolio = load_portfolio()
            return templates.TemplateResponse("portfolio.html", {
                "request":   request,
                "page":      "portfolio",
                "portfolio": portfolio,
                "holdings":  [{"ticker": t, **v} for t, v in portfolio.get("holdings", {}).items()],
                "sectors":   sectors,
                "raw_json":  raw_json,
                "error":     f"Invalid JSON: {e}",
                "saved":     False,
            })
    else:
        data = load_portfolio()
        data["total_aum"]      = float(form.get("total_aum", data["total_aum"]))
        data["available_cash"] = float(form.get("available_cash", data["available_cash"]))
        c = data.setdefault("constraints", {})
        c["max_position_usd"]     = float(form.get("max_position_usd",     c.get("max_position_usd",     3000000)))
        c["sector_cap_pct"]       = float(form.get("sector_cap_pct",       c.get("sector_cap_pct",       40))) / 100
        c["max_drawdown_pct"]     = float(form.get("max_drawdown_pct",     c.get("max_drawdown_pct",     20))) / 100
        c["min_daily_volume_usd"] = float(form.get("min_daily_volume_usd", c.get("min_daily_volume_usd", 1000000)))
        restricted_raw        = form.get("restricted_tickers", "")
        c["restricted_tickers"] = [t.strip().upper() for t in restricted_raw.split(",") if t.strip()]

        tickers  = form.getlist("h_ticker")
        h_sectors = form.getlist("h_sector")
        values   = form.getlist("h_value")
        costs    = form.getlist("h_cost_basis")
        holdings = {}
        for t, s, v, cb in zip(tickers, h_sectors, values, costs):
            t = t.strip().upper()
            if t:
                holdings[t] = {"sector": s, "value": float(v or 0), "cost_basis": float(cb or 0)}
        data["holdings"] = holdings

    await save_portfolio(data)
    return RedirectResponse("/portfolio?saved=1", status_code=303)


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    memos   = parse_memo_index()
    tickers = sorted({m["ticker"] for m in memos})
    return templates.TemplateResponse("history.html", {
        "request": request,
        "page":    "history",
        "memos":   memos,
        "ltm":     await _ltm_content(),
        "tickers": tickers,
    })


@app.get("/system", response_class=HTMLResponse)
async def system_page(request: Request):
    blob_path = BASE_DIR / "blob_storage"
    redis_ok, ltm, key_counts = await asyncio.gather(
        _redis_ok(), _ltm_content(), _redis_key_counts()
    )
    return templates.TemplateResponse("system.html", {
        "request":     request,
        "page":        "system",
        "redis_ok":    redis_ok,
        "redis_url":   REDIS_URL,
        "ltm":         ltm,
        "key_counts":  key_counts,
        "agents":      [
            "market_analyst", "financial_analyst", "technical_analyst",
            "risk_officer", "knowledge_agent", "memo_writer", "committee_chair",
        ],
        "blob_exists": blob_path.exists(),
        "blob_path":   str(blob_path),
    })


# ── Entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("dashboard:app", host="0.0.0.0", port=8004, reload=False)
