/* Investment Committee Dashboard — app.js */

/* ── SSE client (Run page) ──────────────────────────────────────────────── */

function initSSE(runId, ticker, amount) {
  const es = new EventSource(`/run/${runId}/stream`);

  es.addEventListener("step_update", (e) => {
    const d = JSON.parse(e.data);
    updateStepTile(d.step, d.status, d.elapsed);
  });

  es.addEventListener("complete", (e) => {
    const d = JSON.parse(e.data);
    es.close();
    showResult(d, ticker, amount);
    updateBadge("complete");
  });

  es.addEventListener("error", (e) => {
    es.close();
    let msg = "Connection lost";
    try { msg = JSON.parse(e.data).message; } catch (_) {}
    showError(msg);
    updateBadge("error");
  });
}

function updateStepTile(stepId, status, elapsed) {
  const el = document.getElementById(`step-${stepId}`);
  if (!el) return;

  el.classList.remove("step-pending", "step-running", "step-done", "step-error");
  el.classList.add(`step-${status === "completed" ? "done" : status === "in_progress" ? "running" : status}`);

  const timeEl = el.querySelector(".step-time");
  if (timeEl) {
    if (status === "completed" && elapsed !== null) {
      timeEl.textContent = `${elapsed}s`;
    } else if (status === "in_progress") {
      timeEl.textContent = "running…";
    } else if (status === "failed") {
      timeEl.textContent = "failed";
    } else {
      timeEl.textContent = status;
    }
  }
}

function updateBadge(state) {
  const badge = document.getElementById("run-status-badge");
  if (!badge) return;
  badge.classList.remove("animate-pulse", "bg-blue-100", "text-blue-700",
                          "bg-emerald-100", "text-emerald-700",
                          "bg-red-100", "text-red-700");
  if (state === "complete") {
    badge.classList.add("bg-emerald-100", "text-emerald-700");
    badge.textContent = "Complete";
  } else if (state === "error") {
    badge.classList.add("bg-red-100", "text-red-700");
    badge.textContent = "Error";
  }
}

function showResult(d, ticker, amount) {
  const panel = document.getElementById("result-panel");
  if (!panel) return;
  panel.classList.remove("hidden");

  const actionEl = document.getElementById("res-action");
  if (actionEl) {
    actionEl.textContent = d.action || "—";
    actionEl.className = "text-3xl font-bold " + (
      d.action === "BUY"  ? "text-emerald-600" :
      d.action === "HOLD" ? "text-amber-500"   :
      d.action === "PASS" ? "text-red-500"      : "text-slate-700"
    );
  }

  const taEl = document.getElementById("res-ticker-amount");
  if (taEl) {
    if (d.action === "QUICK") {
      taEl.textContent = `P/E: ${d.pe_trailing ?? "—"}  ·  P/S: ${d.price_to_sales ?? "—"}  ·  Score: ${d.overall_score ?? "—"}/10 (${d.verdict ?? ""})`;
    } else {
      const alloc = d.allocation_usd ? `$${Number(d.allocation_usd).toLocaleString()}` : "$0";
      taEl.textContent = `${d.ticker}  ·  ${alloc}`;
    }
  }

  const convEl = document.getElementById("res-conviction");
  if (convEl) convEl.textContent = d.conviction || "—";

  const ratEl = document.getElementById("res-rationale");
  if (ratEl) ratEl.textContent = d.rationale || "—";

  const linkEl = document.getElementById("res-memo-link");
  if (linkEl && d.memo_file) {
    linkEl.href = `/memos?file=${d.memo_file}`;
    linkEl.classList.remove("hidden");
  }
}

function showError(msg) {
  const panel = document.getElementById("error-panel");
  const msgEl = document.getElementById("error-msg");
  if (panel) panel.classList.remove("hidden");
  if (msgEl) msgEl.textContent = msg;
}

/* ── Portfolio editor ───────────────────────────────────────────────────── */

let _totalAum    = 10000000;
let _sectorCap   = 0.40;

const SECTOR_OPTS = [
  "Technology","Financials","Healthcare","Energy","Consumer",
  "Industrials","Materials","Utilities","Real Estate","Communication","Unknown"
];

function initPortfolioEditor(totalAum, sectorCap) {
  _totalAum  = totalAum;
  _sectorCap = sectorCap;
  document.querySelectorAll(".holding-value").forEach(el => {
    el.addEventListener("input", recalcSectors);
  });
  recalcSectors();
}

function addHoldingRow() {
  const table = document.getElementById("holdings-table");
  const row   = document.createElement("div");
  row.className = "holding-row grid grid-cols-12 gap-2 items-center";

  const sectorOptions = SECTOR_OPTS.map(s => `<option value="${s}">${s}</option>`).join("");

  row.innerHTML = `
    <input name="h_ticker" type="text" placeholder="TICK"
           class="col-span-2 border border-slate-200 rounded px-2 py-1.5 text-sm font-mono uppercase
                  focus:outline-none focus:ring-2 focus:ring-blue-400"/>
    <select name="h_sector"
            class="col-span-3 border border-slate-200 rounded px-2 py-1.5 text-sm
                   focus:outline-none focus:ring-2 focus:ring-blue-400">
      ${sectorOptions}
    </select>
    <input name="h_value" type="number" value="0" placeholder="Value"
           class="col-span-3 border border-slate-200 rounded px-2 py-1.5 text-sm holding-value
                  focus:outline-none focus:ring-2 focus:ring-blue-400"/>
    <input name="h_cost_basis" type="number" value="0" step="0.01" placeholder="Cost"
           class="col-span-3 border border-slate-200 rounded px-2 py-1.5 text-sm
                  focus:outline-none focus:ring-2 focus:ring-blue-400"/>
    <button type="button" onclick="removeRow(this)"
            class="col-span-1 text-red-400 hover:text-red-600 text-lg leading-none">✕</button>
  `;
  row.querySelector(".holding-value").addEventListener("input", recalcSectors);
  table.appendChild(row);
  recalcSectors();
}

function removeRow(btn) {
  btn.closest(".holding-row").remove();
  recalcSectors();
}

function recalcSectors() {
  const aum = parseFloat(document.querySelector('[name="total_aum"]')?.value) || _totalAum;
  const rows   = document.querySelectorAll(".holding-row");
  const totals = {};

  rows.forEach(row => {
    const sector = row.querySelector('[name="h_sector"]')?.value || "Unknown";
    const value  = parseFloat(row.querySelector('[name="h_value"]')?.value) || 0;
    totals[sector] = (totals[sector] || 0) + value;
  });

  const preview = document.getElementById("sector-preview");
  if (!preview) return;
  preview.innerHTML = Object.entries(totals).map(([s, v]) => {
    const pct   = (v / aum * 100).toFixed(1);
    const over  = v / aum > _sectorCap;
    return `<span class="px-2 py-1 rounded-lg ${over ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-600"}">
              ${s}: <strong>${pct}%</strong>
            </span>`;
  }).join("");
}

/* ── Raw JSON toggle ────────────────────────────────────────────────────── */

function toggleJson() {
  const editor = document.getElementById("json-editor");
  const icon   = document.getElementById("json-toggle-icon");
  if (!editor) return;
  const hidden = editor.classList.toggle("hidden");
  if (icon) icon.textContent = hidden ? "▶" : "▼";
}

function validateJson() {
  const area = document.getElementById("raw-json-area");
  const msg  = document.getElementById("json-validate-msg");
  if (!area || !msg) return;
  try {
    JSON.parse(area.value);
    msg.textContent = "✓ Valid JSON";
    msg.className   = "text-xs py-1.5 text-emerald-600";
  } catch (e) {
    msg.textContent = `✗ ${e.message}`;
    msg.className   = "text-xs py-1.5 text-red-600";
  }
}

/* ── History filters ────────────────────────────────────────────────────── */

function initHistoryFilters() {
  const tickerSel  = document.getElementById("filter-ticker");
  const actionSel  = document.getElementById("filter-action");
  const searchInp  = document.getElementById("filter-search");
  const countEl    = document.getElementById("row-count");

  function applyFilters() {
    const ticker = tickerSel?.value.toLowerCase() || "";
    const action = actionSel?.value.toLowerCase() || "";
    const search = searchInp?.value.toLowerCase() || "";

    let visible = 0;
    document.querySelectorAll(".history-row").forEach(row => {
      const match =
        (!ticker || row.dataset.ticker.toLowerCase() === ticker) &&
        (!action || row.dataset.action.toLowerCase() === action) &&
        (!search || row.dataset.search.toLowerCase().includes(search));
      row.style.display = match ? "" : "none";
      if (match) visible++;
    });
    if (countEl) countEl.textContent = `${visible} decisions`;
  }

  tickerSel?.addEventListener("change", applyFilters);
  actionSel?.addEventListener("change", applyFilters);
  searchInp?.addEventListener("input",  applyFilters);
}

/* ── Header status dots (ping on load) ─────────────────────────────────── */

async function checkHeaderStatus() {
  try {
    await fetch("/health");
    // /health is instant (no Redis). Real Redis status is on the /system page.
    const redisEl = document.querySelector("#redis-status span:first-child");
    const ltmEl   = document.querySelector("#ltm-status span:first-child");
    if (redisEl) redisEl.className = "inline-block w-2 h-2 rounded-full bg-emerald-500";
    if (ltmEl)   ltmEl.className   = "inline-block w-2 h-2 rounded-full bg-emerald-500";
  } catch (_) {}
}
checkHeaderStatus();
