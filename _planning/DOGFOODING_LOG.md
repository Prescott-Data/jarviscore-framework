# JarvisCore Dogfooding Log

## Overview
Issues and improvements discovered while using JarvisCore internally
at Prescott Data for Finance and Marketing operations (Team Treasury + Team Signal).

---

### [ISSUE-001] CLI scaffold fails — missing `jarviscore.data` module
- **Discovered**: 2026-04-15
- **System**: Setup / Foundation
- **Severity**: Major
- **Component**: CLI (`jarviscore.cli.scaffold`)
- **Description**: `python -m jarviscore.cli.scaffold --examples` crashes with `ModuleNotFoundError: No module named 'jarviscore.data'`. The `get_data_path()` function in `scaffold.py` calls `resources.files('jarviscore.data')` but the `jarviscore/data/` directory doesn't exist in the repository. The `pyproject.toml` references `jarviscore = ["docs/*.md", "data/.env.example", "data/examples/*.py"]` in `[tool.setuptools.package-data]` but the actual data directory was never committed.
- **Expected**: Scaffold should create `.env.example` and example files in the target directory.
- **Workaround**: Manually copy `.env.example` from repo root and create project structure by hand.
- **Fix**: Create `jarviscore/data/` directory with `__init__.py`, `.env.example`, and `examples/` subdirectory containing the example scripts. Or update `scaffold.py` to use `Path(__file__).parent.parent / '.env.example'` as fallback.
- **Status**: Open
- **PR**: —

---

### [ISSUE-002] Model routing limited to 2 tiers — no per-agent or per-task routing
- **Discovered**: 2026-04-15
- **System**: Foundation / Kernel
- **Severity**: Enhancement
- **Component**: Kernel (`jarviscore.kernel.kernel._get_model_for_tier`), Config (`settings.py`)
- **Description**: JarvisCore supports only 2-tier model routing via `CODING_MODEL` and `TASK_MODEL` settings. The Kernel classifies tasks as "coder", "researcher", or "communicator" and routes to one of two models. With real Azure deployments having 9+ models (gpt-5.2-codex, gpt-5.2-chat, gpt-5.4-nano, gpt-5.4-mini, gpt-5, gpt-5.3-codex, gpt-5.3-chat, gpt-4o, gpt-4o-mini), there's no way to:
  1. Route per-agent (Ingram needs codex for parsing, Sentinel needs chat for research)
  2. Route per-task-complexity (use nano for quick classifications, flagship for complex reasoning)
  3. Set model preferences at the AutoAgent level (via class attribute or system_prompt)
  4. Do cost-aware routing (use cheaper models when task is simple)
- **Expected**: Support for per-agent model overrides, task-complexity-based routing, and cost-aware model selection. e.g., `class Ingram(AutoAgent): preferred_model = "gpt-5.2-codex"` or routing tiers beyond just "coding" and "task".
- **Workaround**: All agents currently use the global 2-tier routing. coding_model=gpt-5.2-codex, task_model=gpt-5.2-chat. Works but suboptimal — Sentinel (research) gets the same model as Folio (reporting).
- **Status**: Open
- **PR**: —

---

### [ISSUE-003] Azure `_call_azure` uses `max_tokens` — breaks gpt-5.x models
- **Discovered**: 2026-04-15
- **System**: Foundation / LLM
- **Severity**: Critical
- **Component**: `jarviscore.execution.llm.UnifiedLLMClient._call_azure`
- **Description**: The Azure OpenAI call uses `max_tokens` parameter which is rejected by gpt-5.x models with: `"Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."`. Same issue exists in `jarviscore.cli.check._test_azure()`.
- **Expected**: Framework should use `max_completion_tokens` for gpt-5.x compatibility (it's backward-compatible with older models).
- **Workaround**: Patched `_call_azure` in `llm.py` line 294 to use `max_completion_tokens`. Fix applied in `dogfood/internal-agents` branch.
- **Status**: Fixed locally (needs PR)
- **PR**: —

---

### [ISSUE-004] gpt-5.x models reject temperature≠1 — hardcoded in generator
- **Discovered**: 2026-04-15
- **System**: Foundation / LLM
- **Severity**: Critical
- **Component**: `jarviscore.execution.generator.CodeGenerator.generate` (line 178), `jarviscore.execution.llm.UnifiedLLMClient._call_azure`
- **Description**: `CodeGenerator.generate()` hardcodes `temperature=0.3` for code generation. gpt-5.x models reject any temperature value that isn't 1 (default) with: `"Unsupported value: 'temperature' does not support 0.3"`. The framework needs to handle model-specific parameter constraints.
- **Workaround**: Patched `_call_azure` to conditionally omit temperature for gpt-5.x models (deployment name starts with "gpt-5"). Fix applied in `dogfood/internal-agents` branch.
- **Status**: Fixed locally (needs PR)
- **PR**: —

---

### [ISSUE-005] DuckDuckGo search fails with SSL certificate error on macOS
- **Discovered**: 2026-04-15
- **System**: Execution / Search
- **Severity**: Minor
- **Component**: `jarviscore.execution.search` (DuckDuckGo client)
- **Description**: Internet search via DuckDuckGo fails with `SSLCertVerificationError: certificate verify failed: self-signed certificate in certificate chain`. Common on macOS with Python installed via python.org (missing certifi certificates). Agent gracefully handles the failure and completes the task without search results, but this limits research agents like Sentinel.
- **Workaround**: Run `pip install certifi` and/or `/Applications/Python 3.12/Install Certificates.command`. Or the framework could set `ssl=False` as a fallback.
- **Status**: Open
- **PR**: —

---

### [RESOLVE-006] Sky Team agents had no code execution capability — write/execute/register pipeline missing
- **Discovered**: 2026-04-16
- **System**: Execution / Coder / Kernel
- **Severity**: Critical (Sky Team could not post to LinkedIn, GA4, X, etc.)
- **Root cause**: CoderSubAgent had basic write_code/execute_code tools but no ValidationLayer, no registry-first routing, no HTTP contract enforcement, no REACTPP guidance. Kernel used keyword matching to decide coder vs researcher (wrong order — research is supposed to fire ONLY on failure, not as a prerequisite).
- **Fix implemented**:
  1. **`execution/validation.py`** [NEW] — `ValidationLayer` with 3 sub-validators:
     - `StaticValidator`: syntax + `result` variable mandate
     - `SecurityValidator`: no hardcoded secrets / `eval()` / `__import__`
     - `HTTPContractEnforcer`: HTTP calls MUST have `raise_for_status()` or `status_code` check
  2. **`execution/generator.py`** [UPGRADED] — REACTPP 2-block output format (JSON metadata + Python, no prose), registry capability pre-check injection, self-repair loop (syntax + contract), `fix_code()` with dedicated repair prompt, structured `GeneratedCode` return type
  3. **`kernel/defaults/coder.py`** [UPGRADED] — REACTPP system prompt, `check_registry` tool (Option A fast path), `ValidationLayer` gate in `write_code` (blocks invalid code before sandbox), `register_function` tool (promotes to FunctionRegistry on success), structured CandidateStore audit trail
  4. **`kernel/kernel.py`** [UPGRADED] — Registry-first `_check_registry_reuse()` (Option A), research-on-failure `_should_escalate_to_researcher()` (Option C — never fires as prerequisite), correct pipeline: Registry → Coder → Sandbox → Research-on-failure
- **Pipeline now matches integration-agent staging**:
  ```
  1. FunctionRegistry semantic search  ← reuse verified function if score≥2
  2. Coder writes from training data   ← LLM knows LinkedIn/GA4/X APIs
  3. ValidationLayer gate              ← syntax + security + HTTP contract
  4. SandboxExecutor                   ← real execution test
  5. Research-on-failure ONLY         ← fires if coder signals or 404/schema error
  6. FunctionRegistry.register()       ← CANDIDATE → VERIFIED → GOLDEN
  ```
- **Verified**: 7/7 ValidationLayer unit tests pass (no result var rejected, HTTP without raise_for_status rejected, hardcoded secret rejected, eval() rejected, main() return accepted, raise_for_status accepted)
- **Status**: Fixed
- **OSS push**: Yes (no proprietary patterns used)

---

### [RESOLVE-007] OODA loop rewrite — agents had no turn-by-turn reasoning, no persistent state, no context isolation
- **Discovered**: 2026-04-23
- **System**: Kernel / SubAgent / Context / Memory
- **Severity**: Critical (root cause of shallow, toy-like agent behavior)
- **Root cause**: `BaseSubAgent.run()` was a chatbot-style flat loop:
  - Context was a raw `messages[]` list that grew unbounded (no priority, no trimming)
  - No connection to existing infrastructure (`UnifiedMemory`, `KernelState`, `ContextManager` all existed but were unwired)
  - `max_turns` defaulted to 1-8 (agents couldn't do deep multi-turn work)
  - Convergence governor existed but was only partially wired (stall detection called but results not always acted upon)
  - Subagents created fresh each dispatch (no state reuse within a workflow step)
  - Subagent prompts were 8-12 lines of generic instructions (no behavioral doctrine)
- **Analysis method**: First-principles comparison against integration-agent (IA) and collaboration-agent (CA) on `origin/main`. IA/CA used as learning references, NOT as copy-paste source. All changes are generic OSS framework improvements.
- **Fix implemented (6 files, ~3000 lines)**:
  1. **`kernel/state.py`** [REWRITE] — Expanded `KernelState` from 53-line dataclass to 140-line Pydantic model:
     - `ToolResult` model for structured tool invocation records
     - Mutation methods: `add_tool_result()`, `add_thought()`, `get_final_output()`
     - `internal_variables` (flexible key-value), `belief_state` (constraints/hypotheses)
     - Full serialize/deserialize support for Redis checkpoint/resume
  2. **`context/context_manager.py`** [REWRITE] — Priority-stack context builder:
     - 8-block priority stack: Mission → Failure Memory → Input → Belief → Thoughts → LTM → History → Variables
     - tiktoken-first token counting with word-count fallback (optional dependency)
     - Secret scrubbing (`_SENSITIVE_KEYS` pattern: password, token, api_key, etc.)
     - State-aware `auto_summarize_if_needed()` — compresses oldest 30% of tool history into LTM
     - Backward-compatible: still accepts `Dict` input alongside `KernelState`
  3. **`kernel/subagent.py`** [REWRITE] — OODA loop execution engine:
     - Context rebuilt from `KernelState` each turn via `ContextManager.build_context(state)` (no unbounded `messages[]`)
     - Primary loop governors: `lease.is_expired()` + `cognition.should_continue()` (not hardcoded `max_turns`)
     - `max_turns` demoted to emergency fuse only (default raised from 4→15)
     - OBSERVE→ORIENT→DECIDE→ACT cadence with convergence evaluation after each tool call
     - Failure recording + repeat-action blocking via `FailureLedger`
     - Auto-summarization when context grows too large
     - `system` + `user` message pattern (2-message call each turn, not multi-turn conversation)
     - `_pre_run_hook()` override point for subclass-specific pre-flight
     - JSON protocol fallback parser (for models that prefer structured JSON output)
     - Memory integration: turn logging via `UnifiedMemory.log_turn()`, checkpoint via `save_checkpoint()`
     - Typed outcomes in all exit paths (`YIELD_LEASE_EXHAUSTED`, `YIELD_CONVERGENCE_STALL`, etc.)
  4. **`kernel/kernel.py`** [UPGRADED] — Supervisor now creates and passes full infrastructure:
     - `_create_memory()` — creates `UnifiedMemory` per workflow step (graceful degradation if no Redis/blob)
     - `_create_context_manager()` — creates `ContextManager` with role-appropriate `BudgetConfig`
     - `_get_or_create_subagent()` — caches subagents by `(step_id, role)` for reuse within a step
     - `_cleanup_step()` — releases cached subagents when step completes
     - Passes `cognition`, `context_manager`, and `memory` to `subagent.run()`
     - Typed outcomes in all exit paths
  5. **`kernel/defaults/coder.py`** [REWRITE] — Production behavioral doctrine:
     - 10-rule doctrine (code don't meta-code, fallback ladder, safety first, diagnose before retry, verify before done, report faithfully, auth handling, output contract, minimum complexity, no scope creep)
     - Fallback ladder: write_code → check_registry → delegate_research
     - `delegate_research` tool with **HARD GATE** (blocked until `write_code` called at least once)
  6. **`kernel/defaults/researcher.py`** [REWRITE] — 4-phase protocol:
     - Phase protocol: SEARCHING → EXTRACTING → VERIFYING → DONE
     - Evidence contract (cannot exit without actionable findings or explicit "not found" report)
     - New tools: `read_file` (with pagination), `grep_codebase` (local pattern search)
     - URL content cache (session-scoped dedup via `_read_urls` set)
  7. **`kernel/defaults/communicator.py`** [UPGRADED] — File I/O + improved prompt:
     - New tools: `write_file`, `read_file`, `list_files`
     - Improved system prompt with 4 capability categories
- **Verified**: All imports pass, KernelState serialization roundtrip, ContextManager builds from both KernelState and Dict, secret scrubbing, convergence governor stall detection
- **Design decisions**:
  - tiktoken: optional dependency with graceful word-count fallback
  - Protocol: keep text-based (THOUGHT/TOOL/PARAMS) as default, added JSON fallback parser
  - Cognition: centralized (Kernel creates, passes down; subagent creates lightweight defaults for standalone use)
- **Status**: Fixed
- **OSS push**: Yes (all changes are generic framework improvements, no proprietary logic)

---

### [RESOLVE-008] Component audit + bug fixes: Researcher, Web Search, Coder, Browser
- **Date**: 2026-04-23
- **Triggered by**: Post-OODA-loop mesh startup dogfood run — need to harden all 4 execution components
- **Component**: `kernel/defaults/researcher.py`, `kernel/defaults/coder.py`, `kernel/defaults/communicator.py`, `execution/search.py`, `kernel/defaults/browser.py` [NEW]
- **Root causes found**:
  1. **`researcher._tool_read_url` called `search_client.read_url(url)` — method doesn't exist**. `InternetSearch` has `extract_content(url)` returning a full dict `{success, content, title, word_count}`, not `read_url()`. Every researcher attempt to read a URL was silently failing.
  2. **All tool methods missing `**kwargs`** — LLM occasionally passes extra parameters (e.g., `raw=True`, `encoding="utf-8"`) that crash the tool dispatch with `TypeError: unexpected keyword argument`. Proven in live run: `send_to_peer` crashed with `raw` kwarg.
  3. **`execution/search.py` SSL failure on macOS** — Python 3.9 on macOS Command Line Tools lacks certifi root certs. `aiohttp` connections to DuckDuckGo failed with `SSLCertVerificationError`. Added `ssl.create_default_context()` with certifi fallback and lenient mode.
  4. **Browser automation did not exist** — `settings.py` had `browser_enabled`, `browser_headless` flags but no implementation. The Kernel only knew 3 roles (coder, researcher, communicator).
- **Fixes**:
  - `researcher.py`: `read_url` → calls `extract_content()` and handles dict return correctly
  - `researcher.py`, `coder.py`, `communicator.py`: All tool methods now accept `**kwargs`
  - `search.py`: SSL context with certifi + lenient fallback via `aiohttp.TCPConnector`
  - `kernel/defaults/browser.py` [NEW]: `BrowserSubAgent` with 14 Playwright tools:
    - `navigate`, `click`, `type_text`, `get_text`, `get_attribute`
    - `screenshot`, `wait_for`, `evaluate`, `get_links`
    - `fill_form`, `select_option`, `scroll`, `get_cookies`, `close_page`
    - Graceful degradation when Playwright not installed (returns install instructions)
    - Browser lifecycle tied to `run()` — opens before OODA loop, closes in `finally`
  - `kernel/lease.py`: Added `browser` role profile (5-min wall clock, 20-turn fuse)
  - `kernel/kernel.py`: Added `_BROWSER_KEYWORDS`, classifier routes to `browser`, `_create_subagent` factory creates `BrowserSubAgent`
  - `kernel/subagent.py`: Added `_pre_run_hook()` / `_post_run_hook()` no-op stubs to `BaseSubAgent`
- **Verified**: 5-point import + classification test suite passes cleanly
  - All 4 subagents import without error
  - Task classifier routes correctly for all 4 roles
  - `extract_content()` exists, `read_url()` correctly absent (was a phantom API)
  - Lease profiles include `browser`
- **Status**: Fixed
- **OSS push**: Yes

---

### [ISSUE-006] Playwright not installed in dev environment
- **Discovered**: 2026-04-23
- **Severity**: Low (browser role disabled, not crash — graceful degradation works)
- **Component**: `kernel/defaults/browser.py`
- **Description**: `PLAYWRIGHT_AVAILABLE=False` because `playwright` not installed. Browser tasks will fail gracefully with an install message, not a crash.
- **Fix**: `pip install playwright && playwright install chromium`
- **Status**: Open — install separately when browser automation is needed

---

### [RESOLVE-009] Gemini Grounded Search + Trace Streaming + Chat SSE
- **Resolved**: 2026-04-23
- **Commit**: `e3d1693` (dogfood/internal-agents)
- **Severity**: Major — blocked production-quality web search + UI trace visibility
- **Components**: `execution/search.py`, `kernel/tracing.py` (new), `kernel/subagent.py`, `kernel/kernel.py`, `integrations/chat.py` (new), `config/settings.py`

#### Root Causes
1. **Search**: `InternetSearch` used only DuckDuckGo, which rate-limits aggressively and returns low-quality results. No fallback, no quality ranking.
2. **Traces**: OODA loop emitted zero structured events — agent reasoning, tool calls, and LLM latency were entirely invisible to the UI. Only the final `AgentOutput` made it out.
3. **Chat**: No HTTP endpoint existed to issue a task from the chat UI and receive a response. Agents could only be driven programmatically.

#### Fixes Applied

**1. Multi-provider InternetSearch (`execution/search.py` — full rewrite)**

Implements the CA's proven provider-ranking architecture (OSS-clean port):

| Provider | Weight | Auth | Notes |
|---|---|---|---|
| Google Grounded Search (Gemini) | **1.4** | `GEMINI_API_KEY` or Vertex AI | Primary — highest quality |
| Serper (Google Search API) | **1.2** | `SERPER_API_KEY` | Optional secondary |
| DuckDuckGo Lite | **1.0** | none | Always-on fallback |
| Wikipedia REST | **0.6** | none | Academic fallback |

- All 4 providers run in **parallel** (`asyncio.gather` with 6s timeout per provider)
- `CircuitBreaker` per provider: 5 failures → OPEN, 60s recovery → HALF_OPEN/CLOSED
- `_search_google_grounded()`: uses `genai.Client` in `asyncio.to_thread`, extracts `grounding_chunks` + `grounding_supports` as structured results, 3-retry on 429/503
- `_rank_results()`: keyword overlap bonus + PDF bonus + provider weight → sorted dedup list
- `extract_content()` + `search_and_extract()` unchanged

**2. TraceManager (`kernel/tracing.py` — new file)**

Real-time agent trace streaming for UI observability:
```
OODA loop → TraceManager.log_event()
               ├── Redis List   traces:{wf}:{step}   (7-day TTL, queryable)
               ├── Redis PubSub trace_events:{wf}     (real-time → SSE)
               └── File         traces/{mission}.jsonl (debug fallback)
```

Event types: `step_start`, `thinking`, `tool_start`, `tool_result`, `llm_request`, `llm_response`, `step_complete`

Secret scrubbing on all values. `_NoOpTrace` provides zero-overhead fallback when Redis is absent.

**3. OODA loop wiring (`kernel/subagent.py`)**

`run(trace=None)` — `TraceManager` injected by Kernel, `_NoOpTrace` by default:
- `log_llm_request()` — before LLM call
- `log_llm_response()` — after LLM returns (with latency_ms)
- `log_thinking()` — on every **THOUGHT** block parsed
- `log_tool_start()` — before tool dispatch
- `log_tool_result()` — after tool returns (success + error)
- `log_step_complete()` — on DONE, convergence stall, LLM failure, and turn fuse

**4. Kernel wiring (`kernel/kernel.py`)**

`TraceManager(workflow_id, step_id)` created at top of `execute()`, before dispatch loop. Passed as `trace=_kernel_trace` to `subagent.run()`. Falls back to `_NoOpTrace` on any init error (non-fatal).

**5. Chat + SSE endpoints (`integrations/chat.py` — new file)**

```
POST /chat
  Body: {message, workflow_id?, agent_id?, system_prompt?, context?}
  Auto-routes: research/browse/code/communicate via Kernel classifier
  Returns: {workflow_id, step_id, status, answer, sources, tokens, elapsed_ms}

GET /chat/stream/{workflow_id}
  Content-Type: text/event-stream (SSE)
  - Catch-up replay of all buffered events on connect
  - Non-blocking Redis PubSub poll (100ms interval)
  - Heartbeat keep-alive comments (:)
  - Auto-close on step_complete event or client disconnect

GET /chat/history/{workflow_id}/{step_id}
  Returns full event log for replay (Redis → file fallback)
```

Example client wiring:
```js
const es = new EventSource(`/chat/stream/${workflowId}`)
es.onmessage = (e) => {
    const evt = JSON.parse(e.data)
    if (evt.type === 'thinking')     renderThought(evt.data.thought)
    if (evt.type === 'tool_start')   renderToolCall(evt.data)
    if (evt.type === 'tool_result')  renderToolResult(evt.data)
    if (evt.type === 'step_complete') { renderAnswer(evt.data.summary); es.close() }
}
```

**6. Settings (`config/settings.py`)**

New env vars: `GEMINI_API_KEY`, `GEMINI_GROUNDING_API_KEY`, `GEMINI_GROUNDING_MODEL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `SERPER_API_KEY`

#### Verification
All import/structural checks passed (`python3 -c "..."` suite — 5 components, all ✅):
- CircuitBreaker open/close logic
- _NoOpTrace no-crash guarantee
- `run(trace=)` param present on BaseSubAgent
- `create_chat_router` exported from integrations package
- Gemini + Serper settings present in Settings

#### Required Env Vars
```env
# Primary search (at least one)
GEMINI_API_KEY=your-gemini-api-key          # OR use GOOGLE_CLOUD_PROJECT for Vertex AI
GEMINI_GROUNDING_API_KEY=...                # wins over GEMINI_API_KEY for search

# Secondary search (optional but recommended)
SERPER_API_KEY=your-serper-dev-key

# Required for live traces
REDIS_URL=redis://localhost:6379
```

- **Status**: ✅ Resolved

---

### [RESOLVE-010] Canonical Pydantic contracts — replaced loose dicts across all data boundaries
- **Date**: 2026-04-23
- **Commits**: `7ecaf21` (jarviscore-framework)
- **Severity**: Major — tasks/meetings/HITL crossed system boundaries as raw dicts with no validation
- **Components**: `jarviscore/contracts/` (new package), `jarviscore/kernel/hitl.py`, `jarviscore/storage/redis_store.py`, `prescott-internal-agents/dashboard/app.py`

#### Contracts added

| File | Models |
|---|---|
| `contracts/meeting_note.py` | `MeetingNote`, `MeetingNoteCreate`, `DiscussionEntry`, `ActionItem`, `MeetingType`, `normalise_meeting()` |
| `contracts/task.py` | `Task`, `TaskCreate`, `TaskUpdate`, `TaskStatus`, `TaskPriority` |
| `contracts/hitl.py` | `HITLRequest`, `HITLResolution`, `HITLPolicy`, `HITLDecision`, `HITLStatus`, `normalize_hitl_decision()` |

#### Key fixes
- `HumanTask = HITLRequest` alias: backward-compat for all existing kernel code
- `create_hitl_request_typed()` / `get_hitl_resolution()` in `RedisContextStore`: typed reads/writes instead of raw dicts
- `dashboard/app.py`: `_normalise_meeting()` delegates to `_contract_normalise_meeting()` (fixed name collision bug that caused recursive crash — see ISSUE-007 below)
- **Verified**: 10/10 contract checks pass (instantiation, alias, enum defaults, Redis mapping, decision normalization, is_approved/is_rejected)

#### ISSUE found during this work
- `_normalise_meeting` imported as `_normalise_meeting` then a local function of the same name shadowed it → infinite recursion → all meetings disappeared from dashboard. Fixed by renaming import alias to `_contract_normalise_meeting`.

- **Status**: ✅ Resolved

---

### [RESOLVE-011] Meeting notes — proper glassmorphism overlay modal
- **Date**: 2026-04-23
- **Commits**: `942ef5d` (prescott-internal-agents)
- **Severity**: UX — "View Full Meeting Notes" injected a card below the list; no backdrop, required scrolling, looked broken
- **Component**: `dashboard/static/index.html`

#### Fix
- Replaced DOM-injection pattern with `#meeting-notes-modal` using same `glass-modal-overlay` system as the Create Task modal
- `showMeeting()` rewritten: opens overlay → fetches → renders sections: participants (avatar chips), agenda, summary, full markdown report, discussion log (grid layout), resolutions (dot rows), action items (owner/task/deadline grid)
- Closes on ✕ button, backdrop click, or Escape key
- No garish inline colors — subtle accent dots only, monochrome palette
- All `mn-*` CSS classes added for modal-specific layout

- **Status**: ✅ Resolved

---

### [RESOLVE-012] Athena MemOS integration into jarviscore.memory
- **Date**: 2026-04-23
- **Commits**: `2a33c7c` (jarviscore-framework)
- **Severity**: Enhancement — agents had no persistent episodic/LTM memory beyond per-workflow Redis streams
- **Components**: `jarviscore/memory/` (extended), `jarviscore/config/settings.py`, `jarviscore/cli/memory.py` (new)

#### Architecture decision
Athena goes in **core** (same layer as Nexus, not a separate ext package) because it calls an HTTP service — `httpx` is already a hard dep. Zero new Python dependencies.

#### What was built

| File | Purpose |
|---|---|
| `memory/athena_client.py` | Async HTTP wrapper for Athena REST API: `create_session`, `get_or_create_session`, `store_event`, `get_context`, `search_memory`, `get_heat_metrics`, `health_check` |
| `memory/athena_memory.py` | `AthenaMemory` per-agent bridge: session lifecycle, typed event writes, domain events (`on_task_assigned`, `on_task_completed`, `on_meeting_noted`, `on_hitl_resolved`, `on_task_deleted`) |
| `memory/__init__.py` | Exports `AthenaClient`, `AthenaMemory`, `get_athena_client()` factory |
| `config/settings.py` | `ATHENA_URL`, `ATHENA_TENANT_ID`, `ATHENA_HTTP_TIMEOUT` |
| `cli/memory.py` | `status` · `context --agent` · `search --agent --query` · `up` subcommands |
| `pyproject.toml` | `[memory-athena]` optional extra documented (zero actual new deps) |

#### Activation
```env
ATHENA_URL=http://localhost:8080   # set to enable; graceful no-op if absent
```

#### Feedback items for Athena team (dogfooding)
- REST API response shape for `GET /context` needs to be documented — field names differ from proto (`events` vs `stmEvents`, `chains` vs `mtmChains`). Client normalises both.
- `GET /health` dependency map keys should be standardised (`ok`/`healthy`/`pass`/`UP` all observed across services).
- Session creation should accept `agent_id` as a first-class field (not just metadata) for easier lookup.

- **Status**: ✅ Resolved — dogfooding started, feedback items logged above

---

### [RESOLVE-013] Delete endpoints + UI for meetings, tasks, and warden items
- **Date**: 2026-04-23
- **Commits**: `b3024df` (prescott-internal-agents)
- **Severity**: Major — no way to remove stale data; tasks survived in agent queues after being discarded
- **Component**: `dashboard/app.py`, `dashboard/static/index.html`

#### Endpoints added

| Endpoint | Storage purged |
|---|---|
| `DELETE /api/meetings/{id}` | File + `meeting:{id}` Redis key + pub event |
| `DELETE /api/tasks/{id}` | File + agent queue file + `task:{id}` Redis hash + `lrem tasks:{assignee}` list + `channel:tasks:{assignee}` pub so **online agents immediately drop the task** |
| `DELETE /api/warden/{id}` | File + `warden:{id}` Redis key + pub event |

#### UI
- Meeting timeline: trash icon on each card (hover turns red, optimistic fade → DOM remove)
- Task cards: `deleteTask()` already wired to task board

- **Status**: ✅ Resolved

---

### [RESOLVE-014] Sky Team agents upgraded to goal-oriented autonomous execution
- **Date**: 2026-04-24
- **Components**:
  - `prescott-internal-agents/agents/signal.py`
  - `prescott-internal-agents/agents/treasury.py`
- **Root cause**: All Sky Team agents called `execute_task()` with kitchen-sink task strings — 4-6 numbered sub-tasks jammed into a single OODA loop. If sub-task 3 of 5 failed (e.g., wrong JSON format, write_file error), sub-tasks 4-5 silently never executed. No verification, no replanning, no retry. The Planner, Evaluator, and TruthContext built in previous sessions were not being used.

#### Problem (Compass shift kickoff — before)
```python
# One OODA loop tries to: read blockers → read 5 queues → write meeting JSON
# → write 5 task files → return summary. Fails at step 3? Steps 4-5 never run.
await self.execute_task({
    "task": "1. Read blockers.md. 2. Read task queues. 3. Write meeting JSON. 4. Write task files. 5. Return."
})
```

#### Fix — two changes per goal-oriented agent

**1. `goal_oriented = True`** → routes all `execute_task()` calls through Plan-Execute-Evaluate. Planner decomposes goal → ExecEngine runs each step → StepEvaluator verifies → Replanner fires on failure.

**2. Task strings rewritten: numbered instructions → clean goal statements.** Goal states the outcome. Planner creates the step sequence. `context` dict carries structured planning state instead of being embedded in the prompt string.

```python
# After (Compass shift kickoff)
await self.execute_task({
    "task": f"Run the Sky Team shift kickoff for {now.strftime('%A, %B %d, %Y')}.\n\nSHIFT BRIEF:\n{brief_text}",
    "type": "shift_orientation",
    "context": {
        "agents": ["sentinel", "quill", "warden", "outpost", "envoy"],
        "meeting_id": f"signal-kickoff-{now.date()}",
        "meetings_dir": "meetings/",
        "tasks_dir": "tasks/",
        "blockers_file": "knowledge/ops/blockers.md",
    },
})
```

#### Agents upgraded

| Agent | Team | goal_oriented | Rationale |
|---|---|---|---|
| Compass | Signal | ✅ | Shift kickoff, standup, scrum, EOD review, calendar audit — all multi-step |
| Quill | Signal | ✅ | Draft = read brief → write → revise → save |
| Warden | Signal | ✅ | QA = read item → apply 7 checks → verdict → escalate |
| Dispatch | Signal | ✅ | Distribution = format per channel → attempt API → stage if blocked |
| Sentinel | Signal | ✅ | Intel scan = min 5 searches → synthesize → write report → update wikis |
| Outpost | Signal | ✅ | Outreach = research target → find hook → draft → Warden gate |
| Envoy | Signal | ✅ | IR materials = gather financials → verify claims → draft → flag for sign-off |
| Runway | Treasury | ✅ | Burn analysis = read Ledger+Kodi → model → scenarios → alerts |
| Folio | Treasury | ✅ | Reports = compile from 4 upstream agents → P&L → cash flow → balance sheet → briefing |
| Vault | Treasury | ✅ | Fundraising = research investors → score → model scenarios → audit data room |
| Ingram | Treasury | ○ single-shot | Atomic: given a file, parse it. No multi-step needed. |
| Tally | Treasury | ○ single-shot | Atomic: given transactions, classify them. |
| Ledger | Treasury | ○ single-shot | Atomic: given 2 account sets, reconcile them. |
| Kodi | Treasury | ○ single-shot | Atomic: given financials, compute tax obligations. |

#### Verification
```
✅ goal_oriented  Compass   ✅ goal_oriented  Quill    ✅ goal_oriented  Warden
✅ goal_oriented  Dispatch  ✅ goal_oriented  Sentinel ✅ goal_oriented  Outpost  ✅ goal_oriented  Envoy
✅ goal_oriented  Runway    ✅ goal_oriented  Folio    ✅ goal_oriented  Vault
○  single-shot   Ingram    ○  single-shot   Tally    ○  single-shot   Ledger   ○  single-shot   Kodi
All agents imported successfully.
```

- **Status**: ✅ Resolved
