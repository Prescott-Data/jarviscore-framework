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

