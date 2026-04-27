"""
Researcher Sub-Agent ("The Scout")

Specializes in gathering information, understanding APIs, and reading documentation.
It ensures the Coder Agent has all necessary context before writing a single line of code.

Browser Automation:
Uses ref-based browser control (ported from OpenClaw architecture) for dynamic web pages:
1. Navigate to page with `browser_navigate`
2. Get accessibility snapshot with `browser_snapshot`
3. Interact using refs (e.g., "e1", "e2") with `browser_click`, `browser_type`

Ported from integration-agent-javiscore to jarviscore-framework.
All IA-specific imports replaced with jarviscore equivalents.
"""

import asyncio
import fnmatch
import logging
import json
import glob
import os
import re
import requests
import subprocess
from typing import Dict, Any, List, Optional, Literal, cast, Set, Tuple
from urllib.parse import urlparse

from jarviscore.kernel.subagent import BaseSubAgent
from jarviscore.kernel.state import KernelState
from jarviscore.kernel.defaults.research_flow import ResearchFlow, ResearchPhase
from jarviscore.kernel.cognition import AgentPhase
from jarviscore.search.internet_search import InternetSearch

# Optional deps — graceful degradation without [browser] or [rag] extras
_HAS_BROWSER = False
try:
    from jarviscore.browser.controller import BrowserConfig
    from jarviscore.browser.dispatcher import BrowserDispatcher
    from jarviscore.browser.profiles import BrowserProfileRegistry, BrowserProfile
    _HAS_BROWSER = True
except ImportError:
    BrowserConfig = None  # type: ignore[assignment,misc]
    BrowserDispatcher = None  # type: ignore[assignment,misc]
    BrowserProfileRegistry = None  # type: ignore[assignment,misc]
    BrowserProfile = None  # type: ignore[assignment,misc]

_HAS_RAG = False
try:
    from jarviscore.rag.pipeline import RagPipeline
    _HAS_RAG = True
except ImportError:
    RagPipeline = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ── Env-var helpers (replace IA settings singleton) ──
def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)

def _env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default

def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

def _env_float(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default



class _NoOpTracer:
    """Silent tracer that absorbs all telemetry calls when no real tracer is injected."""
    def log_event(self, *args, **kwargs): pass
    def log_tool_start(self, *args, **kwargs): pass
    def log_tool_result(self, *args, **kwargs): pass
    def log_error(self, *args, **kwargs): pass
    def __getattr__(self, name):
        return lambda *a, **kw: None


class ResearcherSubAgent(BaseSubAgent):
    """
    The Scout.
    
    Responsibilities:
    1. Search the internet for API documentation.
    2. Read local documentation files (PRIORITY).
    3. Extract parameter schemas and endpoint details.
    4. Browse dynamic documentation sites using ref-based browser automation.
    """
    
    def __init__(self, *args, **kwargs):
        # Accept optional internet_search injection (e.g. for testing)
        internet_search = kwargs.pop('internet_search', None)
        self.internet_search = internet_search or InternetSearch(
            pdf_timeout_seconds=_env_int("RESEARCH_PDF_TIMEOUT_SECONDS", 90),
            pdf_max_retries=_env_int("RESEARCH_PDF_MAX_RETRIES", 3),
        )
        
        # Browser controller config — graceful degradation if [browser] not installed
        browser_headless = kwargs.pop("browser_headless", _env_bool("BROWSER_HEADLESS", True))
        launch_args = [
            arg.strip() for arg in _env_str("BROWSER_LAUNCH_ARGS", "").split(",") if arg.strip()
        ]
        
        cdp_url = _env_str("BROWSER_CONTROL_URL") or _env_str("BROWSER_SERVICE_URL")
        
        import uuid
        session_id = str(uuid.uuid4())[:8]
        unique_profile_dir = os.path.join(
            _env_str("BROWSER_PROFILE_USER_DATA_BASE", os.path.join(os.path.expanduser("~"), ".jarviscore", "browser_profiles")),
            f"{_env_str('BROWSER_DEFAULT_PROFILE', 'default')}_{session_id}",
            "user-data",
        ) if not cdp_url else None
        
        self._browser_profile_name = f"researcher_{session_id}"
        if _HAS_BROWSER and BrowserConfig is not None:
            step_timeout = _env_float("STEP_EXECUTION_TIMEOUT", 0)
            self._browser_config = BrowserConfig(
                headless=browser_headless,
                timeout_ms=int(step_timeout * 1000) if step_timeout else 30000,
                profile_name=self._browser_profile_name if not cdp_url else None,
                user_data_dir=unique_profile_dir,
                launch_args=launch_args,
                user_agent=_env_str("BROWSER_USER_AGENT", ""),
                ignore_https_errors=_env_bool("BROWSER_IGNORE_HTTPS_ERRORS", True),
                stealth_enabled=_env_bool("BROWSER_STEALTH_ENABLED", False),
                cdp_url=cdp_url,
            )
        else:
            self._browser_config = None
        self._dispatcher = None
        self._rag_pipeline = None

        # Within-session URL content cache — prevents redundant HTTP round-trips
        self._url_content_cache: Dict[str, str] = {}

        # If no 'role' in args/kwargs, inject the default
        if not args and 'role' not in kwargs:
            kwargs['role'] = 'researcher'

        super().__init__(*args, **kwargs)

        # Ensure tracer exists (IA tools use self.tracer pervasively)
        if not hasattr(self, 'tracer') or self.tracer is None:
            self.tracer = _NoOpTracer()

        # Ensure current_state exists (tools check self.current_state)
        if not hasattr(self, 'current_state'):
            self.current_state = None

    def setup_tools(self) -> None:
        """Register all researcher tools. Called by BaseSubAgent.__init__."""
        # --- DOC ACQUISITION (ONLINE-FIRST) ---
        self.register_tool(
            "read_file",
            self._tool_read_file,
            (
                "Read a local file. Supports pagination for large files: pass offset and limit "
                "to read in pages. Returns total_chars, has_more, next_offset."
            ),
            phase=AgentPhase.DISCOVERY
        )
        # --- INTERNET SEARCH (parallel-friendly) ---
        self.register_tool(
            "search_internet",
            self._tool_search_internet,
            (
                "Search the web for API docs, libraries, or solutions. "
                "Args: query, preferred_domains (optional list like ['docs.example.com'] "
                "to bias search toward official documentation sites)."
            ),
            phase=AgentPhase.DISCOVERY
        )
        self.register_tool(
            "search_internet_batch",
            self._tool_search_internet_batch,
            (
                "Run multiple searches in parallel. Pass a list of queries; returns combined "
                "results per query (faster than N separate calls). "
                "Args: queries, max_results_per_query, preferred_domains (optional)."
            ),
            phase=AgentPhase.DISCOVERY
        )
        # --- SMART INGESTION (High-Tech Controller) ---
        self.register_tool(
            "read_web_content",
            self._tool_read_web_content,
            (
                "Smartly read documentation from a list of URLs. Automatically optimizes strategy "
                "(Fast Fetch -> Auto-Escalate to Browser if needed). Returns unified content. "
                "CACHE: Within-session URL cache is active — re-fetching a URL already read in "
                "this session returns cached content, not live data. Avoid duplicate fetches. "
                "PREFERENCE: Always use this tool for web content. Never attempt HTTP requests "
                "via other means."
            ),
            phase=AgentPhase.DISCOVERY
        )
        self.register_tool(
            "rag_query",
            self._tool_rag_query,
            "Query local RAG index for evidence-backed results.",
            phase=AgentPhase.DISCOVERY,
        )
        
        # --- BROWSER INTERACTION (Manual Override) ---
        # Only register browser tools if [browser] extra is installed
        if _HAS_BROWSER:
            self.register_tool(
                "browser_navigate",
                self._tool_browser_navigate,
                "Open browser session for MANUAL interaction (Login, Search, Click). Use ONLY if `read_web_content` isn't enough.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_snapshot",
                self._tool_browser_snapshot,
                "Get accessibility snapshot of current page. Returns refs (e1, e2...) for interactive elements.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "ui_snapshot_with_som",
                self._tool_ui_snapshot_with_som,
                "Capture and persist a SoM snapshot for robust UI interaction refs.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_click",
                self._tool_browser_click,
                "Click element by ref (e.g., 'e1'). Requires prior browser_snapshot.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_type",
                self._tool_browser_type,
                "Type text into input by ref. Args: ref, text, submit=False.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_click_coord",
                self._tool_browser_click_coord,
                "Coordinate fallback click. Use ONLY when SoM refs are unavailable.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_type_coord",
                self._tool_browser_type_coord,
                "Coordinate fallback type. Use ONLY when SoM refs are unavailable.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_get_page_text",
                self._tool_browser_get_page_text,
                "Extract ALL visible text from the current page as markdown. Use immediately after browser_navigate to read documentation content. No ref needed — faster and more complete than browser_get_text(ref).",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_get_text",
                self._tool_browser_get_text,
                "Get text content of a single element by ref. Use browser_get_page_text() instead when you want all page content.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_wait",
                self._tool_browser_wait,
                "Wait for condition. Args: text=str, time_ms=int, load_state='networkidle'.",
                phase=AgentPhase.DISCOVERY
            )
            self.register_tool(
                "browser_close",
                self._tool_browser_close,
                "Close browser session. Call when done browsing.",
                phase=AgentPhase.DISCOVERY
            )
        
        # --- LIVE TARGET SYSTEM DISCOVERY ---
        self.register_tool(
            "probe_target_api",
            self._tool_probe_target_api,
            (
                "Probe a live system's standard self-describing endpoints (FHIR /metadata, "
                "OData /$metadata, OpenAPI /openapi.json, Swagger /swagger.json, "
                "HATEOAS / or /api). Returns ground-truth API capabilities from the "
                "running system — no documentation needed. "
                "NOTE: The system already ran this automatically before your first turn. "
                "Only call this if you discover a NEW or MORE SPECIFIC base_url during "
                "research that has not been probed yet (e.g. a sub-path URL found in docs)."
            ),
            phase=AgentPhase.DISCOVERY
        )

        # --- CODEBASE SEARCH ---
        self.register_tool(
            "grep_codebase",
            self._tool_grep_codebase,
            (
                "Deterministic text/regex search of the local codebase using ripgrep "
                "(falls back to Python re if rg is unavailable). "
                "WHEN TO USE: Prefer this over `rag_query` when you know the exact string, "
                "symbol, or import pattern you are looking for — grep is precise, rag_query "
                "is semantic. Use `read_file` to read a specific known file; use this to find "
                "WHERE something exists across multiple files. "
                "Args: pattern, path (default '.'), file_glob (default '*.py'), "
                "max_results (default 50), context_lines (default 2)."
            ),
            phase=AgentPhase.DISCOVERY,
        )

        # --- SCHEMA EXTRACTION ---
        self.register_tool(
            "extract_api_details",
            self._tool_extract_api_details,
            (
                "Extract structured API specs (endpoints, body_schema, query_params, response_fields) "
                "from raw documentation text. Call this immediately after browser_get_page_text or "
                "read_web_content to turn unstructured doc content into structured api_specs. "
                "Results are automatically persisted to your api_specs — no manual copy needed. "
                "ANTI-PATTERN: Do NOT call `search_internet` for endpoint discovery if the "
                "LIVE API CAPABILITIES block is already present in your context — those endpoints "
                "are pre-loaded ground truth and searching the web will return stale or incorrect data."
            ),
            phase=AgentPhase.DISCOVERY,
        )

        # --- COMPLETION ---
        self.register_tool(
            "publish_research_findings",
            self._tool_publish_research_findings,
            "Complete research and return findings. Args: api_specs, libraries, evidence, summary.",
            phase=AgentPhase.COMPLETION
        )


    def get_system_prompt(self) -> str:
        prompt = """You are the RESEARCHER AGENT (The Scout).
Your goal is to gather ACCURATE, EVIDENCE-BACKED technical information.
You do NOT guess. You do NOT hallucinate. If you cannot find it, you report "Not Found".

**CRITICAL RULES (VIOLATING THESE = FAILURE):**

1. **NEVER FABRICATE URLS** - Use ONLY the exact URLs returned by `search_internet_batch`. Do NOT modify, construct, or guess URLs. If you need a different page, search for it.

2. **USE SNIPPETS FIRST** - Search results include snippets with useful content. Often the snippet alone answers your question. Only fetch the full page if you need more detail.

3. **NO BROWSER UNLESS ABSOLUTELY NECESSARY** - Browser is EXPENSIVE and SLOW. Use it ONLY for:
   - Sites that require login/authentication
   - SPAs that return blank content via HTTP
   - Interactive navigation (clicking through menus)
   - NEVER use browser just because HTTP returned a 404 (that means the URL doesn't exist)

4. **LAW OF FINITE ATTENTION (TIME LIMIT)**:
   - Do NOT research for more than 15 minutes or ~5 turns per step.
   - **PERFECTION IS THE ENEMY OF DONE.** If you find a schema that is "80% correct" or "close enough", USE IT.
   - If you are on the right page but cannot find the exact JSON, **EXTRACT THE TEXT ANYWAY** (use `browser_get_text` or `read_web_content`) and pass it to the Coder. The Coder can infer missing fields.
   - **DO NOT DISCARD** pages that look relevant just because they are messy.

**THE "HIGH-TECH" PROTOCOL (Map-Reduce):**

0. **PHASE 0: LIVE API CAPABILITIES (Pre-Loaded — Check Context First)**
   - The system has ALREADY probed the target API before this conversation started.
   - Look for the **"LIVE API CAPABILITIES (Ground Truth — Pre-Loaded)"** block at the
     top of your context. It contains everything the live system supports, including
     every resource, endpoint, and search parameter.
   - **If that block is present:**
     - Use its endpoints DIRECTLY. These are ground truth from the live system.
     - Do NOT search the internet for endpoint discovery — the live system is more
       authoritative than any documentation.
     - Proceed to PHASE 4 (Synthesis) immediately.
   - **If that block is absent** (system did not expose standard API discovery paths):
     - Call `probe_target_api(base_url=<new_url>)` ONLY if you discover a different
       or more specific base URL during research that hasn't been probed yet.
     - Otherwise proceed to PHASE 1 (internet search).

1. **PHASE 1: RECONNAISSANCE (Map)**
   - Use `search_internet_batch` to fire parallel queries.
   - *Queries must be specific:* e.g., ["Stripe REST API authentication", "Salesforce create customer endpoint", "Shopify API swagger"].
   - *Goal:* Find the **Official API Documentation** or **Swagger/OpenAPI Spec**.
   - *Anti-Goal:* Do NOT waste time on "Architecture Overviews", "Marketing Pages", or "High-level summaries". We need **endpoints**, **payloads**, and **headers**.
   - **READ THE SNIPPETS** - They often contain exactly what you need!

2. **PHASE 2: INGESTION (Filter & Read)**
   - **COPY-PASTE URLs** - Use `read_web_content(urls=[...])` with the EXACT URLs from search results.
   - Prefer `read_web_content(url_ids=[...])` using keys from `search_internet_batch.url_registry`.
   - **FAST PATH:** This tool performs "Search -> Visit -> Extract Markdown". It uses High-Tech extraction.
   - If HTTP returns "Page Not Found", the page DOES NOT EXIST. Do NOT try browser. Search for a different page instead.
   - If local evidence exists, use `rag_query` to retrieve vetted passages.

3. **PHASE 3: INTERACTIVE DEEP DIVE (Manual Override)**
   - **LAST RESORT ONLY** - Use browser only if:
     a) `read_web_content` returns "SPA Detected" with empty content, OR
     b) You need to login to access content, OR
     c) You need to click through navigation to find the right page
   - Use `browser_navigate` -> `browser_get_page_text` to read content from any page in ONE step.
   - `browser_get_page_text` extracts ALL visible text as markdown — no ref needed, no snapshot required.
   - Only use `browser_snapshot` -> `browser_click` when you need to interact with the page (click a menu, navigate pagination, log in).
   - **CRITICAL:** After navigation, call `browser_get_page_text` FIRST to extract the content. Then call `extract_api_details(text=...)` on the result.

4. **PHASE 4: SYNTHESIS (Reduce)**
   - Compile your findings for endpoints, payloads, and schemas.
   - Nexus handles authentication; do not infer or specify auth types.
   - Provide evidence pointers (doc URLs or code references) for any API spec.

**EVALUATION LOOP (The "OODA" of Research):**
1. **Observe:** Read the content returned by `read_web_content`.
2. **Orient:** Does this page contain the *specific* API endpoints or schemas I need?
   - If YES -> Extract them, add to findings, and move to Synthesis.
   - If PARTIAL -> **KEEP IT.** Extract what is useful. Do NOT discard.
   - If NO -> Discard and try next URL.
3. **Decide:** If you have enough to write *some* code, STOP. Call `publish_research_findings`.
4. **Act:** Call `publish_research_findings` or next search.

**BROWSER AUTOMATION (ref-based):**
- Each `browser_snapshot()` returns a tree where interactive elements have refs like [ref=e1]
- Use these refs to click buttons, type in inputs, etc.
- ALWAYS call `browser_snapshot()` after navigation to get fresh refs
- Call `browser_close()` when done browsing

**LARGE FILE READING (Pagination):**
- `read_file` returns `total_chars`, `has_more`, and `next_offset` on every call.
- If `has_more` is `true`, the file was truncated. Call `read_file` again with `offset=next_offset` to read the next page.
- Keep paging until `has_more` is `false` or you have the information you need.
- Example: `read_file(file_path="spec.yaml")` → `{has_more: true, next_offset: 8000}` → `read_file(file_path="spec.yaml", offset=8000)` → and so on.

**CODEBASE SEARCH:**
- Use `grep_codebase(pattern="...", path=".", file_glob="*.py")` for deterministic text or regex search.
- Faster and more precise than `rag_query` when you know the exact symbol, function name, or string to find.
- Use in VERIFYING phase to confirm an existing implementation before suggesting changes.

**SCHEMA EXTRACTION (CRITICAL — applies to ALL methods):**
- After reading a documentation page, call `extract_api_details(text=...)` with the raw page content.
- `extract_api_details` automatically adds results to your api_specs — you do not need to copy them manually.
- Every method has schema information the Coder CANNOT guess from the URL alone:
  - GET  → `query_params` (e.g. ?v=full, ?q=, ?limit=, ?startIndex=). Without these the Coder gets bare records or misses pagination entirely.
  - POST/PUT/PATCH → `body_schema` (request body field names + types). Without these the Coder guesses field names and hits format_error failures.
  - ALL  → `response_fields` (UUIDs, display names, status fields) that downstream steps depend on.
- An endpoint spec without its schema context is incomplete. Do not call `publish_research_findings` until you have extracted schemas for every endpoint you found.

**OUTPUT FORMAT (The "publish_research_findings" tool):**
When you call 'publish_research_findings', your output MUST be a JSON object containing:
- `api_specs`: List of endpoints. Each entry: {method, url/path, query_params (GET), body_schema (POST/PUT/PATCH), required_fields, response_fields, summary}.
- `libraries`: Recommended Python libraries.
- `evidence`: List of evidence objects {kind, pointer, quote(optional), confidence(optional)}.
- `summary`: One paragraph summary for the Coder including the base path prefix and any auth notes.

CRITICAL EPISTEMIC CONTRACT: You CANNOT exit your turn by saying "I need to research this." You ARE the Researcher. If you don't have the answer, you must use your search and read tools until you find it, and then call `publish_research_findings`. If you truly cannot find it after exhaustive searching, you must explicitly document that it does not exist.
"""
        if self.current_state and self.current_state.internal_variables.get("system_wisdom"):
            prompt += f"\n\n{self.current_state.internal_variables.get('system_wisdom')}"

        return prompt

    def get_role_description(self) -> str:
        return "Find API specifications, documentation, and libraries for the assigned task."

    def _set_research_phase(self, phase: ResearchPhase, reason: str) -> None:
        if self.current_state:
            self.current_state.internal_variables["research_flow"] = ResearchFlow.snapshot(phase, reason)
        try:
            self.tracer.log_event("research_phase", {"phase": phase.value, "reason": reason})
        except Exception:
            pass

    # _env_bool: using module-level _env_bool() instead

    def _current_research_phase(self) -> ResearchPhase:
        if not self.current_state:
            return ResearchPhase.INIT
        raw = self.current_state.internal_variables.get("research_flow", {})
        if isinstance(raw, dict):
            phase = str(raw.get("phase", "")).lower().strip()
            for p in ResearchPhase:
                if p.value == phase:
                    return p
        return ResearchPhase.INIT

    def _allowed_tools_for_phase(self, phase: ResearchPhase) -> Set[str]:
        """Tools allowed in each research phase."""
        shared_ui = {
            "browser_navigate", "browser_snapshot", "ui_snapshot_with_som",
            "browser_click", "browser_type", "browser_click_coord",
            "browser_type_coord", "browser_get_text", "browser_get_page_text",
            "browser_wait", "browser_close",
        }
        mapping: Dict[ResearchPhase, Set[str]] = {
            ResearchPhase.INIT: {"search_internet", "search_internet_batch", "read_file", "read_web_content", "rag_query", "grep_codebase", "extract_api_details", "probe_target_api"},
            ResearchPhase.SEARCHING: {"search_internet", "search_internet_batch", "read_web_content", "rag_query", "grep_codebase", "extract_api_details", "probe_target_api", "publish_research_findings"},
            ResearchPhase.EXTRACTING: {"read_web_content", "rag_query", "extract_api_details", "publish_research_findings"} | shared_ui,
            ResearchPhase.VERIFYING: {"search_internet", "search_internet_batch", "read_web_content", "rag_query", "extract_api_details", "grep_codebase", "probe_target_api", "publish_research_findings", "read_file"} | shared_ui,
            ResearchPhase.DIAGNOSING: {"search_internet", "search_internet_batch", "read_web_content", "rag_query", "grep_codebase", "extract_api_details", "probe_target_api", "publish_research_findings"} | shared_ui,
            ResearchPhase.STUCK: {"publish_research_findings"},
            ResearchPhase.DONE: {"publish_research_findings"},
        }
        return mapping.get(phase, set())

    def _check_phase_tool_contract(self, tool_name: str) -> Optional[str]:
        """Check if a tool is allowed in the current research phase."""
        if not _env_bool("RESEARCH_STRICT_PHASE_CONTRACT", True):
            return None
        if tool_name == "done":
            return ("EPISTEMIC CONTRACT VIOLATION: The 'done' tool has been removed. "
                    "You MUST use 'publish_research_findings' to exit your turn.")
        if tool_name == "error":
            return None
        phase = self._current_research_phase()
        allowed = self._allowed_tools_for_phase(phase)
        if tool_name not in allowed:
            return (
                f"PHASE_TOOL_CONTRACT_VIOLATION: tool '{tool_name}' is not allowed "
                f"in phase '{phase.value}'. Allowed tools: {sorted(list(allowed))}"
            )
        return None

    async def _act(self, state, decision: Dict[str, Any], cognition):
        tool_name = decision.get("tool") or "unknown"
        violation = self._check_phase_tool_contract(str(tool_name))
        if violation:
            params = decision.get("parameters", {}) if isinstance(decision, dict) else {}
            state.add_thought(f"[RESEARCH_CONTRACT] {violation}")
            state.add_tool_result(str(tool_name), params, None, violation)
            self.tracer.log_tool_start(str(tool_name), params)
            self.tracer.log_tool_result(str(tool_name), None, violation)
            return
        await super()._act(state, decision, cognition)

    def _can_complete(self, state, params: Dict[str, Any]) -> Tuple[bool, str]:
        base_ok, base_reason = super()._can_complete(state, params)
        if not base_ok:
            return base_ok, base_reason
        meaningful_research = any(
            t.status == "success" and t.tool_name in {"read_web_content", "browser_get_text", "browser_get_page_text", "rag_query", "read_file", "extract_api_details"}
            for t in state.tool_history
        )
        if not meaningful_research and not (params and (params.get("evidence") or params.get("summary"))):
            return False, "Research completion requires at least one successful content/evidence tool result"
        valid, reason, _ = self._validate_done_payload(state, params)
        if not valid:
            return False, reason
        return True, ""

    def _validate_done_payload(self, state, params: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        strict = _env_bool("RESEARCH_STRICT_DONE_VALIDATION", True)
        summary = str(params.get("summary") or "").strip()
        evidence = params.get("evidence")
        api_specs = params.get("api_specs") or []
        findings = state.internal_variables.get("research_findings", []) if getattr(state, "internal_variables", None) else []
        has_finding_fallback = isinstance(findings, list) and len(findings) > 0

        evidence_count = 0
        bad_evidence = 0
        if isinstance(evidence, list):
            for item in evidence:
                if not isinstance(item, dict):
                    bad_evidence += 1
                    continue
                pointer = item.get("pointer") or item.get("url")
                if pointer:
                    evidence_count += 1
                else:
                    bad_evidence += 1

        bad_specs = 0
        incomplete_specs: List[str] = []
        if isinstance(api_specs, list):
            for spec in api_specs:
                if not isinstance(spec, dict):
                    bad_specs += 1
                    continue
                method = str(spec.get("method") or "").strip().upper()
                url_or_path = str(spec.get("url") or spec.get("path") or spec.get("endpoint") or spec.get("url/path") or "").strip()
                if not method or not url_or_path:
                    bad_specs += 1
                    continue
                label = f"{method} {url_or_path}"
                # Every method has schema information the Coder needs:
                #   GET           → query_params (e.g. ?v=full, ?q=, ?limit=)
                #                   without these the Coder can't control representation
                #                   or filter results, and response fields are unknown
                #   POST/PUT/PATCH → body_schema (request body field names + types)
                #                   without these the Coder guesses field names → format_error
                #   DELETE        → path_params or body_schema if the API requires a body
                #                   usually implicit from the URL but worth flagging if absent
                if method == "GET" and not spec.get("query_params") and not spec.get("response_fields"):
                    incomplete_specs.append(f"{label}: missing query_params and response_fields")
                elif method in {"POST", "PUT", "PATCH"} and not spec.get("body_schema"):
                    incomplete_specs.append(f"{label}: missing body_schema")

        report = {
            "summary_present": bool(summary),
            "evidence_count": evidence_count,
            "bad_evidence": bad_evidence,
            "api_specs_count": len(api_specs) if isinstance(api_specs, list) else 0,
            "bad_api_specs": bad_specs,
            "incomplete_specs": incomplete_specs,
            "finding_fallback": has_finding_fallback,
        }
        if not strict:
            return True, "", report
        if not summary:
            return False, "DONE_VALIDATION_FAILED: summary is required", report
        if evidence_count == 0 and not has_finding_fallback:
            return False, "DONE_VALIDATION_FAILED: evidence is required", report
        if bad_evidence > 0:
            return False, "DONE_VALIDATION_FAILED: evidence entries must include pointer/url", report
        if bad_specs > 0:
            return False, "DONE_VALIDATION_FAILED: api_specs entries need method + url/path", report
        if incomplete_specs:
            # Surface a clear warning — do not hard-fail since the Researcher may
            # not have found full schema docs — but the Coder must know which specs
            # are incomplete so it can handle failures defensively.
            report["warning"] = (
                f"{len(incomplete_specs)} spec(s) are incomplete: "
                + "; ".join(incomplete_specs)
                + ". Coder must treat missing fields as unverified."
            )
        return True, "", report

    def _persist_som_snapshot(self, result_data: Dict[str, Any]) -> None:
        if not self.current_state:
            return
        browser_state = self.current_state.internal_variables.get("browser_state", {})
        refs_map = result_data.get("refs") or {}
        refs = list(refs_map.keys())
        browser_state["last_snapshot_refs"] = refs
        browser_state["last_snapshot_ref_map"] = refs_map
        browser_state["som_snapshot"] = result_data.get("snapshot")
        browser_state["som_stats"] = result_data.get("stats")
        browser_state["som_updated_at"] = asyncio.get_event_loop().time()
        self.current_state.internal_variables["browser_state"] = browser_state

    def _get_ui_memory(self) -> Dict[str, Any]:
        if not self.current_state:
            return {"page_states": {}}
        raw = self.current_state.internal_variables.get("ui_memory", {})
        if isinstance(raw, dict):
            raw.setdefault("page_states", {})
            return raw
        return {"page_states": {}}

    def _set_ui_memory(self, memory: Dict[str, Any]) -> None:
        if self.current_state:
            self.current_state.internal_variables["ui_memory"] = memory

    async def _current_page_signature(self) -> str:
        result = await self._bdispatch("evaluate", expression="({url: location.href, title: document.title})")
        if not result.success:
            return "unknown:unknown"
        data = (result.data or {}).get("result", {})
        if not isinstance(data, dict):
            return "unknown:unknown"
        return f"{data.get('url', '')}|{data.get('title', '')}"

    async def _record_ui_action_success(self, action: str, ref: str) -> None:
        if not ref:
            return
        sig = await self._current_page_signature()
        memory = self._get_ui_memory()
        page_states = memory.get("page_states", {})
        if not isinstance(page_states, dict):
            page_states = {}
        state = page_states.get(sig, {})
        if not isinstance(state, dict):
            state = {}
        by_action = state.get("successful_refs", {})
        if not isinstance(by_action, dict):
            by_action = {}
        refs = by_action.get(action, [])
        if not isinstance(refs, list):
            refs = []
        refs = [r for r in refs if r != ref]
        refs.insert(0, ref)
        by_action[action] = refs[:8]
        state["successful_refs"] = by_action
        state["updated_at"] = asyncio.get_event_loop().time()
        page_states[sig] = state
        memory["page_states"] = page_states
        self._set_ui_memory(memory)

    def _repair_candidates_from_snapshot(self, failed_ref: str, action: str, refs_map: Dict[str, Any]) -> List[str]:
        candidates: List[str] = []
        if failed_ref and failed_ref in refs_map:
            candidates.append(failed_ref)
        if failed_ref:
            for key in sorted(refs_map.keys()):
                if key.startswith(failed_ref[:1]) and key != failed_ref:
                    candidates.append(key)
        for key in sorted(refs_map.keys()):
            if key not in candidates:
                candidates.append(key)
        return candidates[:6]

    async def _attempt_ui_repair(
        self,
        action: Literal["click", "type"],
        failed_ref: str,
        text: Optional[str] = None,
        submit: bool = False,
        slowly: bool = False,
        timeout_ms: int = 30000,
    ) -> Dict[str, Any]:
        # Adaptive repair horizon - give the agent room to think/recover
        max_turns = max(2, int(os.getenv("RESEARCH_REPAIR_MAX_TURNS", "5")))
        sig = await self._current_page_signature()
        memory = self._get_ui_memory()
        page_states = memory.get("page_states", {})
        memory_refs: List[str] = []
        if isinstance(page_states, dict):
            state = page_states.get(sig, {})
            if isinstance(state, dict):
                successful = state.get("successful_refs", {})
                if isinstance(successful, dict):
                    memory_refs = list(successful.get(action, []) or [])

        attempted: Set[str] = set()
        for turn in range(1, max_turns + 1):
            snap = await self._bdispatch("snapshot", interactive_only=True, compact=True)
            if snap.success and isinstance(snap.data, dict):
                self._persist_som_snapshot(snap.data)
                refs_map = snap.data.get("refs") or {}
            else:
                refs_map = {}

            candidates = []
            for ref in memory_refs:
                if ref and ref not in candidates:
                    candidates.append(ref)
            for ref in self._repair_candidates_from_snapshot(failed_ref, action, refs_map):
                if ref not in candidates:
                    candidates.append(ref)

            for ref in candidates:
                if ref in attempted:
                    continue
                attempted.add(ref)
                if action == "click":
                    res = await self._bdispatch("click", ref=ref, timeout_ms=timeout_ms)
                else:
                    res = await self._bdispatch("type", ref=ref, text=text or "", submit=submit, slowly=slowly, timeout_ms=timeout_ms)
                if res.success:
                    await self._record_ui_action_success(action, ref)
                    return {
                        "status": "success",
                        "repaired": True,
                        "repair_turns": turn,
                        "ref": ref,
                        "hint": "Recovered via bounded repair loop.",
                    }

        if hasattr(self.llm, "query_with_vision"):
            try:
                import base64
                ss = await self._bdispatch("screenshot", full_page=False, format="png")
                ss_bytes = (ss.data or {}).get("bytes") if ss.success else None
                if ss_bytes:
                    img_b64 = base64.b64encode(ss_bytes).decode("ascii") if isinstance(ss_bytes, bytes) else str(ss_bytes)
                    vision_prompt = (
                        f'I need to {action} an element described as: "{failed_ref}". '
                        "Find the closest matching interactive element on this page.\n"
                        'Return JSON: {"found": true/false, "x": int, "y": int, "label": "..."}'
                    )
                    raw = await self.llm.query_with_vision(
                        prompt=vision_prompt,
                        image_base64=img_b64,
                        system_prompt="You locate UI elements in screenshots. Return only JSON.",
                    )
                    parsed = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
                    if parsed.get("found") and parsed.get("x") is not None:
                        ok, data, err = await self._coord_action(int(parsed["x"]), int(parsed["y"]), text if action == "type" else None)
                        if ok:
                            return {
                                "status": "success",
                                "repaired": True,
                                "repair_method": "vision_locate",
                                "x": parsed["x"],
                                "y": parsed["y"],
                                "label": parsed.get("label"),
                            }
            except Exception as exc:
                logger.debug("[RESEARCHER] Vision repair fallback failed: %s", exc)

        return {
            "status": "error",
            "error": "REPAIR_FAILED",
            "semantic_error": "REPAIR_FAILED",
            "failed_ref": failed_ref,
            "attempted_refs": sorted(list(attempted)),
        }

    def _som_refs_available(self) -> bool:
        if not self.current_state:
            return False
        browser_state = self.current_state.internal_variables.get("browser_state", {})
        refs = browser_state.get("last_snapshot_refs", [])
        return isinstance(refs, list) and len(refs) > 0

    # --- STATE MANAGEMENT HELPERS ---

    async def _track_content_cost(self, content: str, source: str):
        """Track token cost of consumed content."""
        if not content or not hasattr(self, "cognition") or not self.cognition:
            return
        
        # Estimate tokens (approx 4 chars per token)
        tokens = len(content) // 4
        if tokens > 0:
            await self.cognition.track(
                tool=source, 
                result="content_ingestion", 
                tokens=tokens, 
                phase=AgentPhase.DISCOVERY
            )

    def _get_known_urls(self) -> set:
        """Retrieve known URLs from persistent state."""
        if not self.current_state:
            return set()
        return set(self.current_state.internal_variables.get("known_urls", []))

    def _add_known_url(self, url: str):
        """Add a URL to the persistent registry."""
        if not self.current_state:
            return
        current = self._get_known_urls()
        current.add(url)
        self.current_state.internal_variables["known_urls"] = list(current)

    def _get_url_registry(self) -> Dict[str, str]:
        if not self.current_state:
            return {}
        reg = self.current_state.internal_variables.get("url_registry", {})
        if isinstance(reg, dict):
            return {str(k): str(v) for k, v in reg.items()}
        return {}

    def _set_url_registry(self, registry: Dict[str, str]):
        if self.current_state:
            self.current_state.internal_variables["url_registry"] = dict(registry)

    def _register_search_urls(self, urls: List[str]) -> Dict[str, str]:
        registry = self._get_url_registry()
        reverse = {v: k for k, v in registry.items()}
        next_idx = 1
        if registry:
            try:
                next_idx = max(int(k[1:]) for k in registry.keys() if k.startswith("u")) + 1
            except Exception:
                next_idx = len(registry) + 1
        for url in urls:
            cleaned = str(url or "").strip()
            if not cleaned:
                continue
            if cleaned not in reverse:
                key = f"u{next_idx}"
                next_idx += 1
                registry[key] = cleaned
                reverse[cleaned] = key
        self._set_url_registry(registry)
        return registry

    def _reverse_url_registry(self) -> Dict[str, str]:
        reg = self._get_url_registry()
        return {v: k for k, v in reg.items()}

    def _checkpoint(self) -> Dict[str, Any]:
        if not self.current_state:
            return {}
        cp = self.current_state.internal_variables.get("research_checkpoint", {})
        return cp if isinstance(cp, dict) else {}

    def _record_checkpoint_action(self, action: str, success: bool, details: Optional[Dict[str, Any]] = None):
        cp = self._checkpoint()
        actions = cp.get("actions_taken", [])
        if not isinstance(actions, list):
            actions = []
        actions.append({
            "action": action,
            "success": bool(success),
            "details": details or {},
            "ts": asyncio.get_event_loop().time(),
        })
        cp["actions_taken"] = actions[-40:]
        cp["last_action"] = action
        cp["last_action_success"] = bool(success)
        if self.current_state:
            self.current_state.internal_variables["research_checkpoint"] = cp

    def _suggest_recovery_strategy(self) -> str:
        cp = self._checkpoint()
        actions = cp.get("actions_taken", [])
        if not isinstance(actions, list):
            actions = []
        recent = actions[-10:]
        failures = [a for a in recent if isinstance(a, dict) and not a.get("success")]
        if len(failures) >= 6:
            return "High failure ratio. Use url_ids from registry and fetch one official source URL first."
        if recent and all(isinstance(a, dict) and a.get("action") == "search_internet_batch" for a in recent[-3:]):
            return "Search-heavy stagnation. Stop searching; call read_web_content with url_ids from last search."
        return "Switch strategy: read one minted official documentation URL, then verify extracted endpoint evidence."

    def _get_rag_ingested_sources(self) -> set:
        if not self.current_state:
            return set()
        return set(self.current_state.internal_variables.get("rag_ingested_sources", []))

    def _mark_rag_ingested(self, source: str):
        if not self.current_state:
            return
        current = self._get_rag_ingested_sources()
        current.add(source)
        self.current_state.internal_variables["rag_ingested_sources"] = list(current)

    def _truncate_for_rag(self, content: str) -> str:
        if not content:
            return content
        max_len = _env_int("RESEARCH_CONTENT_MAX_LENGTH", 32000)
        if len(content) <= max_len:
            return content
        return content[:max_len]

    def _get_rag_pipeline(self) -> RagPipeline:
        if self._rag_pipeline is None:
            self._rag_pipeline = RagPipeline()
        return self._rag_pipeline

    def _ingest_rag_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not _env_bool("RAG_AUTO_INGEST", True):
            return {"status": "skipped", "reason": "RAG_AUTO_INGEST disabled"}
        if not documents:
            return {"status": "skipped", "reason": "no documents"}
        try:
            rag = self._get_rag_pipeline()
            return rag.ingest_documents(documents)
        except Exception as exc:
            logger.warning(f"[RESEARCHER] RAG ingestion failed: {exc}")
            return {"status": "error", "error": str(exc)}

    def _add_research_finding(self, finding: Dict[str, Any]):
        """Append a structured finding to persistent state."""
        if not self.current_state:
            return
        findings = self.current_state.internal_variables.get("research_findings", [])
        if not isinstance(findings, list):
            logger.warning(f"[RESEARCHER] CORRUPT STATE DETECTED: research_findings was {type(findings)}, resetting to list.")
            findings = []
        findings.append(finding)
        self.current_state.internal_variables["research_findings"] = findings

    def _add_api_specs(self, specs: List[Dict[str, Any]]):
        if not self.current_state or not specs:
            return
        existing = self.current_state.internal_variables.get("api_specs", [])
        existing.extend(specs)
        self.current_state.internal_variables["api_specs"] = existing

    @staticmethod
    def _normalize_public_fetch_errors(results: List[Dict[str, Any]]) -> None:
        for item in results:
            if not isinstance(item, dict) or item.get("status") != "error":
                continue
            error = str(item.get("error") or "")
            if "401" in error or "403" in error:
                item["error"] = "Access Denied - Resource Protected (Auth Required)"

    def _derive_api_specs_from_findings(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        derived: List[Dict[str, Any]] = []
        if not isinstance(findings, list):
            return derived
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            url = str(finding.get("url") or "")
            snippet = str(finding.get("content_preview") or "")
            if not url or not snippet:
                continue
            extracted = self._extract_api_specs_from_content(snippet, url)
            if extracted:
                derived.extend(extracted)
        return derived

    def _parse_csv_setting(self, value: str) -> List[str]:
        if not value:
            return []
        return [v.strip().lower() for v in value.split(",") if v.strip()]

    def _get_allowed_domains(self) -> List[str]:
        return self._parse_csv_setting(_env_str("RESEARCH_ALLOWED_DOMAINS", ""))

    def _get_provider_allowlist(self) -> List[str]:
        return self._parse_csv_setting(_env_str("RESEARCH_PROVIDER_ALLOWLIST", ""))

    def _is_domain_allowed(self, url: str) -> bool:
        allowed = self._get_allowed_domains()
        if not allowed:
            return True
        netloc = urlparse(url).netloc.lower()
        if not netloc:
            return False
        return any(netloc == d or netloc.endswith(f".{d}") for d in allowed)

    def _is_same_domain(self, url_a: str, url_b: str) -> bool:
        domain_a = urlparse(url_a).netloc.lower()
        domain_b = urlparse(url_b).netloc.lower()
        return bool(domain_a and domain_b and domain_a == domain_b)

    # Providers that return academic papers, not API documentation.
    # arXiv returns EMR research papers; Crossref returns DOI/journal entries.
    # Both score 0.9 and 0.8 in the ranking weights — higher than Wikipedia —
    # and consume parallel batch slots without contributing usable API specs.
    _ACADEMIC_PROVIDERS: frozenset = frozenset({"arxiv", "crossref"})

    def _filter_search_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        provider_allowlist = set(self._get_provider_allowlist())
        filtered: List[Dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            source = (r.get("source") or "").lower()
            # Always exclude academic paper databases from API research results.
            # If the operator explicitly allowlists them, that takes precedence.
            if not provider_allowlist and source in self._ACADEMIC_PROVIDERS:
                continue
            if provider_allowlist and source not in provider_allowlist:
                continue
            url = (r.get("url") or "").strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            if url and not self._is_domain_allowed(url):
                continue
            r["url"] = url
            filtered.append(r)
        return filtered

    @staticmethod
    def _compact_search_results(results: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
        compacted: List[Dict[str, Any]] = []
        for r in (results or [])[: max(1, limit)]:
            if not isinstance(r, dict):
                continue
            # 500 chars instead of 140: API doc snippets routinely contain endpoint
            # paths, required fields, and method names beyond the first sentence.
            # At 140 chars the Researcher had to fetch the full page just to see
            # what the snippet already knew, wasting a full tool turn.
            snippet = str(r.get("snippet") or "")[:500]
            compacted.append(
                {
                    "title": str(r.get("title") or "")[:180],
                    "snippet": snippet,
                    "url": r.get("url"),
                    "source": r.get("source"),
                    "score": r.get("score"),
                }
            )
        return compacted

    def _extract_api_specs_from_content(self, content: str, source_url: str) -> List[Dict[str, Any]]:
        if not content:
            return []
        max_specs = _env_int("RESEARCH_API_SPEC_MAX", 50)
        specs: List[Dict[str, Any]] = []
        base = ""
        parsed = urlparse(source_url)
        if parsed.scheme and parsed.netloc:
            base = f"{parsed.scheme}://{parsed.netloc}"
        
        # Try strict JSON/OpenAPI extraction first.
        if content.strip().startswith("{") and '"paths"' in content:
            try:
                data = json.loads(content)
                paths = data.get("paths", {}) if isinstance(data, dict) else {}
                is_openapi = isinstance(data, dict) and isinstance(paths, dict) and (
                    "openapi" in data or "swagger" in data
                )
                if not is_openapi:
                    return []
                allowed_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
                seen_openapi: Set[str] = set()
                for path, methods in paths.items():
                    if not isinstance(methods, dict) or not isinstance(path, str):
                        continue
                    for method in methods.keys():
                        method_upper = str(method).upper()
                        if method_upper not in allowed_methods:
                            continue
                        if len(specs) >= max_specs:
                            return specs
                        key = f"{method_upper}:{path}"
                        if key in seen_openapi:
                            continue
                        seen_openapi.add(key)
                        specs.append({
                            "method": method_upper,
                            "path": path,
                            "url": f"{base}{path}" if base and isinstance(path, str) and path.startswith("/") else path,
                            "source_url": source_url,
                            "source_type": "openapi_json",
                            "operation_id": (methods.get(method) or {}).get("operationId") if isinstance(methods.get(method), dict) else None,
                            "summary": (methods.get(method) or {}).get("summary") if isinstance(methods.get(method), dict) else None,
                        })
                return specs
            except Exception:
                pass

        return specs

    def _fetch_openapi_specs_direct(self, url: str) -> Tuple[List[Dict[str, Any]], str]:
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code >= 400 or not resp.text:
                return [], ""
            text = resp.text
            specs = self._extract_api_specs_from_content(text, url)
            return specs, text[:4000]
        except Exception:
            return [], ""

    # ── PRE-RUN HOOK ──────────────────────────────────────────────────────────
    # Physics: Cognitive Offloading + Determinism at Boundaries + Finite Attention
    #
    # API capability discovery is a code-deterministic operation. There is no
    # reasoning required — given a URL and credentials the answer is always what
    # the live server returns. Placing this in a tool the LLM decides to call
    # violates three laws simultaneously:
    #   1. Cognitive Offloading: the LLM wastes reasoning budget on plumbing.
    #   2. Determinism at Boundaries: a deterministic result routed through a
    #      probabilistic decision gate.
    #   3. Law of Finite Attention: tool results land at 40-60% context position
    #      (≈50% recall) instead of P0 (≈90% recall).
    #
    # Solution: run discovery BEFORE the OODA loop starts. Store results in
    # state.internal_variables["_api_discovery"] — the ContextManager injects
    # this at P0 (right after MISSION) on every turn.

    async def _pre_run_hook(self, state: KernelState) -> None:
        """
        Pre-flight API capability discovery (executes before first LLM turn).

        Deterministically probes the target system's standard self-description
        endpoints using every candidate base URL found in state.  On first
        successful response the structured findings are stored at
        state.internal_variables["_api_discovery"] and immediately available
        to the ContextManager for P0 injection.

        The LLM receives pre-loaded capabilities and focuses exclusively on
        TASK reasoning, not API discovery mechanics.

        Cross-step reuse: if a prior step in this workflow already probed the
        same system, the result is loaded from the workflow-scoped Redis shared
        context and the HTTP probe is skipped entirely.
        """
        # Short-circuit 1: already in local state (same subagent instance re-run).
        if state.internal_variables.get("_api_discovery"):
            logger.info("[RESEARCHER] Pre-flight: already have _api_discovery in local state, skipping probe")
            self._set_research_phase(ResearchPhase.DONE, "API capabilities pre-loaded from state")
            return

        # Short-circuit 2: a prior step in this workflow already probed this API.
        # Load from workflow-scoped shared context to avoid redundant HTTP probes
        # and the web-search loop that follows when a probe fails.
        redis_store = getattr(getattr(self, "memory", None), "redis_store", None)
        if redis_store and getattr(redis_store, "enabled", False):
            try:
                shared = redis_store.get_shared_context(state.workflow_id)
                if shared and isinstance(shared.get("_api_discovery"), dict):
                    state.internal_variables["_api_discovery"] = shared["_api_discovery"]
                    logger.info(
                        "[RESEARCHER] Pre-flight: loaded _api_discovery from workflow shared context "
                        "(cross-step reuse, probe skipped)"
                    )
                    self._set_research_phase(ResearchPhase.DONE, "API capabilities pre-loaded from shared context")
                    return
            except Exception as _load_err:
                logger.debug("[RESEARCHER] Pre-flight: Redis shared context load failed: %s", _load_err)

        candidates = self._extract_api_candidate_urls(state)
        if not candidates:
            logger.info("[RESEARCHER] Pre-flight: no base_url found in state, skipping probe")
            return

        auth = self._resolve_discovery_auth(state)
        logger.info(
            "[RESEARCHER] Pre-flight discovery: %d candidate URL(s): %s",
            len(candidates), candidates[:3],
        )

        for base_url in candidates:
            try:
                result = await self._tool_probe_target_api(
                    base_url=base_url, auth_info=auth
                )
                # Only store if we found a STRUCTURED API protocol document.
                # A plain 200 at "/" (nginx page, health check) is not useful.
                # We require at least one entry in `findings` — meaning the
                # response contained a recognisable API structure
                # (FHIR CapabilityStatement, OData $metadata, OpenAPI spec, or
                # a HATEOAS link map with named resources).
                findings = result.get("findings") or {}
                meaningful = (
                    result.get("status") == "ok"
                    and bool(findings)
                    and any(
                        k in findings
                        for k in (
                            "fhir_capability_statement",
                            "odata_metadata",
                            "openapi_spec",
                            "rest_resource_index",
                        )
                    )
                )
                if meaningful:
                    discovery = {
                        "source_url": base_url,
                        "findings": findings,
                        "available": result.get("available", []),
                        "message": result.get("message", ""),
                    }
                    state.internal_variables["_api_discovery"] = discovery
                    logger.info(
                        "[RESEARCHER] Pre-flight: discovered API capabilities at %s — %s",
                        base_url, result.get("message", ""),
                    )
                    # Persist to workflow-scoped shared context so all subsequent
                    # steps load this directly (cross-step reuse, Short-circuit 2).
                    # Use merge_shared_context to avoid clobbering other shared facts.
                    if redis_store and getattr(redis_store, "enabled", False):
                        try:
                            redis_store.merge_shared_context(
                                state.workflow_id,
                                {"_api_discovery": discovery},
                                source="researcher_preflight",
                            )
                        except Exception as _re:
                            logger.debug("[RESEARCHER] Pre-flight: Redis persist failed: %s", _re)
                    
                    self._set_research_phase(ResearchPhase.DONE, "API capabilities probed and validated")
                    return  # first successful discovery is sufficient
            except Exception as probe_err:
                logger.debug(
                    "[RESEARCHER] Pre-flight: probe failed for %s — %s",
                    base_url, probe_err,
                )

        logger.info("[RESEARCHER] Pre-flight: no standard discovery endpoints responded on any candidate URL")
        # ═══ COGNITIVE COST PYRAMID: LEVEL 3 DEGRADED PATH ═══
        # API schema discovery failed — agent will fall back to web research.
        # Log planning_degraded so AuditScribe + ops tooling can identify which
        # providers consistently miss schema discovery and need schema URL config.
        self.tracer.log_event(
            "planning_timeout_fallback",
            {
                "reason": "preflight_schema_discovery_failed",
                "candidates_tried": len(candidates),
                "workflow_id": state.workflow_id,
                "step_id": state.step_id,
                "provider": state.input_data.get("provider") or state.input_data.get("credentials", {}).get("provider"),
                "remediation": (
                    "Add this provider's API base URL to RESEARCHER_PROBE_URLS env var, "
                    "or register a canonical OpenAPI/FHIR/OData endpoint in settings."
                ),
            },
        )
        # Initialise web-search counter for this subagent run (tracks Level 3 spend)
        state.internal_variables["_web_search_count"] = 0

    def _extract_api_candidate_urls(self, state: KernelState) -> List[str]:
        """
        Parameter Injection Pattern: extract every plausible API base URL from
        state without any LLM involvement.

        Tries explicit URL keys across input_data, credentials, and inherited
        context variables, then expands each root with a short list of
        protocol-standard sub-path prefixes (not vendor paths).
        """
        seen: Set[str] = set()
        candidates: List[str] = []

        def _add(url: Any) -> None:
            if not isinstance(url, str) or not url.strip():
                return
            u = url.strip().rstrip("/")
            if u and u not in seen:
                seen.add(u)
                candidates.append(u)

        # ── Explicit URL fields (highest confidence) ─────────────────────
        _add(state.input_data.get("base_url"))
        _add(state.input_data.get("api_base_url"))

        creds = state.input_data.get("credentials") or {}
        if isinstance(creds, dict):
            _add(creds.get("base_url"))
            _add(creds.get("url"))
            _add(creds.get("api_url"))

        # ── Inherited from previous agents via state re-hydration ─────────
        ivars = state.internal_variables or {}
        _add(ivars.get("base_url"))
        _add(ivars.get("api_base_url"))

        shared = (ivars.get("shared_context") or {})
        if isinstance(shared, dict):
            _add(shared.get("base_url"))
            _add(shared.get("api_base_url"))

        if not candidates:
            return candidates

        # ── Protocol-standard sub-path expansion ──────────────────────────
        # Many services place their API at a sub-path of the server root.
        # These suffixes are protocol conventions, not vendor-specific paths:
        #   /fhir, /fhir/R4   → FHIR servers often hosted under a sub-path
        #   /api, /api/v1     → Common REST convention
        #   /rest             → Alternative REST convention
        #   /graphql          → GraphQL single-endpoint convention
        # We expand only the ROOT candidates (not the already-expanded ones)
        # to avoid combinatorial explosion.
        root_candidates = list(candidates)
        protocol_sub_paths = [
            "/fhir",
            "/fhir/R4",
            "/api",
            "/api/v1",
            "/rest",
            "/graphql",
        ]
        for root in root_candidates:
            for suffix in protocol_sub_paths:
                _add(root + suffix)

        return candidates

    def _resolve_discovery_auth(
        self, state: KernelState
    ) -> Optional[Dict[str, Any]]:
        """
        Parameter Injection Pattern: resolve auth credentials from state for
        the pre-flight probe, without LLM involvement.
        """
        candidates = [
            getattr(state, "auth_context", None),
            (state.input_data or {}).get("auth_info"),
            (state.input_data or {}).get("credentials"),
            (state.internal_variables or {}).get("identity_auth_info"),
            ((state.internal_variables or {}).get("auth_status") or {}).get("auth_info"),
        ]
        for c in candidates:
            if isinstance(c, dict) and c:
                return c
        return None

    # --- TOOLS ---

    async def _tool_probe_target_api(
        self,
        base_url: str,
        auth_info: Optional[Dict[str, Any]] = None,
        extra_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Probe a live target system's standard self-describing endpoints.

        Every major enterprise API standard exposes a machine-readable
        capability declaration at a fixed, protocol-defined path.  This tool
        tries all known standard paths and returns exactly what the running
        system supports — no internet search, no documentation scraping, no
        inference.  The live system is always the ground truth.

        Standard probes by protocol (vendor-agnostic):
          FHIR (any vendor)  → GET /metadata          CapabilityStatement
          OData (SAP, MS)    → GET /$metadata          Service metadata
          OpenAPI 3          → GET /openapi.json        API spec
          Swagger 2          → GET /swagger.json        API spec
          GraphQL            → POST /graphql (introspection)
          HATEOAS/REST index → GET / or /api            Resource links

        `base_url` must be the API root — e.g. "https://api.salesforce.com/v1"
        or "https://myapp.com" — the tool appends standard paths to it.
        If `auth_info` is not supplied, credentials are resolved from the
        current step's auth context.
        """
        import aiohttp, ssl, json as _json

        logger.info("[RESEARCHER] probe_target_api: base_url=%s", base_url)

        # Resolve auth from context if not passed directly
        resolved_auth: Optional[Dict[str, Any]] = auth_info
        if not resolved_auth and self.current_state:
            resolved_auth = (
                getattr(self.current_state, "auth_context", None)
                or (self.current_state.input_data or {}).get("auth_info")
                or (self.current_state.input_data or {}).get("credentials")
            )

        # Build aiohttp BasicAuth if username/password present
        aio_auth = None
        headers: Dict[str, str] = {"Accept": "application/json"}
        if isinstance(resolved_auth, dict):
            u = resolved_auth.get("username")
            p = resolved_auth.get("password")
            if u and p:
                aio_auth = aiohttp.BasicAuth(str(u), str(p))
            token = resolved_auth.get("token") or resolved_auth.get("access_token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            if isinstance(resolved_auth.get("headers"), dict):
                headers.update(resolved_auth["headers"])

        base = base_url.rstrip("/")
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        # Protocol-standard discovery paths — no vendor hardcoding.
        # base_url is already the API root; we append standard suffixes only.
        standard_paths: List[Dict[str, str]] = [
            # ── FHIR (HL7) ─────────────────────────────────────────────────
            # Any FHIR server (Epic, Cerner, Azure FHIR, GCP FHIR, custom)
            # MUST expose /metadata returning a CapabilityStatement.
            {"path": "/metadata",               "label": "FHIR CapabilityStatement"},
            # ── OData (ISO/IEC 20802) ───────────────────────────────────────
            # SAP, Microsoft Dynamics 365, SharePoint, Azure DevOps, Salesforce
            # OData services MUST expose /$metadata returning EDMX/XML.
            {"path": "/$metadata",              "label": "OData service metadata"},
            # ── OpenAPI 3.x ─────────────────────────────────────────────────
            {"path": "/openapi.json",           "label": "OpenAPI 3 spec"},
            {"path": "/openapi.yaml",           "label": "OpenAPI 3 spec (yaml)"},
            {"path": "/api-docs",               "label": "OpenAPI (api-docs)"},
            {"path": "/api-docs/swagger.json",  "label": "OpenAPI (api-docs/swagger)"},
            # ── Swagger 2.x ─────────────────────────────────────────────────
            {"path": "/swagger.json",           "label": "Swagger 2 spec"},
            {"path": "/v2/api-docs",            "label": "Swagger 2 (Spring Boot)"},
            {"path": "/api/swagger.json",       "label": "Swagger 2 (api/)"},
            # ── HATEOAS / REST index ─────────────────────────────────────────
            # Many REST APIs return a resource link map at their root
            {"path": "/",                       "label": "REST root index"},
            {"path": "/api",                    "label": "REST api index"},
            {"path": "/api/v1",                 "label": "REST api/v1 index"},
            # ── Health / status (fallback signal) ───────────────────────────
            {"path": "/health",                 "label": "health endpoint"},
            {"path": "/actuator/health",        "label": "Spring actuator health"},
        ]
        if extra_paths:
            for p in extra_paths:
                standard_paths.append({"path": p, "label": "custom"})

        available: List[Dict[str, Any]] = []
        findings: Dict[str, Any] = {}

        try:
            async with aiohttp.ClientSession(
                auth=aio_auth,
                headers=headers,
                connector=aiohttp.TCPConnector(ssl=ssl_ctx),
            ) as session:
                for probe in standard_paths:
                    url = base + probe["path"]
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            if resp.status == 200:
                                try:
                                    body = await resp.json(content_type=None)
                                except Exception:
                                    body = {}

                                entry: Dict[str, Any] = {
                                    "label": probe["label"],
                                    "url": url,
                                    "status": 200,
                                }

                                # Parse FHIR CapabilityStatement
                                if "CapabilityStatement" in str(body.get("resourceType", "")):
                                    rest_block = (body.get("rest") or [{}])[0]
                                    resources = rest_block.get("resource", [])
                                    entry["fhir_resources"] = [
                                        {
                                            "type": r.get("type"),
                                            "interactions": [
                                                i["code"] for i in r.get("interaction", [])
                                            ],
                                            "searchParams": [
                                                sp["name"]
                                                for sp in r.get("searchParam", [])[:10]
                                            ],
                                        }
                                        for r in resources
                                    ]
                                    entry["summary"] = (
                                        f"FHIR server supports {len(resources)} resource types: "
                                        + ", ".join(r.get("type", "?") for r in resources)
                                    )
                                    findings["fhir_capability_statement"] = entry

                                # HATEOAS / REST resource index (links array)
                                # Many REST APIs (not just OpenMRS) return a
                                # {"links": [{"rel": "...", "uri": "..."}]} index
                                elif "links" in body and isinstance(body["links"], list):
                                    links = body["links"]
                                    entry["rest_resources"] = [
                                        {"name": lk.get("rel"), "uri": lk.get("uri")}
                                        for lk in links
                                    ]
                                    entry["summary"] = (
                                        f"REST resource index: {len(links)} resources: "
                                        + ", ".join(
                                            lk.get("rel", "?") for lk in links[:15]
                                        )
                                    )
                                    findings["rest_resource_index"] = entry

                                # Generic OpenAPI/Swagger — build a rich endpoint index
                                # so the researcher can emit findings without a web-search loop.
                                elif "paths" in body or "swagger" in body or "openapi" in body:
                                    raw_paths: Dict[str, Any] = body.get("paths") or {}
                                    paths_list = list(raw_paths.keys())[:20]
                                    entry["paths_sample"] = paths_list
                                    entry["summary"] = (
                                        f"OpenAPI/Swagger spec with "
                                        f"{len(raw_paths)} paths"
                                    )

                                    # Build structured endpoint index: method + path +
                                    # summary + query params + required body fields.
                                    # Cap at 60 endpoints to stay within context budget.
                                    endpoint_index: List[Dict[str, Any]] = []
                                    http_methods = ("get", "post", "put", "patch", "delete", "head")
                                    for ep_path, path_item in list(raw_paths.items())[:60]:
                                        if not isinstance(path_item, dict):
                                            continue
                                        for method in http_methods:
                                            op = path_item.get(method)
                                            if not isinstance(op, dict):
                                                continue
                                            # Query / path parameters
                                            query_params = [
                                                p.get("name", "?")
                                                for p in (op.get("parameters") or [])
                                                if isinstance(p, dict)
                                                and p.get("in") in ("query", "path")
                                            ]
                                            # Required body fields (requestBody schema)
                                            required_body: List[str] = []
                                            req_body = op.get("requestBody") or {}
                                            content = req_body.get("content") or {}
                                            for media_type, media_obj in content.items():
                                                schema = (media_obj or {}).get("schema") or {}
                                                required_body = schema.get("required") or list(
                                                    (schema.get("properties") or {}).keys()
                                                )[:8]
                                                break  # first content type is enough
                                            endpoint_index.append({
                                                "method": method.upper(),
                                                "path": ep_path,
                                                "summary": op.get("summary") or op.get("operationId") or "",
                                                "query_params": query_params[:10],
                                                "required_body": required_body[:8],
                                            })

                                    entry["endpoint_index"] = endpoint_index
                                    findings["openapi_spec"] = entry

                                else:
                                    entry["summary"] = f"200 OK ({len(_json.dumps(body))} bytes)"
                                    findings[probe["label"]] = entry

                                available.append(entry)
                                logger.info(
                                    "[RESEARCHER] probe_target_api: FOUND %s at %s",
                                    probe["label"], url,
                                )
                    except Exception as probe_err:
                        logger.debug(
                            "[RESEARCHER] probe_target_api: %s → %s",
                            url, str(probe_err)[:80],
                        )
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "available": [],
                "findings": {},
            }

        if not available:
            return {
                "status": "no_discovery_endpoints_found",
                "message": (
                    "No standard self-describing endpoints responded. "
                    "The system may not expose FHIR, OpenAPI, or a REST index. "
                    "Fall back to internet search for API documentation."
                ),
                "available": [],
                "findings": {},
            }

        return {
            "status": "ok",
            "available": available,
            "available_count": len(available),
            "findings": findings,
            "message": " | ".join(e["summary"] for e in available if "summary" in e),
        }

    async def _tool_read_file(
        self,
        file_path: Optional[str] = None,
        file: Optional[str] = None,
        offset: int = 0,
        limit: int = 8000,
    ) -> Dict[str, Any]:
        """
        Read documentation from a local file path.
        Supports pagination for large files — use offset + limit to read in pages.
        Returns: content, total_chars, has_more, next_offset.
        Example: first call omits offset (reads chars 0-7999).
                 If has_more=True, call again with offset=next_offset to continue.
        """
        self.tracer.log_tool_start("read_file", {"file_path": file_path or file, "offset": offset, "limit": limit})
        path = file_path or file
        if not path:
            error = "No local file path provided"
            self.tracer.log_tool_result("read_file", None, error=error)
            return {"status": "error", "error": error}
        try:
            with open(path, "r") as f:
                content = f.read()
        except Exception as e:
            self.tracer.log_tool_result("read_file", None, error=str(e))
            return {"status": "error", "error": str(e)}

        total_chars = len(content)
        page = content[offset: offset + limit]
        has_more = (offset + limit) < total_chars
        next_offset = offset + limit if has_more else None

        if self.current_state:
            self.current_state.internal_variables["research_source"] = path
            self._add_research_finding({
                "source": path,
                "content_preview": content[:500],
                "type": "local_file",
                "timestamp": asyncio.get_event_loop().time()
            })
            if path not in self._get_rag_ingested_sources():
                ingest = self._ingest_rag_documents([{
                    "source": path,
                    "content": self._truncate_for_rag(content),
                    "metadata": {"type": "local_file"},
                }])
                if ingest.get("status") == "success":
                    self._mark_rag_ingested(path)

        self.tracer.log_tool_result("read_file", {
            "path": path,
            "total_chars": total_chars,
            "page_chars": len(page),
            "has_more": has_more,
        })

        await self._track_content_cost(page, "read_file")

        return {
            "status": "success",
            "content": page,
            "source": path,
            "total_chars": total_chars,
            "offset": offset,
            "has_more": has_more,
            "next_offset": next_offset,
        }

    async def _tool_search_internet(
        self, query: str, preferred_domains: Optional[List[str]] = None
    ) -> str:
        """
        Search the internet.
        Args:
            query: Search query string.
            preferred_domains: Optional list of domains to bias results toward
                (e.g. ['docs.example.com', 'api.example.com']). Appended as
                site: hints so the search engine prioritises official sources.
        """
        effective_query = query
        if preferred_domains:
            site_hint = " OR ".join(f"site:{d.strip()}" for d in preferred_domains[:3])
            effective_query = f"{query} ({site_hint})"

        self.tracer.log_tool_start("search_internet", {"query": effective_query, "preferred_domains": preferred_domains})
        logger.info("[RESEARCHER] Searching: %s", effective_query)
        # ═══ COGNITIVE COST PYRAMID: Level 3 web-search counter ═══
        if self.current_state is not None:
            count = int(self.current_state.internal_variables.get("_web_search_count") or 0) + 1
            self.current_state.internal_variables["_web_search_count"] = count
            self.tracer.log_event("planning_timeout_fallback", {
                "reason": "web_search_used",
                "search_count": count,
                "query": effective_query,
            })

        try:
            await self.internet_search.initialize()
            results = await self.internet_search.search(effective_query, max_results=5)
            results = self._filter_search_results(results)
            results = self._compact_search_results(results, limit=5)
            # Register URLs to prevent hallucination
            for r in results:
                if isinstance(r, dict) and r.get("url"):
                    self._add_known_url(r["url"])

            # Phase transition: any successful search leaves INIT (mirrors
            # the batch variant at _tool_search_internet_batch).  Without
            # this, the researcher stays in INIT where
            # publish_research_findings is blocked, producing the
            # PHASE_TOOL_CONTRACT_VIOLATION seen in prod traces (Bug #2).
            if self._current_research_phase() == ResearchPhase.INIT:
                self._set_research_phase(ResearchPhase.SEARCHING, "search_internet_completed")

            self.tracer.log_tool_result("search_internet", results)
            return json.dumps(results, indent=2)
        except Exception as e:
            self.tracer.log_tool_result("search_internet", None, error=str(e))
            return json.dumps({"error": str(e)})

    async def _tool_search_internet_batch(
        self,
        queries: List[str],
        max_results_per_query: int = 3,
        preferred_domains: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run multiple searches in parallel. Returns results keyed by query.
        Args:
            queries: List of search query strings.
            max_results_per_query: Max results returned per query (default 3).
            preferred_domains: Optional list of domains to bias all queries toward
                (e.g. ['docs.example.com']). Applied as site: hints to every query.
        """
        self._set_research_phase(ResearchPhase.SEARCHING, "batch_discovery")

        site_hint: str = ""
        if preferred_domains:
            site_hint = " OR ".join(f"site:{d.strip()}" for d in preferred_domains[:3])

        effective_queries = [
            f"{q} ({site_hint})" if site_hint else q for q in (queries or [])
        ]

        self.tracer.log_tool_start("search_internet_batch", {"queries": effective_queries, "preferred_domains": preferred_domains})
        # ═══ COGNITIVE COST PYRAMID: Level 3 web-search counter ═══
        if self.current_state is not None:
            count = int(self.current_state.internal_variables.get("_web_search_count") or 0) + len(effective_queries)
            self.current_state.internal_variables["_web_search_count"] = count
            self.tracer.log_event("planning_timeout_fallback", {
                "reason": "web_search_batch_used",
                "search_count": count,
                "queries": effective_queries,
            })
        
        if not effective_queries:
            error = "queries list is empty"
            self.tracer.log_tool_result("search_internet_batch", None, error=error)
            return {"status": "error", "error": error}

        effective_queries = effective_queries[:6]  # cap to reduce latency and context bloat
        logger.info("[RESEARCHER] Parallel search batch: %d queries", len(effective_queries))

        out: Dict[str, Any] = {"status": "success", "by_query": {}}

        await self.internet_search.initialize()
        # Pass academic provider names so they are skipped at query time —
        # no network call is made for them at all.  _filter_search_results
        # still provides a second-level safety net, but skipping early avoids
        # wasted parallel network slots and latency on every batch search.
        _academic_skip = set(self._ACADEMIC_PROVIDERS) if not self._get_provider_allowlist() else set()
        tasks = [
            self.internet_search.search(
                q,
                max_results=max_results_per_query,
                exclude_providers=_academic_skip,
            )
            for q in effective_queries
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for q, res in zip(effective_queries, results_list):
            if isinstance(res, Exception):
                out["by_query"][q] = {"error": str(res), "results": []}
            elif isinstance(res, list):
                filtered = self._filter_search_results(res)
                filtered = self._compact_search_results(filtered, limit=max_results_per_query)
                out["by_query"][q] = {"results": filtered}
                # Register URLs from search results to prevent hallucination
                for r in filtered:
                    if isinstance(r, dict) and r.get("url"):
                        self._add_known_url(r["url"])
            else:
                out["by_query"][q] = {"error": "Unexpected search result type", "results": []}
                        
        # Flatten for easy consumption: all_results = list of {query, title, snippet, url}
        all_results = []
        for q, data in out["by_query"].items():
            for r in data.get("results", []):
                all_results.append({**r, "query": q})
        out["all_results"] = all_results[:25]
        if self.current_state:
            last_urls = [
                str(r.get("url")) for r in out["all_results"] if isinstance(r, dict) and r.get("url")
            ][:20]
            self.current_state.internal_variables["last_search_urls"] = last_urls
            out["url_registry"] = self._register_search_urls(last_urls)
            out["usage_hint"] = "Use read_web_content(url_ids=[...]) with keys from url_registry."
        self._record_checkpoint_action("search_internet_batch", True, {"queries": len(effective_queries), "results": len(out.get('all_results', []))})
        
        # Add explicit instruction to use these exact URLs
        out["IMPORTANT"] = "Use ONLY the exact URLs listed above. Do NOT modify or construct new URLs."
        
        self.tracer.log_tool_result("search_internet_batch", {"result_count": len(all_results)})
        return out

    async def _tool_read_web_content(
        self,
        urls: Optional[List[str]] = None,
        url_ids: Optional[List[str]] = None,
        max_content_length: Optional[int] = None,
        auto_escalate: bool = True,
    ) -> Dict[str, Any]:
        """
        Fast HTTP ingestion for URLs.
        Auto-escalates to browser on anti-bot/WAF blocks when enabled.
        """
        self._set_research_phase(ResearchPhase.EXTRACTING, "read_web_content")
        self.tracer.log_tool_start("read_web_content", {"urls": urls, "url_ids": url_ids})
        safe_urls: List[str] = []
        if isinstance(urls, list):
            safe_urls = [str(u) for u in urls if isinstance(u, str) and u.strip()]
        elif isinstance(urls, str):
            safe_urls = [urls]
        limit = max_content_length or _env_int("RESEARCH_CONTENT_MAX_LENGTH", 32000)
        traverse_enabled = _env_bool("RESEARCH_TRAVERSE_ENABLED", True)
        max_depth = _env_int("RESEARCH_TRAVERSE_MAX_DEPTH", 2)
        max_extra_links = _env_int("RESEARCH_TRAVERSE_MAX_LINKS", 5)

        if url_ids and self.current_state:
            reg = self._get_url_registry()
            for uid in url_ids:
                mapped = reg.get(str(uid))
                if mapped:
                    safe_urls.append(mapped)
                elif isinstance(uid, str) and uid.startswith(("http://", "https://")):
                    safe_urls.append(uid)
        if _env_bool("RESEARCH_REQUIRE_URL_IDS", True):
            registry = self._get_url_registry()
            if registry and not url_ids and safe_urls:
                exact_values = {str(v).strip() for v in registry.values() if isinstance(v, str)}
                unmatched_urls = [u for u in safe_urls if str(u or "").strip() not in exact_values]
                return {
                    "status": "error",
                    "error": "URL_ID_SELECTION_REQUIRED",
                    "semantic_error": "URL_ID_SELECTION_REQUIRED",
                    "reason": "URL registry exists; select target URLs via url_ids for deterministic selection.",
                    "unminted_urls": unmatched_urls,
                    "available_url_ids": sorted(list(registry.keys())),
                }
        
        if not safe_urls:
            error = "No URLs provided"
            self.tracer.log_tool_result("read_web_content", None, error=error)
            return {"status": "error", "error": error}

        target_urls = []
        results = []
        
        # We previously enforced a STRICT GUARDRAIL here to only allow minted URLs.
        # However, this caused severe cognitive friction (excessive turns) when the agent
        # legitimately deduced a valid URL or was provided one in the prompt.
        # We now allow any URL, relying on HTTP 404s to catch hallucinations.
        
        for u in safe_urls:
            if u and u.strip():
                cleaned = u.strip()
                if not cleaned.startswith(("http://", "https://")):
                    cleaned = "https://" + cleaned
                
                target_urls.append(cleaned)
        
        target_urls = target_urls[:5]
        
        if target_urls:
            logger.info(f"[RESEARCHER] Reading {len(target_urls)} verified URLs via HTTP...")

        # results list is already initialized and may contain rejected URLs
        browser_candidates: List[str] = []
        pdf_candidates: List[str] = []
        pending_errors: Dict[str, str] = {}
        queue: List[Dict[str, Any]] = [{"url": u, "depth": 0} for u in target_urls]
        visited: set = set()
        max_total = len(target_urls) + (max_extra_links if traverse_enabled else 0)

        await self.internet_search.initialize()
        while queue and len(visited) < max_total:
            item = queue.pop(0)
            url = item.get("url")
            depth = int(item.get("depth", 0))
            if not url or url in visited:
                continue
            visited.add(url)

            direct_specs: List[Dict[str, Any]] = []
            direct_preview = ""
            if _env_bool("RESEARCH_OPENAPI_DIRECT_FETCH_ENABLED", True):
                lowered = url.lower()
                if lowered.endswith(".json") or "swagger" in lowered or "openapi" in lowered:
                    direct_specs, direct_preview = await asyncio.to_thread(self._fetch_openapi_specs_direct, url)
                    if direct_specs:
                        self._add_api_specs(direct_specs)

            _cached_content = self._url_content_cache.get(url)
            if _cached_content is not None:
                logger.debug("[RESEARCHER] URL cache hit: %s (%d chars)", url, len(_cached_content))
                extracted: Dict[str, Any] = {"main_content": _cached_content, "error": ""}
            else:
                extracted = await self.internet_search.extract_content(url)
            content = extracted.get("main_content") or extracted.get("content") or ""
            error = extracted.get("error") or ""
            if content and not error:
                self._url_content_cache[url] = content

            if not content or error:
                if direct_specs:
                    await self._track_content_cost(direct_preview[:limit], "read_web_content:openapi_direct")
                    results.append({
                        "url": url,
                        "status": "success",
                        "method": "openapi_direct",
                        "content": direct_preview[:limit],
                        "truncated": len(direct_preview) > limit,
                        "api_specs_found": len(direct_specs),
                    })
                    continue
                if auto_escalate and self._is_pdf_url(url, error):
                    pdf_candidates.append(url)
                    pending_errors[url] = error or "No content extracted"
                    continue
                if auto_escalate:
                    logger.info(f"[RESEARCHER] Auto-escalating to browser for {url} due to missing content or error: {error}")
                    browser_candidates.append(url)
                    pending_errors[url] = error or "Missing content"
                    continue
                entry = {
                    "url": url,
                    "status": "error",
                    "error": error or "No content extracted",
                    "hint": "This URL may not exist. Use exact URLs from search results.",
                    "semantic_error": "CONTENT_FETCH_FAILED"
                }
                results.append(entry)
                continue

            final_content = content[:limit]
            if len(content) > limit:
                final_content += (
                    f"\n... [CONTENT TRUNCATED. Call read_web_content with "
                    f"max_content_length={limit*2} to see more.]"
                )

            self._add_research_finding({
                "url": url,
                "content_preview": final_content[:4000],
                "timestamp": asyncio.get_event_loop().time()
            })
            if url not in self._get_rag_ingested_sources():
                ingest = self._ingest_rag_documents([{
                    "source": url,
                    "content": self._truncate_for_rag(content),
                    "metadata": {"method": "http_fast"},
                }])
                if ingest.get("status") == "success":
                    self._mark_rag_ingested(url)

            api_specs = self._extract_api_specs_from_content(content, url)
            if direct_specs:
                api_specs.extend(direct_specs)
            if api_specs:
                self._add_api_specs(api_specs)

            await self._track_content_cost(final_content, "read_web_content:http")

            results.append({
                "url": url,
                "status": "success",
                "method": "http_fast",
                "content": final_content,
                "api_specs_found": len(api_specs),
            })

            if traverse_enabled and depth < max_depth:
                links = extracted.get("links") or []
                for link in links:
                    if len(visited) + len(queue) >= max_total:
                        break
                    if not link or link in visited:
                        continue
                    if _env_bool("RESEARCH_TRAVERSE_SAME_DOMAIN_ONLY", True) and not self._is_same_domain(url, link):
                        continue
                    if not self._is_domain_allowed(link):
                        continue
                    self._add_known_url(link)
                    queue.append({"url": link, "depth": depth + 1})

        if auto_escalate and pdf_candidates:
            await self._ensure_dispatcher()
            for url in pdf_candidates:
                try:
                    pdf_text, pdf_error = await self._fetch_pdf_via_browser(
                        url,
                        max_retries=_env_int("RESEARCH_PDF_MAX_RETRIES", 3),
                        timeout_seconds=_env_int("RESEARCH_PDF_TIMEOUT_SECONDS", 90),
                    )
                    if pdf_text:
                        final_content = pdf_text[:limit]
                        if len(pdf_text) > limit:
                            final_content += (
                                f"\n... [CONTENT TRUNCATED. Call read_web_content with "
                                f"max_content_length={limit*2} to see more.]"
                            )
                        
                        self._add_research_finding({
                            "url": url,
                            "content_preview": final_content[:500],
                            "type": "pdf",
                            "timestamp": asyncio.get_event_loop().time()
                        })
                        if url not in self._get_rag_ingested_sources():
                            ingest = self._ingest_rag_documents([{
                                "source": url,
                                "content": self._truncate_for_rag(pdf_text),
                                "metadata": {"method": "browser_pdf_fetch"},
                            }])
                            if ingest.get("status") == "success":
                                self._mark_rag_ingested(url)
                        
                        api_specs = self._extract_api_specs_from_content(pdf_text, url)
                        if api_specs:
                            self._add_api_specs(api_specs)
                        
                        # Track content cost
                        await self._track_content_cost(final_content, "read_web_content:pdf")
                        
                        results.append({
                            "url": url,
                            "status": "success",
                            "method": "browser_pdf_fetch",
                            "content": final_content,
                            "api_specs_found": len(api_specs),
                            "relevance_score": self._calculate_relevance_score(final_content, len(api_specs)),
                            "ooda_hint": "HIGH RELEVANCE: Extract" if self._calculate_relevance_score(final_content, len(api_specs)) > 0.7 else "LOW RELEVANCE: Discard"
                        })
                    else:
                        results.append({
                            "url": url,
                            "status": "error",
                            "error": pdf_error or pending_errors.get(url, "PDF browser fetch failed"),
                            "semantic_error": "PDF_FETCH_FAILED"
                        })
                except Exception as exc:
                    results.append({
                        "url": url,
                        "status": "error",
                        "error": str(exc),
                        "semantic_error": "PDF_FETCH_EXCEPTION"
                    })

        if auto_escalate and browser_candidates:
            await self._ensure_dispatcher()
            for url in browser_candidates:
                try:
                    nav_res = await self._bdispatch("navigate", url=url, timeout_ms=45000)
                    if not nav_res.success:
                        results.append({
                            "url": url,
                            "status": "error",
                            "error": nav_res.error or pending_errors.get(url, "Navigation failed"),
                            "semantic_error": "BROWSER_NAV_FAILED"
                        })
                        continue
                    
                    await asyncio.sleep(5)
                    
                    snap_res = await self._bdispatch("snapshot", interactive_only=False)
                    if snap_res.success:
                        text_res = await self._tool_browser_get_page_text()
                        content = text_res.get("content", "") if text_res.get("status") == "success" else ""
                        
                        if not content:
                            text_res_old = await self._bdispatch("get_text", ref="body")
                            content = text_res_old.data.get("text", "") if text_res_old.success else ""
                            
                        if snap_res.data.get("snapshot"):
                            content = (
                                f"[Interactive Elements]:\n{snap_res.data.get('snapshot')}\n\n"
                                f"[Page Text]:\n{content}"
                            )
                        final_content = content[:limit]
                        if len(content) > limit:
                            final_content += (
                                f"\n... [CONTENT TRUNCATED. Call read_web_content with "
                                f"max_content_length={limit*2} to see more.]"
                            )
                        
                        self._add_research_finding({
                            "url": url,
                            "content_preview": final_content[:500],
                            "type": "browser_render",
                            "timestamp": asyncio.get_event_loop().time()
                        })
                        
                        # Track content cost
                        await self._track_content_cost(final_content, "read_web_content:browser")
                        if url not in self._get_rag_ingested_sources():
                            ingest = self._ingest_rag_documents([{
                                "source": url,
                                "content": self._truncate_for_rag(content),
                                "metadata": {"method": "browser_fallback"},
                            }])
                            if ingest.get("status") == "success":
                                self._mark_rag_ingested(url)
                        
                        api_specs = self._extract_api_specs_from_content(content, url)
                        if api_specs:
                            self._add_api_specs(api_specs)
                        
                        results.append({
                            "url": url,
                            "status": "success",
                            "method": "browser_render",
                            "content": final_content,
                            "api_specs_found": len(api_specs),
                            "relevance_score": self._calculate_relevance_score(final_content, len(api_specs)),
                            "ooda_hint": "HIGH RELEVANCE: Extract" if self._calculate_relevance_score(final_content, len(api_specs)) > 0.7 else "LOW RELEVANCE: Discard"
                        })
                    else:
                        results.append({
                            "url": url,
                            "status": "error",
                            "error": snap_res.error or pending_errors.get(url, "Snapshot failed"),
                            "semantic_error": "BROWSER_SNAPSHOT_FAILED"
                        })
                except Exception as exc:
                    results.append({
                        "url": url,
                        "status": "error",
                        "error": str(exc),
                        "semantic_error": "BROWSER_EXCEPTION"
                    })

        success_count = sum(1 for page in results if isinstance(page, dict) and page.get("status") == "success")
        # Normalize public web auth errors so they do not trigger global auth blockers.
        self._normalize_public_fetch_errors(results)
        if success_count == 0 and results:
            allowed_urls: List[str] = []
            allowed_url_ids: List[str] = []
            if self.current_state:
                raw_urls = self.current_state.internal_variables.get("last_search_urls", [])
                if isinstance(raw_urls, list):
                    allowed_urls = [str(u) for u in raw_urls if u][:10]
                    reverse = self._reverse_url_registry()
                    allowed_url_ids = [reverse[u] for u in allowed_urls if u in reverse]
            strategy = self._suggest_recovery_strategy()
            self._set_research_phase(ResearchPhase.DIAGNOSING, "no_content_extracted")
            self._record_checkpoint_action("read_web_content", False, {"reason": "NO_CONTENT_EXTRACTED"})
            self.tracer.log_tool_result(
                "read_web_content",
                {"pages_count": len(results), "success_count": 0},
                error="NO_CONTENT_EXTRACTED",
            )
            return {
                "status": "error",
                "error": "NO_CONTENT_EXTRACTED",
                "semantic_error": "NO_CONTENT_EXTRACTED",
                "reason": "All candidate pages failed extraction or provenance checks.",
                "allowed_urls": allowed_urls,
                "allowed_url_ids": allowed_url_ids,
                "recovery_strategy": strategy,
                "pages": results,
            }

        self._record_checkpoint_action("read_web_content", True, {"success_count": success_count})
        self._set_research_phase(ResearchPhase.VERIFYING, "content_extracted")
        self.tracer.log_tool_result("read_web_content", {"pages_count": len(results), "success_count": success_count})
        return {"status": "success", "pages": results}


    @staticmethod
    def _is_pdf_url(url: str, error: str = "") -> bool:
        if url.lower().endswith(".pdf"):
            return True
        return "pdf" in (error or "").lower()

    async def _fetch_pdf_via_browser(
        self,
        url: str,
        max_retries: int,
        timeout_seconds: int,
    ) -> tuple[str, str]:
        last_error = ""
        dispatcher = await self._ensure_dispatcher()
        controller = await dispatcher.get_controller(self._browser_profile_name)
        for attempt in range(max_retries):
            try:
                response = await controller.session.page.request.get(
                    url,
                    timeout=timeout_seconds * 1000,
                )
                status = response.status
                if status == 200:
                    pdf_bytes = await response.body()
                    text = self.internet_search._extract_pdf_text(pdf_bytes)
                    if text:
                        return text, ""
                    last_error = "PDF extraction failed"
                    return "", last_error
                if status in (202, 429, 503, 504):
                    last_error = f"HTTP error: {status}"
                    await asyncio.sleep(1.0 * (2 ** attempt))
                    continue
                last_error = f"HTTP error: {status}"
                return "", last_error
            except Exception as exc:
                last_error = str(exc)
                await asyncio.sleep(1.0 * (2 ** attempt))
        return "", last_error or "PDF browser fetch failed"

    async def _tool_rag_query(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        self.tracer.log_tool_start("rag_query", {"query": query})
        rag = self._get_rag_pipeline()
        result = rag.retrieve(query, top_k=top_k)

        # Extract api_specs from retrieved passages so the api_doc gate can see
        # them.  RAG is built from previously ingested API documentation — the
        # correct endpoint specs may already be cached here.  Without this step
        # the Researcher would call rag_query, get back raw passages, and the
        # gate would still report "no verified specs" even though the answer was
        # sitting in the index the whole time.
        extracted_count = 0
        if isinstance(result, dict):
            for item in result.get("results", []):
                if not isinstance(item, dict):
                    continue
                passage = str(item.get("content") or item.get("text") or item.get("passage") or "")
                source = str(item.get("source") or item.get("url") or "")
                if passage:
                    specs = self._extract_api_specs_from_content(passage, source)
                    if specs:
                        self._add_api_specs(specs)
                        extracted_count += len(specs)

        if result and self.current_state:
            self._add_research_finding({
                "query": query,
                "rag_result_preview": str(result)[:500],
                "type": "rag",
                "timestamp": asyncio.get_event_loop().time(),
            })

        result_count = len(result.get("results", [])) if isinstance(result, dict) else 0
        if extracted_count:
            logger.info("[RESEARCHER] rag_query: extracted %d api_spec(s) from %d passages", extracted_count, result_count)
        self.tracer.log_tool_result("rag_query", {"count": result_count, "specs_extracted": extracted_count})
        return result


    async def _tool_extract_api_details(self, text: str) -> Dict[str, Any]:
        """
        Uses LLM to extract structured API specs from unstructured documentation text.
        Returns api_specs entries with body_schema for POST/PUT/PATCH endpoints so the
        Coder never has to guess request field names and types.

        Call this immediately after browser_get_page_text or read_web_content to convert
        raw documentation into structured api_specs. Results are automatically persisted
        to state — no manual copy to publish_research_findings needed.
        """
        self.tracer.log_tool_start("extract_api_details", {"text_length": len(text)})

        prompt = f"""You are an API specification extractor. Read the documentation text below
and return a JSON object with this exact structure:

{{
  "api_specs": [
    {{
      "method": "GET|POST|PUT|PATCH|DELETE",
      "path": "/exact/url/path",
      "summary": "one-line description",
      "query_params": {{
        "param_name": "type, description, required/optional"
      }},
      "body_schema": {{
        "field_name": "type and description"
      }},
      "required_fields": ["field1", "field2"],
      "response_fields": ["field1", "field2"]
    }}
  ],
  "base_path": "/common/prefix/if/any",
  "notes": "any important constraints or auth notes"
}}

Rules:
- Extract EVERY endpoint you can identify, even if partial.
- GET: query_params is MANDATORY. List every documented query parameter (e.g. ?v=, ?q=, ?limit=, ?startIndex=). Without these the Coder cannot control response representation or filter results.
- POST, PUT, PATCH: body_schema is MANDATORY. List every request body field you can find.
- DELETE: note any required path parameters or body fields.
- required_fields: list only fields the API explicitly marks as required.
- response_fields: key fields returned in the response (especially IDs/UUIDs used by downstream steps).
- Do NOT invent field names. Only include what the documentation explicitly states.
- If you cannot determine a value, omit the key rather than guessing.

DOCUMENTATION TEXT:
{text[:20000]}
"""
        if not hasattr(self.llm, "query_json"):
            error = "LLM does not support structured query"
            self.tracer.log_tool_result("extract_api_details", None, error=error)
            return {"error": error}

        result = await self.llm.query_json(
            "You are a precise API specification extractor. Return only valid JSON.", prompt
        )
        extracted_specs = result.get("api_specs") if isinstance(result, dict) else []
        spec_count = len(extracted_specs) if isinstance(extracted_specs, list) else 0

        if isinstance(extracted_specs, list) and extracted_specs:
            self._add_api_specs(extracted_specs)
            logger.info(
                "[RESEARCHER] extract_api_details: added %d api_spec(s) via LLM extraction",
                spec_count,
            )
            if self.current_state:
                self._add_research_finding({
                    "source": "extract_api_details",
                    "content_preview": f"Extracted {spec_count} api_spec(s) from documentation text.",
                    "type": "api_extraction",
                    "timestamp": asyncio.get_event_loop().time(),
                })

        self.tracer.log_tool_result("extract_api_details", {"specs_extracted": spec_count})
        return result

    # -------------------------------------------------------------------------
    # CODEBASE SEARCH TOOL
    # -------------------------------------------------------------------------

    async def _tool_grep_codebase(
        self,
        pattern: str,
        path: str = ".",
        file_glob: str = "*.py",
        max_results: int = 50,
        context_lines: int = 2,
    ) -> Dict[str, Any]:
        """
        Deterministic text/regex search of the local codebase.

        Uses ripgrep (rg) when available for maximum speed. Falls back to
        Python re + os.walk when rg is not on the PATH. Caps output at
        max_results matches to prevent context explosion.

        Returns structured matches: [{file, line, text, type(match|context)}]
        """
        self.tracer.log_tool_start("grep_codebase", {
            "pattern": pattern, "path": path, "file_glob": file_glob,
        })

        matches: List[Dict[str, Any]] = []
        source = "ripgrep"

        try:
            cmd = [
                "rg",
                "--no-heading",
                "--line-number",
                "--color=never",
                "-g", file_glob,
                "-C", str(context_lines),
                "--max-count", "5",   # max 5 hits per file to avoid any single file dominating
                pattern,
                path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            for line in proc.stdout.splitlines():
                if len(matches) >= max_results:
                    break
                # ripgrep match line:  "file:lineno:content"
                m = re.match(r"^(.+?):(\d+):(.*)", line)
                if m:
                    matches.append({"file": m.group(1), "line": int(m.group(2)), "text": m.group(3), "type": "match"})
                    continue
                # ripgrep context line: "file-lineno-content"
                c = re.match(r"^(.+?)-(\d+)-(.*)", line)
                if c:
                    matches.append({"file": c.group(1), "line": int(c.group(2)), "text": c.group(3), "type": "context"})

        except FileNotFoundError:
            # rg binary not available — fall back to pure-Python search.
            source = "python_re"
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                err = f"Invalid regex: {exc}"
                self.tracer.log_tool_result("grep_codebase", None, error=err)
                return {"status": "error", "error": err}

            for root, _dirs, files in os.walk(path):
                if len(matches) >= max_results:
                    break
                for fname in files:
                    if len(matches) >= max_results:
                        break
                    if not fnmatch.fnmatch(fname, file_glob):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", errors="ignore") as fh:
                            lines = fh.readlines()
                        for i, text in enumerate(lines):
                            if len(matches) >= max_results:
                                break
                            if compiled.search(text):
                                start = max(0, i - context_lines)
                                end = min(len(lines), i + context_lines + 1)
                                for j in range(start, end):
                                    matches.append({
                                        "file": fpath,
                                        "line": j + 1,
                                        "text": lines[j].rstrip(),
                                        "type": "match" if j == i else "context",
                                    })
                    except OSError:
                        pass

        except subprocess.TimeoutExpired:
            source = "ripgrep_timeout"

        match_count = sum(1 for m in matches if m["type"] == "match")
        self.tracer.log_tool_result("grep_codebase", {"match_count": match_count, "source": source})
        return {
            "status": "success",
            "pattern": pattern,
            "path": path,
            "source": source,
            "match_count": match_count,
            "matches": matches,
        }

    # -------------------------------------------------------------------------
    # BROWSER AUTOMATION TOOLS (Ref-Based)
    # -------------------------------------------------------------------------
    
    async def _ensure_dispatcher(self) -> BrowserDispatcher:
        """Ensure browser dispatcher is ready; creates on first call."""
        if self._dispatcher is not None:
            return self._dispatcher

        registry = BrowserProfileRegistry(
            default_profile=self._browser_profile_name,
            allow_unregistered=False,
        )
        registry.register(BrowserProfile(
            name=self._browser_profile_name,
            config=self._browser_config,
        ))
        self._dispatcher = BrowserDispatcher(registry)
        logger.info("[RESEARCHER] Browser dispatcher initialized (profile=%s)", self._browser_profile_name)

        if (
            getattr(settings, "BROWSER_CAPTURE_ENABLED", False)
            and self.current_state
            and not self.current_state.internal_variables.get("browser_capture_started")
        ):
            try:
                capture_session_id = f"{self.workflow_id or 'research'}:{self.step_id or 'step'}"
                cap_res = await self._dispatcher.dispatch({
                    "kind": "capture_start",
                    "profile": self._browser_profile_name,
                    "payload": {"session_id": capture_session_id},
                })
                if cap_res.success:
                    self.current_state.internal_variables["browser_capture_started"] = True
                    logger.info("[RESEARCHER] Browser capture started")
            except Exception as exc:
                logger.warning("[RESEARCHER] Browser capture start exception: %s", exc)

        if self.current_state:
            self.current_state.internal_variables["browser_state"] = {
                "session_id": self._browser_profile_name,
                "started_at": asyncio.get_event_loop().time(),
            }

        return self._dispatcher

    async def _bdispatch(self, kind: str, **payload):
        """Route a browser operation through the unified BrowserDispatcher."""
        dispatcher = await self._ensure_dispatcher()
        return await dispatcher.dispatch({
            "kind": kind,
            "profile": self._browser_profile_name,
            "payload": payload,
        })
    
    async def _tool_browser_navigate(self, url: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        """
        Navigate browser to URL.
        
        Args:
            url: URL to navigate to
            timeout_ms: Navigation timeout
        
        Returns:
            Page info (url, title)
        """
        self.tracer.log_tool_start("browser_navigate", {"url": url})
        try:
            max_retries = 2
            result = None
            for attempt in range(max_retries + 1):
                try:
                    result = await self._bdispatch("navigate", url=url, timeout_ms=timeout_ms)
                    if result.success:
                        break
                    logger.warning("[RESEARCHER] Navigation attempt %d failed: %s", attempt + 1, result.error)
                    if attempt < max_retries:
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.warning("[RESEARCHER] Navigation attempt %d exception: %s", attempt + 1, e)
                    if attempt < max_retries:
                        await asyncio.sleep(2)
            
            if result and result.success:
                title_res = await self._bdispatch("evaluate", expression="document.title")
                title = (title_res.data or {}).get("result") if title_res.success else None
                logger.info(f"[RESEARCHER] Navigated to: {url}")
                
                # Persist browser state
                if self.current_state:
                    self.current_state.internal_variables["browser_state"] = {
                        "session_id": self._browser_profile_name,
                        "current_url": result.data.get("url"),
                        "title": title,
                        "last_active": asyncio.get_event_loop().time(),
                    }
                
                self.tracer.log_tool_result("browser_navigate", {"url": result.data.get("url"), "title": title})
                return {
                    "status": "success",
                    "url": result.data.get("url"),
                    "title": title,
                    "hint": "Call browser_snapshot() to get interactive elements with refs."
                }
            else:
                error = result.error if result else "Navigation failed"
                self.tracer.log_tool_result("browser_navigate", None, error=error)
                return {"status": "error", "error": error}
        except Exception as e:
            logger.error(f"[RESEARCHER] Navigation failed: {e}")
            self.tracer.log_tool_result("browser_navigate", None, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def _tool_browser_snapshot(self, interactive_only: bool = False) -> Dict[str, Any]:
        """
        Get accessibility snapshot of current page.
        
        Returns refs (e1, e2, ...) for interactive elements that can be used
        with browser_click, browser_type, etc.
        
        Args:
            interactive_only: If True, only return interactive elements (buttons, links, inputs). 
                            DEFAULT IS FALSE to ensure you can READ content.
        
        Returns:
            Accessibility tree with refs, stats
        """
        self.tracer.log_tool_start("browser_snapshot", {"interactive_only": interactive_only})
        try:
            result = await self._bdispatch("snapshot", interactive_only=interactive_only, compact=True)
            
            if result.success:
                refs_count = result.data.get('stats', {}).get('refs', 0)
                logger.info(f"[RESEARCHER] Snapshot: {refs_count} refs")
                
                # Persist snapshot refs for context recovery
                self._persist_som_snapshot(result.data)
                
                self.tracer.log_tool_result("browser_snapshot", {"refs_count": refs_count})
                
                # Track snapshot cost (snapshot data can be large)
                snapshot_data = str(result.data.get("snapshot", ""))
                await self._track_content_cost(snapshot_data, "browser_snapshot")
                
                return {
                    "status": "success",
                    "snapshot": result.data.get("snapshot"),
                    "refs": result.data.get("refs"),
                    "stats": result.data.get("stats"),
                    "hint": "Use refs (e.g., 'e1') with browser_click() or browser_type()."
                }
            else:
                self.tracer.log_tool_result("browser_snapshot", None, error=result.error)
                return {"status": "error", "error": result.error}
        except Exception as e:
            logger.error(f"[RESEARCHER] Snapshot failed: {e}")
            self.tracer.log_tool_result("browser_snapshot", None, error=str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_ui_snapshot_with_som(self, interactive_only: bool = True) -> Dict[str, Any]:
        result = await self._tool_browser_snapshot(interactive_only=interactive_only)
        if result.get("status") == "success":
            result["som_ready"] = True
            result["hint"] = "SoM snapshot persisted. Prefer browser_click/browser_type with refs."
        return result
    
    async def _tool_browser_click(
        self, 
        ref: str, 
        double_click: bool = False,
        timeout_ms: int = 8000
    ) -> Dict[str, Any]:
        """
        Click element by ref.
        
        Args:
            ref: Element ref from snapshot (e.g., "e1")
            double_click: If True, double-click
            timeout_ms: Action timeout
        """
        self.tracer.log_tool_start("browser_click", {"ref": ref, "double_click": double_click})
        try:
            if _env_bool("RESEARCH_STRICT_SOM_FIRST", True) and not ref:
                return {"status": "error", "error": "SOM_REF_REQUIRED"}
            result = await self._bdispatch("click", ref=ref, double_click=double_click, timeout_ms=timeout_ms)
            
            if result.success:
                logger.info(f"[RESEARCHER] Clicked ref={ref}")
                await self._record_ui_action_success("click", ref)
                self.tracer.log_tool_result("browser_click", {"ref": ref, "status": "success"})
                return {
                    "status": "success",
                    "ref": ref,
                    "hint": "Page may have changed. Call browser_snapshot() to get fresh refs."
                }
            else:
                if _env_bool("RESEARCH_REPAIR_LOOP_ENABLED", True):
                    repaired = await self._attempt_ui_repair(
                        action="click",
                        failed_ref=str(ref or result.ref or ""),
                        timeout_ms=timeout_ms,
                    )
                    if repaired.get("status") == "success":
                        self.tracer.log_tool_result("browser_click", repaired)
                        return repaired
                self.tracer.log_tool_result("browser_click", None, error=result.error)
                return {"status": "error", "error": result.error, "ref": result.ref}
        except Exception as e:
            self.tracer.log_tool_result("browser_click", None, error=str(e))
            return {"status": "error", "error": str(e), "ref": ref}
    
    async def _tool_browser_type(
        self,
        ref: str,
        text: str,
        submit: bool = False,
        slowly: bool = False,
        timeout_ms: int = 8000
    ) -> Dict[str, Any]:
        """
        Type text into input element by ref.
        
        Args:
            ref: Element ref from snapshot (e.g., "e2")
            text: Text to type
            submit: If True, press Enter after typing
            slowly: If True, type with delay (useful for autocomplete)
            timeout_ms: Action timeout
        """
        self.tracer.log_tool_start("browser_type", {"ref": ref, "text_len": len(text), "submit": submit})
        try:
            if _env_bool("RESEARCH_STRICT_SOM_FIRST", True) and not ref:
                return {"status": "error", "error": "SOM_REF_REQUIRED"}
            result = await self._bdispatch("type", ref=ref, text=text, submit=submit, slowly=slowly, timeout_ms=timeout_ms)
            
            if result.success:
                logger.info(f"[RESEARCHER] Typed into ref={ref}, submit={submit}")
                await self._record_ui_action_success("type", ref)
                self.tracer.log_tool_result("browser_type", {"ref": ref, "status": "success"})
                return {
                    "status": "success",
                    "ref": ref,
                    "typed": text,
                    "submitted": submit
                }
            else:
                if _env_bool("RESEARCH_REPAIR_LOOP_ENABLED", True):
                    repaired = await self._attempt_ui_repair(
                        action="type",
                        failed_ref=str(ref or result.ref or ""),
                        text=text,
                        submit=submit,
                        slowly=slowly,
                        timeout_ms=timeout_ms,
                    )
                    if repaired.get("status") == "success":
                        repaired["typed"] = text
                        self.tracer.log_tool_result("browser_type", repaired)
                        return repaired
                self.tracer.log_tool_result("browser_type", None, error=result.error)
                return {"status": "error", "error": result.error, "ref": result.ref}
        except Exception as e:
            self.tracer.log_tool_result("browser_type", None, error=str(e))
            return {"status": "error", "error": str(e), "ref": ref}

    async def _coord_action(self, x: int, y: int, text: Optional[str] = None) -> Tuple[bool, Dict[str, Any], str]:
        if text is None:
            expr = (
                "(() => {"
                f"const x={int(x)}, y={int(y)};"
                "const el=document.elementFromPoint(x,y);"
                "if(!el){return {ok:false,error:'NO_ELEMENT_AT_COORD'}};"
                "el.click();"
                "return {ok:true,tag:el.tagName||null};"
                "})()"
            )
        else:
            escaped = json.dumps(str(text))
            expr = (
                "(() => {"
                f"const x={int(x)}, y={int(y)};"
                "const el=document.elementFromPoint(x,y);"
                "if(!el){return {ok:false,error:'NO_ELEMENT_AT_COORD'}};"
                "if (typeof el.focus === 'function') { el.focus(); }"
                f"el.value = {escaped};"
                "el.dispatchEvent(new Event('input', { bubbles: true }));"
                "el.dispatchEvent(new Event('change', { bubbles: true }));"
                "return {ok:true,tag:el.tagName||null};"
                "})()"
            )
        eval_res = await self._bdispatch("evaluate", expression=expr)
        data = eval_res.data if isinstance(eval_res.data, dict) else {}
        ok = bool(eval_res.success and data.get("ok"))
        err = "" if ok else str(data.get("error") or eval_res.error or "COORD_ACTION_FAILED")
        return ok, data, err

    async def _tool_browser_click_coord(
        self,
        x: int,
        y: int,
        reason: str = "",
        force: bool = False,
        verify_snapshot: bool = True,
    ) -> Dict[str, Any]:
        if not _env_bool("RESEARCH_COORD_FALLBACK_ENABLED", True):
            return {"status": "error", "error": "COORD_FALLBACK_DISABLED"}
        if not reason:
            return {"status": "error", "error": "COORD_REASON_REQUIRED"}
        if self._som_refs_available() and not force:
            return {"status": "error", "error": "COORD_BLOCKED_SOM_AVAILABLE", "hint": "Use SoM refs first."}
        ok, data, err = await self._coord_action(x=x, y=y, text=None)
        if not ok:
            return {"status": "error", "error": err, "x": x, "y": y}
        verification = None
        if verify_snapshot:
            verification = await self._tool_ui_snapshot_with_som(interactive_only=True)
        return {"status": "success", "x": x, "y": y, "result": data, "verification": verification}

    async def _tool_browser_type_coord(
        self,
        x: int,
        y: int,
        text: str,
        reason: str = "",
        force: bool = False,
        verify_snapshot: bool = True,
    ) -> Dict[str, Any]:
        if not _env_bool("RESEARCH_COORD_FALLBACK_ENABLED", True):
            return {"status": "error", "error": "COORD_FALLBACK_DISABLED"}
        if not reason:
            return {"status": "error", "error": "COORD_REASON_REQUIRED"}
        if self._som_refs_available() and not force:
            return {"status": "error", "error": "COORD_BLOCKED_SOM_AVAILABLE", "hint": "Use SoM refs first."}
        ok, data, err = await self._coord_action(x=x, y=y, text=text)
        if not ok:
            return {"status": "error", "error": err, "x": x, "y": y}
        verification = None
        if verify_snapshot:
            verification = await self._tool_ui_snapshot_with_som(interactive_only=True)
        return {"status": "success", "x": x, "y": y, "typed": text, "result": data, "verification": verification}
    
    async def _tool_browser_get_text(self, ref: str, timeout_ms: int = 8000) -> Dict[str, Any]:
        """
        Get text content of element by ref.
        
        Args:
            ref: Element ref from snapshot
            timeout_ms: Action timeout
        """
        self.tracer.log_tool_start("browser_get_text", {"ref": ref})
        try:
            result = await self._bdispatch("get_text", ref=ref, timeout_ms=timeout_ms)
            
            if result.success:
                text = result.data.get("text", "")
                self.tracer.log_tool_result("browser_get_text", {"ref": ref, "text_len": len(text)})
                
                # Track text cost
                await self._track_content_cost(text, "browser_get_text")
                
                return {
                    "status": "success",
                    "ref": ref,
                    "text": text
                }
            else:
                self.tracer.log_tool_result("browser_get_text", None, error=result.error)
                return {"status": "error", "error": result.error, "ref": result.ref}
        except Exception as e:
            self.tracer.log_tool_result("browser_get_text", None, error=str(e))
            return {"status": "error", "error": str(e), "ref": ref}
    
    async def _tool_browser_wait(
        self,
        text: Optional[str] = None,
        text_gone: Optional[str] = None,
        time_ms: Optional[int] = None,
        load_state: Optional[Literal["load", "domcontentloaded", "networkidle"]] = None,
        timeout_ms: int = 20000
    ) -> Dict[str, Any]:
        """
        Wait for various conditions.
        
        Args:
            text: Wait for text to appear on page
            text_gone: Wait for text to disappear
            time_ms: Wait for fixed time (milliseconds)
            load_state: Wait for 'load', 'domcontentloaded', or 'networkidle'
            timeout_ms: Maximum wait time
        """
        self.tracer.log_tool_start("browser_wait", {"text": text, "time_ms": time_ms, "load_state": load_state})
        try:
            allowed = {"load", "domcontentloaded", "networkidle"}
            if load_state not in allowed:
                load_state = None
            result = await self._bdispatch(
                "wait",
                text=text,
                text_gone=text_gone,
                time_ms=time_ms,
                load_state=load_state,
                timeout_ms=timeout_ms,
            )
            
            if result.success:
                self.tracer.log_tool_result("browser_wait", {"status": "success"})
                return {"status": "success", "message": "Wait condition satisfied"}
            else:
                self.tracer.log_tool_result("browser_wait", None, error=result.error)
                return {"status": "error", "error": result.error}
        except Exception as e:
            self.tracer.log_tool_result("browser_wait", None, error=str(e))
            return {"status": "error", "error": str(e)}
    
    async def _tool_browser_get_page_text(self) -> Dict[str, Any]:
        """
        Extract ALL visible text from the current page as clean markdown.

        Use this immediately after browser_navigate when you need to read
        documentation content.  browser_get_text(ref) only retrieves text
        from a single accessibility-tree element and requires you to first
        identify the right ref — an extra step that frequently targets the
        wrong container (sidebar, nav, footer).

        This tool runs JavaScript directly against the DOM to find the main
        content container (article > main > .content > body fallback), returns
        its inner HTML, and converts it to markdown.  No ref needed.
        """
        self.tracer.log_tool_start("browser_get_page_text", {})
        try:
            script = """
(() => {
    const selectors = [
        'article', 'main', '[role="main"]',
        '.content', '#content', '.post', '.article',
        '.entry-content', '.post-content', '.wiki-content',
        '.markdown-body', '.rst-content', '.document',
        'body'
    ];
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
            const text = el.innerText || el.textContent || '';
            if (text.trim().length > 200) {
                return { selector: sel, html: el.innerHTML, text: text };
            }
        }
    }
    return { selector: 'body', html: document.body.innerHTML, text: document.body.innerText || '' };
})()
"""
            eval_result = await self._bdispatch("evaluate", expression=script)
            if not eval_result.success:
                self.tracer.log_tool_result("browser_get_page_text", None, error=eval_result.error)
                return {"status": "error", "error": eval_result.error or "JS evaluation failed"}

            # evaluate() wraps the JS return value under data["result"],
            # so we need one extra .get("result") to reach the JS object.
            outer = eval_result.data if isinstance(eval_result.data, dict) else {}
            data = outer.get("result") or {}
            if not isinstance(data, dict):
                data = {}
            raw_html = str(data.get("html") or "")
            raw_text = str(data.get("text") or "")
            selector_used = str(data.get("selector") or "body")

            # Convert HTML to markdown for structured content (tables, code blocks, headers)
            if raw_html:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(raw_html, "html.parser")
                    markdown = self.internet_search._html_to_markdown(soup)
                except Exception:
                    markdown = raw_text
            else:
                markdown = raw_text

            limit = _env_int("RESEARCH_CONTENT_MAX_LENGTH", 32000)
            content = markdown[:limit]
            if len(markdown) > limit:
                content += f"\n... [CONTENT TRUNCATED at {limit} chars. Call with a specific ref if more is needed.]"

            # Run spec extraction immediately — same as read_web_content does
            api_specs = self._extract_api_specs_from_content(markdown, "")
            if api_specs:
                self._add_api_specs(api_specs)

            self._add_research_finding({
                "url": "browser:current_page",
                "content_preview": content[:4000],
                "type": "browser_page_text",
                "selector": selector_used,
                "timestamp": asyncio.get_event_loop().time(),
            })

            await self._track_content_cost(content, "browser_get_page_text")
            self.tracer.log_tool_result("browser_get_page_text", {
                "length": len(content),
                "selector": selector_used,
                "specs_found": len(api_specs),
            })
            return {
                "status": "success",
                "content": content,
                "selector_used": selector_used,
                "api_specs_found": len(api_specs),
                "hint": "Pass this content to extract_api_details() to get structured api_specs.",
            }
        except Exception as e:
            logger.error(f"[RESEARCHER] browser_get_page_text failed: {e}")
            self.tracer.log_tool_result("browser_get_page_text", None, error=str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_browser_close(self) -> Dict[str, Any]:
        """
        Close browser session.
        Call this when done browsing to free resources.
        """
        self.tracer.log_tool_start("browser_close", {})
        try:
            if self._dispatcher:
                await self._dispatcher.close_all()
                self._dispatcher = None
                logger.info("[RESEARCHER] Browser dispatcher closed")
                if self.current_state:
                    self.current_state.internal_variables.pop("browser_state", None)
            self.tracer.log_tool_result("browser_close", {"status": "success"})
            return {"status": "success", "message": "Browser closed"}
        except Exception as e:
            self.tracer.log_tool_result("browser_close", None, error=str(e))
            return {"status": "error", "error": str(e)}

    async def _tool_publish_research_findings(
        self,
        api_specs: Optional[List[Dict[str, Any]]] = None,
        libraries: Optional[List[str]] = None,
        evidence: Optional[List[Dict[str, Any]]] = None,
        summary: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Complete research and return findings.
        Pass what you learned from browsing/searching. Closes browser if open.
        """
        self._set_research_phase(ResearchPhase.DONE, "publish_research_findings_called")
        self.tracer.log_tool_start("publish_research_findings", {})

        if self._dispatcher:
            try:
                await self._dispatcher.close_all()
                self._dispatcher = None
                if self.current_state:
                    self.current_state.internal_variables.pop("browser_state", None)
            except Exception:
                pass

        out: Dict[str, Any] = {
            "api_specs": api_specs or kwargs.get("api_specs") or [],
            "libraries": libraries or kwargs.get("libraries") or [],
            "evidence": evidence or kwargs.get("evidence") or [],
            "summary": summary or kwargs.get("summary") or "",
        }
        
        # Merge accumulated research findings from state if not explicitly provided
        if self.current_state:
            accumulated_findings = self.current_state.internal_variables.get("research_findings", [])
            if not isinstance(accumulated_findings, list):
                accumulated_findings = []
            
            if accumulated_findings:
                # Add to evidence if not already present
                if not isinstance(out["evidence"], list):
                    out["evidence"] = []
                    
                existing_urls = set()
                for e in out["evidence"]:
                    if isinstance(e, dict):
                        u = e.get("url") or e.get("pointer")
                        if u:
                            existing_urls.add(u)

                for finding in accumulated_findings:
                    if not isinstance(finding, dict):
                        continue
                    url = finding.get("url")
                    if url and url not in existing_urls:
                        # HIGH-TECH FIX: Map to strict Kernel Evidence Schema (kind + pointer)
                        # This ensures the Sovereign Loop SourcePolicy accepts the evidence.
                        out["evidence"].append({
                            "kind": "web_finding",
                            "pointer": url,
                            "url": url, # Legacy compat
                            "content": finding.get("content_preview"),
                            "content_preview": finding.get("content_preview"),
                            "source": "accumulated_history",
                            "confidence": "high"
                        })
                        existing_urls.add(url)
            
            accumulated_specs = self.current_state.internal_variables.get("api_specs", [])
            if isinstance(accumulated_specs, list) and accumulated_specs:
                if not isinstance(out["api_specs"], list):
                    out["api_specs"] = []
                
                existing_keys = {
                    f"{s.get('method')}:{s.get('path')}:{s.get('url')}"
                    for s in out["api_specs"]
                    if isinstance(s, dict)
                }
                for spec in accumulated_specs:
                    if not isinstance(spec, dict):
                        continue
                    key = f"{spec.get('method')}:{spec.get('path')}:{spec.get('url')}"
                    if key not in existing_keys:
                        out["api_specs"].append(spec)
                        existing_keys.add(key)

            # Convergence assist: derive specs from extracted findings when structured specs are missing.
            if (not isinstance(out.get("api_specs"), list)) or len(out.get("api_specs") or []) == 0:
                derived_specs = self._derive_api_specs_from_findings(accumulated_findings)
                if derived_specs:
                    out["api_specs"] = list(derived_specs)
        
        for k, v in kwargs.items():
            if k not in out:
                out[k] = v
                
        valid, reason, report = self._validate_done_payload(self.current_state, out) if self.current_state else (True, "", {})
        
        if not valid:
            self.tracer.log_tool_result("publish_research_findings", None, reason)
            return {
                "status": "error",
                "error": f"EPISTEMIC CONTRACT VIOLATION: {reason}",
                "validation_report": report
            }
            
        out["research_checkpoint"] = self._checkpoint()
        out["url_registry"] = self._get_url_registry()
        out["done_validation"] = report
        
        # Explicit output contract to tell Kernel to move back to coding
        out["status"] = "candidate_ready"
        out["action_required"] = "delegate_coding"
        
        # CRITICAL: We must set the state status to 'completed' to break the OODA loop,
        # just like the old 'done' tool used to do in base.py.
        if self.current_state:
            self.current_state.status = "completed"
        
        self.tracer.log_tool_result("publish_research_findings", out)
        return out

    def _build_research_trace_summary(self, output: Any) -> Dict[str, Any]:
        payload = output.payload if hasattr(output, "payload") and isinstance(output.payload, dict) else {}
        metadata = output.metadata if hasattr(output, "metadata") and isinstance(output.metadata, dict) else {}
        state = metadata.get("state", {}) if isinstance(metadata, dict) else {}
        tool_history = state.get("tool_history", []) if isinstance(state, dict) else []

        pages_count = 0
        pages_success = 0
        for entry in tool_history:
            if not isinstance(entry, dict):
                continue
            tool_output = entry.get("tool_output")
            if not isinstance(tool_output, dict):
                continue
            pages = tool_output.get("pages")
            if isinstance(pages, list):
                pages_count += len(pages)
                pages_success += sum(
                    1 for page in pages if isinstance(page, dict) and str(page.get("status")) == "success"
                )

        api_specs = payload.get("api_specs") if isinstance(payload, dict) else None
        evidence = payload.get("evidence") if isinstance(payload, dict) else None
        done_validation = payload.get("done_validation") if isinstance(payload, dict) else None
        status = str(getattr(output, "status", "") or "").lower()
        return {
            "status": status,
            "task_success": status in {"success", "completed"},
            "turns": len(getattr(output, "trajectory", []) or []),
            "pages_count": pages_count,
            "pages_success": pages_success,
            "api_specs_count": len(api_specs) if isinstance(api_specs, list) else 0,
            "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
            "done_validation_valid": bool(done_validation.get("valid")) if isinstance(done_validation, dict) else None,
        }

    async def cleanup(self):
        """
        Explicitly clean up resources (browser session) to prevent zombie processes.
        Called by Kernel's try/finally block.
        """
        if self._dispatcher:
            try:
                await self._dispatcher.close_all()
                logger.info("[RESEARCHER] Cleanup: Browser dispatcher closed")
            except Exception as e:
                logger.warning("[RESEARCHER] Cleanup error: %s", e)
            finally:
                self._dispatcher = None
                if self.current_state:
                    self.current_state.internal_variables.pop("browser_state", None)

    async def run(
        self,
        task: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        max_turns: Optional[int] = None,
        **kwargs,  # absorb model=, cognition=, context_manager=, memory=, trace= from Kernel
    ):
        output = await super().run(task, context, max_turns=max_turns)
        try:
            self.tracer.log_event("research_run_summary", self._build_research_trace_summary(output))
        except Exception as exc:
            logger.debug(f"Failed to emit research_run_summary trace: {exc}")
        return output
