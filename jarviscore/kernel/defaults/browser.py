"""
BrowserSubAgent — Headless browser automation specialist.

Doctrine:
  The browser agent drives a real Chromium browser (via Playwright) to interact
  with web pages that require JavaScript, authentication, or dynamic content.
  It is NOT a replacement for web_search — use it only when the task cannot be
  accomplished with HTTP + BeautifulSoup.

  Session lifecycle:
  - Shared: with a control URL, attach to the person's open browser over CDP;
    only the page this run opened is closed afterwards
  - Persistent: with a profile root, each tenant (the mesh's
    memory_scope_field) keeps cookies and logins in its own profile
  - Otherwise a fresh browser per run() call
  - Pages are reused within a run to preserve cookies/auth state

  Tool philosophy:
  - Every tool returns {status, data/error} — never raises exceptions to LLM
  - Screenshots reach the model as images attached to the observation
  - Selectors use CSS by default; XPath and text matching as fallbacks

Design principles:
  - Graceful degradation: if Playwright not installed, returns clear install message
  - Lazy Playwright import: framework loads without playwright installed
  - Page stability: wait_for_load_state("networkidle") by default
  - Anti-bot: realistic viewport, user-agent, and timing
"""

import asyncio
import hashlib
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from jarviscore.contracts.hitl import HITLAction
from jarviscore.execution.multimodal import OBSERVED_IMAGES, Image
from jarviscore.kernel import approval
from jarviscore.kernel.gate import GateEvidence
from jarviscore.kernel.subagent import BaseSubAgent

logger = logging.getLogger(__name__)

# Check Playwright availability at import time (lazy — won't crash)
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.debug("Playwright not installed — BrowserSubAgent unavailable (pip install playwright)")

_PROFILE_LOCKS: Dict[str, asyncio.Lock] = {}
# When each site was last requested by this process, for per-site pacing.
_LAST_VISIT: Dict[str, float] = {}

# Page text as a person sees it. innerText leaves out what form fields hold,
# so a basket of quantity inputs reads as a list with no quantities. Each
# field is replaced in a clone by what it currently shows.
_READ_WITH_FIELDS = """(root, wholePage) => {
    const shown = (field) => {
        const tag = field.tagName;
        const type = (field.getAttribute('type') || '').toLowerCase();
        if (type === 'hidden') return '';
        if (type === 'checkbox' || type === 'radio') return field.checked ? '[x]' : '[ ]';
        if (['submit', 'button', 'reset'].includes(type)) return field.value;
        if (tag === 'SELECT') {
            return '[' + Array.from(field.selectedOptions).map(o => o.text.trim()).join(', ') + ']';
        }
        return '[' + field.value + ']';
    };
    if (root.matches('input, select, textarea')) return shown(root);
    const live = Array.from(root.querySelectorAll('input, select, textarea'));
    const clone = root.cloneNode(true);
    Array.from(clone.querySelectorAll('input, select, textarea')).forEach((field, i) => {
        field.replaceWith(document.createTextNode(' ' + shown(live[i]) + ' '));
    });
    if (wholePage) clone.querySelectorAll('script, style, nav, footer').forEach(e => e.remove());
    return clone.innerText === undefined ? clone.textContent : clone.innerText;
}"""

# Tools that can commit the person when the agent marks the action irreversible.
_COMMITTING_TOOLS = frozenset({"click", "type_text", "fill_form", "select_option", "evaluate"})


def browser_identity(version: str, system: Optional[str] = None, machine: Optional[str] = None) -> Dict[str, Any]:
    """The User-Agent and client hints of Chrome ``version`` on this host."""
    import platform

    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    platform_name, token = {
        "Darwin": ("macOS", "Macintosh; Intel Mac OS X 10_15_7"),
        "Windows": ("Windows", "Windows NT 10.0; Win64; x64"),
    }.get(system, ("Linux", "X11; Linux x86_64"))
    major = version.split(".", 1)[0]
    brands = [("Chromium", major), ("Google Chrome", major), ("Not-A.Brand", "99")]
    return {
        "userAgent": (
            f"Mozilla/5.0 ({token}) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{major}.0.0.0 Safari/537.36"
        ),
        "userAgentMetadata": {
            "brands": [{"brand": brand, "version": v} for brand, v in brands],
            "fullVersionList": [
                {"brand": brand, "version": version if v == major else "99.0.0.0"}
                for brand, v in brands
            ],
            "platform": platform_name,
            "platformVersion": "",
            "architecture": "arm" if machine in {"arm64", "aarch64"} else "x86",
            "model": "",
            "mobile": False,
        },
    }
# Tools whose result is what the page actually showed.
_OBSERVATION_TOOLS = frozenset({
    "snapshot", "get_text", "get_attribute", "get_links", "screenshot", "evaluate", "wait_for", "get_cookies",
})
# Roles a person can act on; the snapshot index lists only these.
_INTERACTIVE_ROLES = frozenset({
    "link", "button", "combobox", "textbox", "searchbox", "checkbox", "radio", "menuitem",
    "menuitemcheckbox", "menuitemradio", "tab", "option", "spinbutton", "slider", "switch",
})
_SNAPSHOT_LINE = re.compile(r'^\s*- (\w+)(?: "((?:[^"\\]|\\.)*)")?(.*?)\[ref=((?:f\d+)?e\d+)\]')
_SNAPSHOT_STATE = re.compile(r"\[(disabled|checked|expanded|selected|pressed|aria-hidden)\]")
_TREE_NODE = re.compile(
    r'^(?P<role>[\w-]+)(?: "(?P<name>(?:[^"\\]|\\.)*)")?(?P<flags>(?: \[[^\]]*\])*)(?::(?: (?P<text>.*))?)?$'
)
# Containers read as one line, the way a person reads a sentence or a table row.
_INLINE_ROLES = frozenset({
    "paragraph", "listitem", "row", "cell", "gridcell", "columnheader", "rowheader", "caption",
    "term", "definition", "code", "strong", "emphasis", "time", "status", "option", "blockquote",
})
# Containers whose name tells a person what part of the page they are in.
_NAMED_REGIONS = frozenset({"dialog", "alertdialog", "alert", "form", "region", "navigation", "table", "list"})
_VIEW_REF = re.compile(r"\[(?:f\d+)?e\d+\]")


def _words(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _parse_tree(tree: str) -> list:
    """The ARIA snapshot as nested nodes: (kind, role, name, flags, text, children)."""
    root: list = []
    stack = [(-1, root)]
    for line in tree.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("- "):
            continue
        depth, body = len(line) - len(stripped), stripped[2:]
        if body.startswith("'"):
            # YAML single-quotes a line whose text holds a colon; '' is an escaped quote
            quoted, _, rest = body[1:].rpartition("'")
            body = quoted.replace("''", "'") + rest
        while stack[-1][0] >= depth:
            stack.pop()
        children: list = []
        if body.startswith("/"):
            key, _, value = body[1:].partition(":")
            node = ("property", key, "", "", _unquote(value), children)
        elif body.startswith("text:"):
            node = ("text", "text", "", "", _unquote(body[5:]), children)
        else:
            match = _TREE_NODE.match(body)
            if not match:
                node = ("text", "text", "", "", _unquote(body), children)
            else:
                node = ("element", match["role"], (match["name"] or "").replace('\\"', '"'),
                        match["flags"] or "", _unquote(match["text"] or ""), children)
        stack[-1][1].append(node)
        stack.append((depth, children))
    return root


def _element_label(role: str, name: str, flags: str) -> str:
    ref = re.search(r"\[ref=([^\]]+)\]", flags)
    state = " ".join(_SNAPSHOT_STATE.findall(flags))
    label = f'{role} "{name}"' if name else role
    return f"[{ref.group(1)}] {label}" + (f" ({state})" if state else "") if ref else label


def _inline(node) -> str:
    kind, role, name, flags, text, children = node
    if kind == "property":
        return f"{role}: {text}" if role != "url" and text else ""
    if kind == "text":
        return text
    if role in _INTERACTIVE_ROLES:
        parts = [_element_label(role, name, flags)]
    elif role == "img":
        parts = [f'img "{name}"'] if name else []
    elif role == "row" and children:
        name, parts = "", []  # a row's name joins its cells; read the cells
    else:
        parts = [name] if name else []
    if text and text not in name:
        parts.append(text)
    for child in children:
        rendered = _inline(child)
        if not rendered or rendered == name:
            continue
        if name and _words(rendered) in _words(name) and not _VIEW_REF.search(rendered):
            continue  # the element's name already says it
        parts.append(rendered)
    separator = " | " if role == "row" else " "
    line = separator.join(part for part in parts if part)
    return f"| {line} |" if role == "row" else line


def _index_from_tree(tree: str) -> list[dict[str, str]]:
    """Every interactive element in an ARIA snapshot with its ref, role, name and state."""
    elements = []
    for line in tree.splitlines():
        match = _SNAPSHOT_LINE.match(line)
        if not match or match.group(1) not in _INTERACTIVE_ROLES:
            continue
        role, name, flags, ref = match.groups()
        elements.append({
            "ref": ref, "role": role, "name": (name or "").replace('\\"', '"'),
            "state": " ".join(_SNAPSHOT_STATE.findall(flags)),
        })
    return elements


def _reading_view(tree: str) -> str:
    """The page as a person reads it: its text, with a ref on everything that can be acted on."""
    lines: list[str] = []

    def render(nodes) -> None:
        for node in nodes:
            kind, role, name, flags, text, children = node
            if kind != "element" or role in _INTERACTIVE_ROLES or role in _INLINE_ROLES or role == "img":
                rendered = _inline(node)
                if rendered:
                    lines.append(f"- {rendered}" if role == "listitem" else rendered)
                continue
            if role == "heading":
                level = re.search(r"\[level=(\d)\]", flags)
                lines.append(f"{'#' * int(level.group(1)) if level else '#'} {name or _inline(node)}")
                continue
            if role in _NAMED_REGIONS and (name or role.startswith("alert") or role == "dialog"):
                lines.append(f"[{role}{f' {name!r}' if name else ''}]")
            elif name and text:
                lines.append(f"{name} {text}")
            elif name or text:
                lines.append(name or text)
            render(children)

    render(_parse_tree(tree))
    return "\n".join(lines)


# Puts the values a person approved back on a reopened form; throws if any cannot be.
_RESTORE_FORM = """({action, fields}) => {
    const form = Array.from(document.forms).find(f => f.action === action);
    if (!form) throw new Error('the approved form is not on this page');
    for (const [name, value] of fields) {
        const field = form.elements.namedItem(name);
        if (!field) throw new Error(`the approved field ${name} is not on this page`);
        const choices = field instanceof RadioNodeList ? Array.from(field) : [field];
        const choosable = choices.filter(el => el.type === 'radio' || el.type === 'checkbox');
        if (choosable.length) {
            const chosen = choosable.find(el => el.value === value && !el.disabled);
            if (!chosen) throw new Error(`the approved choice for ${name} is not available`);
            chosen.checked = true;
        } else {
            choices[0].value = value;
            if (choices[0].value !== value) throw new Error(`the approved value for ${name} is not available`);
        }
        for (const el of choices) {
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }
    }
}"""
# What sits over an element's centre, or null when a click would reach it.
_COVERED_BY = """el => {
    const box = el.getBoundingClientRect();
    const top = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    if (!top || top === el || el.contains(top) || top.contains(el)) return null;
    const label = (top.getAttribute('aria-label') || top.innerText || '').trim().slice(0, 80);
    return `${top.tagName.toLowerCase()}${top.id ? '#' + top.id : ''}${label ? ' "' + label + '"' : ''}`;
}"""


class BrowserSubAgent(BaseSubAgent):
    """
    Headless browser automation subagent.

    Requires: pip install playwright && playwright install chromium

    Tools:
    - navigate: Go to a URL and wait for page load
    - click: Click an element by CSS selector or text
    - type_text: Type text into an input field
    - get_text: Extract text from an element or the whole page
    - get_attribute: Get a specific attribute from an element
    - screenshot: Take a screenshot (the model sees the image)
    - wait_for: Wait for an element to appear or disappear
    - evaluate: Run JavaScript on the page
    - get_links: Extract all links from the current page
    - fill_form: Fill multiple form fields at once
    - select_option: Select an option from a <select> dropdown
    - hover: Hover over an element (triggers hover effects)
    - scroll: Scroll the page or a specific element
    - get_cookies: Get current page cookies
    - close_page: Close the current page and open a fresh one
    """

    whole_observation_tools = frozenset({"snapshot", "find", "act"})
    perception_tools = frozenset({"snapshot"})
    #: Seconds between requests to the same site.
    site_interval_s: float = float(os.getenv("BROWSER_SITE_INTERVAL_S", "1.5"))
    #: How long an action may take to finish loading before the agent looks again.
    settle_timeout_ms: int = int(os.getenv("BROWSER_SETTLE_TIMEOUT_MS", "3000"))
    #: Decision confidence at which act() performs the action itself.
    act_min_confidence: float = float(os.getenv("BROWSER_ACT_MIN_CONFIDENCE", "0.7"))
    #: How long a browser stays open for the step's next execution epoch to pick it up.
    continuation_hold_s: float = float(os.getenv("BROWSER_CONTINUATION_HOLD_S", "120"))

    SYSTEM_PROMPT = """\
You are a BROWSER AUTOMATION SPECIALIST in a multi-agent orchestration framework.
Your job: navigate and interact with web pages to extract data or complete tasks.

## CRITICAL RULES

1. **NAVIGATE FIRST** — Always call navigate() before any other interaction.
2. **READ THE PAGE, THEN ACT BY REF** — snapshot() shows the page as a person reads it:
   its text, tables, instructions and notices, with a ref on every element you can act
   on and its state such as (disabled). Follow what the page says about how to use it.
   Act on an element by passing its ref to click, type_text, fill_form or select_option.
   Take a new snapshot after the page changes: refs from an earlier page no longer apply.
3. **LET THE DECISION MODEL PICK WHEN IT IS AVAILABLE** — once you know what to do,
   act(goal, action) with action click, type or select finds the element and acts in
   one step; it suits reversible steps. When it returns needs_choice, pick a ref from
   its candidates. find(goal) returns the ref without acting.
4. **READ WHAT THE SNAPSHOT SHOWS** — answers come from the page text in the snapshot;
   use get_text or evaluate only for what it does not show.
5. **RESPECT ACCESS** — navigate() may report access.denied: the site turned the browser
   away. Do not route around it through search engines or other copies of the site;
   report what was blocked.
6. **HANDLE ERRORS** — An element that is disabled, hidden or covered is reported at once
   with the reason; deal with the cause (for example accept a cookie banner) or choose
   another element.
7. **NO LOOPS** — Do not retry the same action more than twice; try a different approach.
8. **DONE WITH EVIDENCE** — Your DONE summary must include the extracted data or
   a clear statement of what action was completed, as the page showed it in this run.
9. **IRREVERSIBLE ACTIONS WAIT FOR THE PERSON** — Before an action that commits the
   person or cannot be undone (placing an order, paying, booking, submitting an
   application or form to an organisation, sending a message, deleting, publishing),
   add `"irreversible": true` and `"consequence": "<what will happen>"` to that
   tool's PARAMS and call it. That call is how the person is asked: the runtime
    pauses and shows them the consequence; it does NOT perform the action.
    When they approve, JarvisCore performs exactly that action as the step resumes
    and records its receipt; observe the outcome on the page before finishing and
    never repeat it. When they decline, do not attempt it; report that it was not done.
    Do not stop short or report the action as blocked for lack of
   approval; issue the flagged call. Browsing, searching, signing in, adding to a
   basket and filling a form without submitting it are reversible.
   Example: TOOL: click / PARAMS: {"text": "Place order", "irreversible": true,
   "consequence": "Places the order for 1 backpack and charges £29.99"}

## WORKFLOW

1. navigate(url)
2. snapshot() → read the page
3. act by ref, or act(goal, action)
4. snapshot() after the page changes
5. DONE with findings
"""

    def __init__(
        self,
        agent_id: str,
        llm_client,
        headless: bool = True,
        viewport: Optional[Dict] = None,
        redis_store=None,
        blob_storage=None,
        profile_root: Optional[str] = None,
        scope_field: Optional[str] = None,
        control_url: Optional[str] = None,
    ):
        self.headless = headless
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.profile_root = profile_root
        self.scope_field = scope_field
        self.control_url = control_url

        # Playwright objects — initialized in _pre_run_hook, closed in _post_run_hook
        self._playwright = None
        self._browser: Optional["Browser"] = None
        self._context: Optional["BrowserContext"] = None
        self._page: Optional["Page"] = None
        self._current_url: str = ""
        self._attached = False
        self._profile_lock: Optional[asyncio.Lock] = None
        self._launch_error = ""
        self._identity: Dict[str, Any] = {}
        self._relocated: Dict[str, str] = {}
        # (workflow_id, step_id) whose next execution epoch may continue in the open browser
        self._held_for: Optional[tuple] = None
        self._hold_expiry: Optional[asyncio.TimerHandle] = None

        super().__init__(
            agent_id=agent_id,
            role="browser",
            llm_client=llm_client,
            redis_store=redis_store,
            blob_storage=blob_storage,
        )

    def get_system_prompt(self) -> str:
        return self.SYSTEM_PROMPT

    def setup_tools(self) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            # Register a single stub tool that explains how to install Playwright
            self.register_tool(
                "install_required",
                self._tool_install_required,
                "Playwright not installed. Params: {}",
                phase="thinking",
            )
            return

        self.register_tool(
            "navigate",
            self._tool_navigate,
            'Go to a URL. Params: {"url": "<url>", "wait_for": "networkidle|domcontentloaded|load"}',
            phase="action",
        )
        self.register_tool(
            "snapshot",
            self._tool_snapshot,
            'The page as a person reads it: headings, text, tables as rows, notices and dialogs, '
            'with "[<ref>] <role> \\"<name>\\"" on everything you can act on and states like '
            '(disabled). Act on elements by ref. Params: {}',
            phase="thinking",
        )
        self.register_tool(
            "click",
            self._tool_click,
            'Click an element. Params: {"ref": "<snapshot ref>"} or {"selector": "<css>"} or {"text": "<visible text>"}',
            phase="action",
        )
        self.register_tool(
            "type_text",
            self._tool_type_text,
            'Type text into an input. Params: {"ref": "<snapshot ref>" or "selector": "<css>", "text": "<text>", "clear_first": true}',
            phase="action",
        )
        self.register_tool(
            "get_text",
            self._tool_get_text,
            'Get text from an element or page. Params: {"ref": "<snapshot ref>" or "selector": "<css>", or neither for the full page; "max_chars": 5000}',
            phase="thinking",
        )
        self.register_tool(
            "get_attribute",
            self._tool_get_attribute,
            'Get an attribute from an element. Params: {"selector": "<css>", "attribute": "<attr>"}',
            phase="thinking",
        )
        self.register_tool(
            "screenshot",
            self._tool_screenshot,
            "Take a screenshot of the current page. Params: {}",
            phase="thinking",
        )
        self.register_tool(
            "wait_for",
            self._tool_wait_for,
            'Wait for an element. Params: {"selector": "<css>", "timeout_ms": 5000, "state": "visible|hidden|attached|detached"}',
            phase="thinking",
        )
        self.register_tool(
            "evaluate",
            self._tool_evaluate,
            'Run JavaScript on the page. Params: {"script": "<js expression>"}',
            phase="action",
        )
        self.register_tool(
            "get_links",
            self._tool_get_links,
            'Get all links from the page. Params: {"selector": "<optional css to scope>", "max": 50}',
            phase="thinking",
        )
        self.register_tool(
            "fill_form",
            self._tool_fill_form,
            'Fill multiple form fields. Params: {"fields": [{"ref": "<snapshot ref>" or "selector": "<css>", "value": "<text>"}]}',
            phase="action",
        )
        self.register_tool(
            "select_option",
            self._tool_select_option,
            'Select a dropdown option. Params: {"ref": "<snapshot ref>" or "selector": "<css>", "value": "<option value or label>"}',
            phase="action",
        )
        self.register_tool(
            "scroll",
            self._tool_scroll,
            'Scroll the page. Params: {"direction": "down|up|top|bottom", "pixels": 500}',
            phase="action",
        )
        self.register_tool(
            "get_cookies",
            self._tool_get_cookies,
            "Get all cookies for the current page. Params: {}",
            phase="thinking",
        )
        self.register_tool(
            "close_page",
            self._tool_close_page,
            "Close current page and open a fresh one. Params: {}",
            phase="action",
        )

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle — open/close browser per run()
    # ──────────────────────────────────────────────────────────────────────

    def _can_complete(self, state, parsed: Dict[str, Any]):
        """A browser result reports what the browser showed in this run.

        When every attempt to use the browser failed, those recorded failures
        are the evidence and an honest report of them may complete.
        """
        ok, reason = super()._can_complete(state, parsed)
        if not ok:
            return ok, reason
        attempts = [t for t in state.tool_history if t.tool_name in self._tools and t.tool_name != "read_turn_result"]
        observed = any(t.status == "success" and t.tool_name in _OBSERVATION_TOOLS for t in attempts)
        all_failed = bool(attempts) and not any(t.status == "success" for t in attempts)
        if observed or all_failed:
            return True, None
        return False, GateEvidence(
            check="browser_observation",
            requirement=(
                "a browser result rests on what the page showed in this run; observe it "
                "(get_text, screenshot, get_attribute, ...) before DONE"
            ),
            observed={"tools_used": sorted({t.tool_name for t in attempts})},
        )

    def _approved_action_params(self, action: HITLAction) -> Dict[str, Any]:
        params = dict(action.params)
        if "ref" in params:
            params["ref"] = self._relocated.get(action.action_id, params["ref"])
        return {**params, "irreversible": True, "consequence": action.consequence}

    async def _approved_action_applies(self, action: HITLAction) -> bool:
        """The element the person approved is still where they approved it.

        A snapshot ref names an element only on the page it was taken from, so
        an action proposed by ref is found again by what it touches.
        """
        if not self._page:
            return False
        if action.location.startswith(("http://", "https://")):
            try:
                await self._page.goto(action.location, wait_until="domcontentloaded")
            except Exception as exc:
                logger.info("[browser] Approved action page did not reopen: %s", exc)
                return False
            # A reopened page has lost what was entered; the person approved those values.
            element = (action.target or {}).get("element") or {}
            if element.get("form") and element.get("fields"):
                try:
                    await self._page.evaluate(_RESTORE_FORM, {"action": element["form"], "fields": element["fields"]})
                except Exception as exc:
                    logger.info("[browser] Approved form values could not be restored: %s", exc)
                    return False
        context = getattr(getattr(self, "_current_state", None), "context", None) or {}
        if "ref" not in action.params:
            target = await self._action_target(action.tool, dict(action.params))
            return target is not None and self.action_id(context, action.tool, target) == action.action_id
        for element in await self._index():
            target = await self._action_target(action.tool, {**action.params, "ref": element["ref"]})
            if target is not None and self.action_id(context, action.tool, target) == action.action_id:
                self._relocated[action.action_id] = element["ref"]
                return True
        return False

    @staticmethod
    def action_id(context: Dict[str, Any], tool_name: str, target: Any) -> str:
        """One approval covers this exact action in this step, across a resume."""
        identity = {
            "workflow_id": context.get("workflow_id"),
            "step_id": context.get("step_id"),
            "tool": tool_name,
            "target": target,
        }
        return hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode()).hexdigest()

    async def _fingerprint(self, selector: str = "", text: str = "", ref: str = "") -> Optional[Dict[str, Any]]:
        if ref:
            locator = self._ref(ref)
        else:
            locator = (
                self._page.get_by_text(text, exact=False).first
                if text and not selector
                else self._page.locator(selector).first
            )
        return await locator.evaluate(
            "el => ({tag: el.tagName, id: el.id, name: el.getAttribute('name'), "
            "type: el.getAttribute('type'), text: (el.innerText || el.value || '').trim(), "
            "form: el.form ? el.form.action : null, method: el.form ? el.form.method : null, "
            "fields: el.form ? Array.from(el.form.elements).filter(f => f.name && !f.disabled "
            "&& !['hidden','submit','button','reset','image','file'].includes(f.type) "
            "&& (!['radio','checkbox'].includes(f.type) || f.checked)).map(f => [f.name, String(f.value)]) : null})",
            timeout=5000,
        )

    @staticmethod
    def _describe_action(tool_name: str, params: Dict[str, Any], target: Any, where: str) -> str:
        """What the person is approving, in their words: verb, visible label, page."""
        from urllib.parse import urlsplit

        element = (target or {}).get("element") if isinstance(target, dict) else None
        label = str((element or {}).get("text") or params.get("text") or "").strip()
        verb = {
            "click": "Click", "type_text": "Type into", "fill_form": "Fill in",
            "select_option": "Choose an option in", "evaluate": "Run a script on",
        }.get(tool_name, tool_name.replace("_", " ").capitalize())
        page = urlsplit(where)
        place = f"{page.netloc}{page.path}" if page.netloc else where
        if tool_name == "click" and label:
            return f"{verb} “{label[:80]}” on {place}"
        return f"{verb} {place}"

    async def _action_target(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """What this action would really touch, however the agent named it.

        Two wordings for the same button on the same page are one action, so
        an approval survives the agent re-describing it after a resume.
        """
        if not self._page:
            return params
        try:
            from urllib.parse import urlsplit

            page = urlsplit(self._page.url)
            where = f"{page.scheme}://{page.netloc}{page.path}"
            if tool_name == "click":
                element = await self._fingerprint(
                    params.get("selector", ""), params.get("text", ""), params.get("ref", "")
                )
                return {"page": (element or {}).get("form") or where, "element": element}
            if tool_name in {"type_text", "select_option"}:
                element = await self._fingerprint(params.get("selector", ""), ref=params.get("ref", ""))
                return {"page": where, "element": element, "value": params.get("text", params.get("value"))}
            if tool_name == "fill_form":
                fields = [
                    {
                        "element": await self._fingerprint(field.get("selector", ""), ref=field.get("ref", "")),
                        "value": field.get("value"),
                    }
                    for field in params.get("fields") or []
                ]
                return {"page": where, "fields": fields}
            return {"page": where, "params": params}
        except Exception:
            return None

    async def _execute_tool(self, tool_name: str, params: Dict) -> Dict[str, Any]:
        params = dict(params)
        if tool_name == "act" and params.get("irreversible") is True:
            return {
                "status": "error",
                "error": (
                    "act() never performs an irreversible action: a person approves an exact "
                    "element. Use find() for its ref, then click/type_text with that ref and "
                    "irreversible plus consequence."
                ),
                "semantic_error": "IRREVERSIBLE_NEEDS_EXACT_ELEMENT",
            }
        irreversible = params.pop("irreversible", False) is True
        consequence = str(params.pop("consequence", "") or "").strip()
        if irreversible and tool_name in _COMMITTING_TOOLS:
            if not consequence:
                return {
                    "status": "error",
                    "error": "Say in `consequence` what this action will do, so the person can decide.",
                    "semantic_error": "CONSEQUENCE_REQUIRED",
                }
            context = getattr(getattr(self, "_current_state", None), "context", None) or {}
            target = await self._action_target(tool_name, params)
            if target is None:
                return {
                    "status": "error",
                    "error": (
                        f"The element for this action is not on the current page "
                        f"({self._page.url if self._page else 'no page'}). Open the page it is on first."
                    ),
                    "semantic_error": "ACTION_TARGET_NOT_FOUND",
                }
            action_id = self.action_id(context, tool_name, target)
            where = self._page.url if self._page else "the current page"
            action = HITLAction(
                action_id=action_id,
                tool=tool_name,
                system="browser",
                params=params,
                description=self._describe_action(tool_name, params, target, where),
                consequence=consequence,
                location=where,
                target=target if isinstance(target, dict) else {},
            )
            workflow_id, step_id = context.get("workflow_id"), context.get("step_id")
            refusal = approval.gate(self.redis_store, workflow_id, step_id, action)
            if refusal is not None:
                return refusal
            result = await super()._execute_tool(tool_name, params)
            approval.settle(self.redis_store, workflow_id, step_id, action_id, result)
            self._record_reached(tool_name, result)
            return result
        result = await super()._execute_tool(tool_name, params)
        self._record_reached(tool_name, result)
        return result

    def _record_reached(self, tool_name: str, result: Any) -> None:
        """A page an action led to is progress, whether or not it has been read yet."""
        if (
            tool_name in _COMMITTING_TOOLS | {"navigate", "act"}
            and isinstance(result, dict)
            and result.get("status") == "success"
            and self._page is not None
        ):
            self._record_observed_state(self._page.url, "")

    def profile_dir(self, context: Optional[Dict[str, Any]]) -> Optional[str]:
        """Where this run's tenant keeps its browser profile, if anywhere.

        A mesh that separates tenants and a step that names none gets a fresh
        browser: one person's logins are never lent to another.
        """
        if not self.profile_root:
            return None
        if self.scope_field:
            scope = str((context or {}).get(self.scope_field) or "").strip()
            if not scope:
                return None
        else:
            scope = "default"
        return os.path.join(self.profile_root, hashlib.sha256(scope.encode()).hexdigest()[:32])

    async def _pre_run_hook(self, state) -> None:
        """Open the browser this run works in before the OODA loop starts."""
        if getattr(self, "decision_client", None) is not None and "find" not in self._tools:
            self.register_tool(
                "find",
                self._tool_find,
                'Pick the element that accomplishes a goal, in under a second, with the decision model. '
                'Returns its ref, confidence and the closest alternatives. Params: {"goal": "<what to act on>"}',
                phase="thinking",
            )
            self.register_tool(
                "act",
                self._tool_act,
                'Find the element for a goal and click, type into or select it in one step. When the '
                'choice is unclear it returns candidates instead of acting. Never for irreversible '
                'actions. Params: {"goal": "<what to act on>", "action": "click|type|select", '
                '"text": "<for type>", "value": "<for select>"}',
                phase="action",
            )
        if not PLAYWRIGHT_AVAILABLE:
            return
        if self._held_for is not None:
            context = getattr(state, "context", None) or {}
            continuing = (
                context.get("_new_execution_epoch")
                and self._held_for == (context.get("workflow_id"), context.get("step_id"))
                and self._page is not None
                and not self._page.is_closed()
            )
            self._release_hold()
            if continuing:
                logger.info("[browser] Continuing in the open browser at %s", self._page.url)
                return
            await self._post_run_hook()
        args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ]
        self._launch_error = ""
        try:
            self._playwright = await async_playwright().start()
            profile = None if self.control_url else self.profile_dir(getattr(state, "context", None))
            if self.control_url:
                self._browser = await self._playwright.chromium.connect_over_cdp(self.control_url)
                self._attached = True
                self._context = (
                    self._browser.contexts[0]
                    if self._browser.contexts
                    else await self._browser.new_context(viewport=self.viewport)
                )
                self._page = await self._context.new_page()
            elif profile:
                # Chromium locks a profile to one process; runs for the same
                # tenant in this process take turns instead of failing.
                self._profile_lock = _PROFILE_LOCKS.setdefault(profile, asyncio.Lock())
                await self._profile_lock.acquire()
                os.makedirs(profile, mode=0o700, exist_ok=True)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    profile,
                    headless=self.headless,
                    args=args,
                    viewport=self.viewport,
                )
                self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            else:
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=args,
                )
                self._context = await self._browser.new_context(
                    viewport=self.viewport,
                    java_script_enabled=True,
                )
                self._page = await self._context.new_page()
            if not self._attached:
                await self._present_as_browser()
            logger.info(
                "[browser] Browser ready (mode=%s, headless=%s)",
                "shared" if self._attached else "persistent" if profile else "fresh",
                self.headless,
            )
        except Exception as e:
            logger.error("[browser] Failed to open browser: %s", e)
            self._launch_error = str(e)
            await self._post_run_hook()

    async def _present_as_browser(self) -> None:
        """Identify as the Chrome that is actually running, on the OS it runs on.

        Headless Chromium announces itself as ``HeadlessChrome``; sites behind
        bot defences deny it outright. The real version and platform, given
        consistently in the header and the client hints, are what a person's
        browser sends.
        """
        session = await self._context.new_cdp_session(self._page)
        product = (await session.send("Browser.getVersion"))["product"]
        await session.detach()
        self._identity = browser_identity(product.split("/", 1)[1])
        await self._identify(self._page)
        self._context.on("page", lambda page: asyncio.ensure_future(self._identify(page)))

    async def _identify(self, page) -> None:
        session = await self._context.new_cdp_session(page)
        await session.send("Network.setUserAgentOverride", self._identity)

    async def _post_run_hook(self) -> None:
        """Close what this run opened; a shared browser stays open."""
        try:
            if self._page:
                await self._page.close()
            if self._context and not self._attached:
                await self._context.close()
            if self._browser and not self._attached:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug("[browser] Cleanup error (non-fatal): %s", e)
        finally:
            if self._profile_lock is not None and self._profile_lock.locked():
                self._profile_lock.release()
            self._profile_lock = None
            self._attached = False
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    def _ensure_page(self) -> Optional[Dict]:
        """Return error dict if browser not ready, None if ready."""
        if not self._page:
            return {
                "status": "error",
                "error": (
                    f"The browser could not be opened: {self._launch_error}"
                    if self._launch_error
                    else "Browser not initialized. Try: pip install playwright && playwright install chromium"
                ),
            }
        return None

    # ──────────────────────────────────────────────────────────────────────
    # Stub tool (no Playwright)
    # ──────────────────────────────────────────────────────────────────────

    async def _tool_install_required(self, **kwargs) -> Dict[str, Any]:
        return {
            "status": "error",
            "error": (
                "Playwright is not installed. "
                "Install it with: pip install playwright && playwright install chromium\n"
                "This task cannot be completed without a browser. "
                "Consider using the researcher's web_search or read_url tools instead."
            ),
        }

    # ──────────────────────────────────────────────────────────────────────
    # Tools
    # ──────────────────────────────────────────────────────────────────────

    async def _tool_navigate(
        self,
        url: str,
        wait_for: str = "networkidle",
        timeout_ms: int = 30000,
        **kwargs,
    ) -> Dict[str, Any]:
        """Navigate to a URL."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            await self._pace(url)
            response = await self._page.goto(
                url,
                wait_until=wait_for,
                timeout=timeout_ms,
            )
            self._current_url = self._page.url
            title = await self._page.title()
            result = {
                "status": "success",
                "url": self._current_url,
                "title": title,
                "http_status": response.status if response else None,
            }
            access = await self._judge_access(url, result["http_status"], title)
            if access is not None:
                result["access"] = access
            return result
        except Exception as e:
            return {"status": "error", "error": str(e), "url": url}

    async def _pace(self, url: str) -> None:
        """Space requests to one site the way a person's browsing is spaced."""
        from urllib.parse import urlsplit

        site = urlsplit(url).netloc
        loop = asyncio.get_running_loop()
        last = _LAST_VISIT.get(site)
        if last is not None:
            wait = self.site_interval_s - (loop.time() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        _LAST_VISIT[site] = loop.time()

    async def _judge_access(self, url: str, http_status: Optional[int], title: str) -> Optional[Dict[str, Any]]:
        """Whether the site served the page or turned the browser away, as evidence."""
        if getattr(self, "decision_client", None) is None:
            return None
        try:
            text = await self._page.evaluate(
                f"() => ({_READ_WITH_FIELDS})(document.body, true)"
            )
            result = await self.decision_client.evaluate(
                state=(
                    f"Requested: {url}\nLanded: {self._page.url}\nHTTP status: {http_status}\n"
                    f"Title: {title}\nPage text:\n{str(text).strip()}"
                ),
                questions={"denied": {
                    "type": "noul",
                    "instructions": (
                        "Did the site refuse to serve the requested content to this browser "
                        "(an access block, bot check or captcha) instead of showing it?"
                    ),
                }},
            )
        except Exception as exc:
            logger.info("[browser] Access judgement unavailable: %s", exc)
            return None
        denied = float(result.answers["denied"]["noul"])
        return {
            "denied": denied >= 0.5,
            "probability": round(denied, 3),
            "decision_request_id": result.request_id,
        }

    async def _settle(self) -> None:
        """Let what an action started finish loading before the next observation."""
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=self.settle_timeout_ms)
            await self._page.wait_for_load_state("networkidle", timeout=self.settle_timeout_ms)
        except Exception as exc:  # a page that keeps a connection open is still usable
            logger.debug("[browser] Page did not settle within %sms: %s", self.settle_timeout_ms, exc)

    async def _tool_click(
        self,
        selector: str = "",
        text: str = "",
        ref: str = "",
        timeout_ms: int = 10000,
        **kwargs,
    ) -> Dict[str, Any]:
        """Click an element by snapshot ref, CSS selector or visible text."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if ref:
                locator, refusal = await self._actionable(ref)
                if refusal:
                    return refusal
                await locator.click(timeout=timeout_ms)
            elif text and not selector:
                # Text-based click
                await self._page.get_by_text(text, exact=False).first.click(timeout=timeout_ms)
            elif selector:
                await self._page.click(selector, timeout=timeout_ms)
            else:
                return {"status": "error", "error": "One of ref, selector or text is required"}
            await self._settle()
            return {"status": "success", "url": self._page.url}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_type_text(
        self,
        selector: str = "",
        text: str = "",
        ref: str = "",
        clear_first: bool = True,
        delay_ms: int = 50,
        **kwargs,
    ) -> Dict[str, Any]:
        """Type text into an input field."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if ref:
                locator, refusal = await self._actionable(ref)
                if refusal:
                    return refusal
            elif selector:
                locator = self._page.locator(selector).first
            else:
                return {"status": "error", "error": "One of ref or selector is required"}
            if clear_first:
                await locator.fill("", timeout=10000)
            await locator.press_sequentially(text, delay=delay_ms)
            await self._settle()
            return {"status": "success", "target": ref or selector, "chars_typed": len(text)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_get_text(
        self,
        selector: str = "",
        max_chars: int = 5000,
        ref: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Extract text from an element or the full page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if ref or selector:
                element = self._ref(ref) if ref else self._page.locator(selector).first
                text = await element.evaluate(_READ_WITH_FIELDS, False, timeout=10000)
            else:
                text = await self._page.evaluate(
                    f"() => ({_READ_WITH_FIELDS})(document.body, true)"
                )
            text = str(text).strip()
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars] + "\n... [truncated]"
            return {
                "status": "success",
                "text": text,
                "char_count": len(text),
                "truncated": truncated,
                "url": self._page.url,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _ref(self, ref: str):
        return self._page.locator(f"aria-ref={ref}")

    async def _actionable(self, ref: str):
        """The element behind ``ref``, or the reason it cannot be acted on now."""
        locator = self._ref(ref)
        try:
            if await locator.count() == 0:
                reason = "is not on the current page; take a new snapshot"
            elif await locator.is_disabled():
                reason = "is disabled"
            elif not await locator.is_visible():
                reason = "is not visible"
            else:
                await locator.scroll_into_view_if_needed(timeout=2000)
                cover = await locator.evaluate(_COVERED_BY)
                if not cover:
                    return locator, None
                reason = f"is covered by {cover}; deal with that first"
        except Exception as exc:
            reason = f"could not be resolved ({exc})"
        return locator, {
            "status": "error",
            "error": f"Element {ref} {reason}.",
            "semantic_error": "ELEMENT_NOT_ACTIONABLE",
            "performed": False,
        }

    async def _index(self) -> List[Dict[str, str]]:
        """Every interactive element on the page with its ref, role, name and state."""
        return _index_from_tree(await self._page.locator("body").aria_snapshot(mode="ai"))

    async def _tool_snapshot(self, ref: str = "", **kwargs) -> Dict[str, Any]:
        """The page, or one region of it, as a person reads it, with refs on what can be acted on."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if ref:
                region = _reading_view(await self._ref(ref).aria_snapshot(mode="ai"))
                return {"status": "success", "url": self._page.url, "region": region}
            view = _reading_view(await self._page.locator("body").aria_snapshot(mode="ai"))
            self._record_observed_state(self._page.url, view)
            return {
                "status": "success",
                "url": self._page.url,
                "title": await self._page.title(),
                "page": view,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _record_observed_state(self, url: str, listing: str) -> None:
        """A page state not seen before is progress; revisiting known states is not."""
        variables = getattr(getattr(self, "_current_state", None), "internal_variables", None)
        if variables is None:
            return
        digest = hashlib.sha256(f"{url}\n{listing}".encode()).hexdigest()[:16]
        observed = variables.setdefault("_observed_states", [])
        if digest not in observed:
            observed.append(digest)

    async def _tool_find(self, goal: str, **kwargs) -> Dict[str, Any]:
        """Choose the element that accomplishes ``goal`` with the decision model."""
        err = self._ensure_page()
        if err:
            return err
        try:
            elements = [e for e in await self._index() if "disabled" not in e["state"]]
            if not elements:
                return {"status": "error", "error": "No actionable elements are on this page."}
            result = await self.decision_client.evaluate(
                state=f"Page: {await self._page.title()} ({self._page.url})\nGoal: {goal}",
                questions={"element": {
                    "type": "choice",
                    "instructions": "Which page element should be acted on to accomplish the goal?",
                    "criteria": {
                        e["ref"]: f"{e['role']} \"{e['name']}\"" + (f" ({e['state']})" if e["state"] else "")
                        for e in elements
                    },
                }},
            )
        except Exception as e:
            return {"status": "error", "error": str(e)}
        answer = result.answers["element"]
        by_ref = {e["ref"]: e for e in elements}
        ranked = sorted(answer["probabilities"].items(), key=lambda item: item[1], reverse=True)
        return {
            "status": "success",
            "ref": answer["choice"],
            "element": by_ref.get(answer["choice"]),
            "confidence": answer["confidence"],
            "alternatives": [
                {**by_ref[ref], "probability": round(p, 3)}
                for ref, p in ranked[1:4] if ref in by_ref
            ],
            "decision_request_id": result.request_id,
        }

    async def _tool_act(
        self, goal: str, action: str = "click", text: str = "", value: str = "", **kwargs,
    ) -> Dict[str, Any]:
        """Find the element for ``goal`` and act on it in one turn when the choice is clear."""
        tools = {"click": "click", "type": "type_text", "select": "select_option"}
        if action not in tools:
            return {"status": "error", "error": "action must be click, type or select"}
        found = await self._tool_find(goal)
        if found.get("status") != "success":
            return found
        if found["confidence"] < self.act_min_confidence or found["element"] is None:
            return {
                "status": "needs_choice",
                "note": "The element for this goal is not clear; choose a ref yourself and act on it.",
                "candidates": [found["element"], *found["alternatives"]],
                "confidence": found["confidence"],
            }
        params = {"ref": found["ref"]}
        if action == "type":
            params["text"] = text
        elif action == "select":
            params["value"] = value
        element = found["element"]
        try:
            verdict = await self.decision_client.evaluate(
                state=(
                    f"Page: {await self._page.title()} ({self._page.url})\n"
                    f"Element: {element['role']} \"{element['name']}\"\nAction: {action}"
                    + (f" \"{text or value}\"" if text or value else "")
                ),
                questions={"commits": {
                    "type": "noul",
                    "instructions": (
                        "Would this action commit the person or be hard to undo, such as placing "
                        "an order, paying, booking, sending, submitting, publishing or deleting?"
                    ),
                }},
            )
            commits = float(verdict.answers["commits"]["noul"])
        except Exception as exc:
            return {"status": "error", "error": f"Could not judge whether this action commits the person: {exc}"}
        if commits >= 0.5:
            return {
                "status": "error",
                "error": (
                    f"{element['role']} \"{element['name']}\" ({found['ref']}) looks consequential; "
                    "act() never performs it. If it is what the goal needs, call click/type_text "
                    "with this ref, irreversible and consequence so the person can decide."
                ),
                "semantic_error": "CONSEQUENTIAL_ACTION",
                "ref": found["ref"],
                "commits_probability": round(commits, 3),
            }
        outcome = await self._execute_tool(tools[action], params)
        return {
            **outcome,
            "acted_on": found["element"],
            "confidence": found["confidence"],
            "decision_request_id": found["decision_request_id"],
        }

    async def _tool_get_attribute(
        self,
        selector: str,
        attribute: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Get an attribute value from an element."""
        err = self._ensure_page()
        if err:
            return err
        try:
            value = await self._page.get_attribute(selector, attribute, timeout=10000)
            return {
                "status": "success",
                "selector": selector,
                "attribute": attribute,
                "value": value,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_screenshot(
        self,
        full_page: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """Take a screenshot of the current page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            png_bytes = await self._page.screenshot(full_page=full_page)
            title = await self._page.title()
            return {
                "status": "success",
                "url": self._page.url,
                "title": title,
                OBSERVED_IMAGES: [
                    Image(data=png_bytes, media_type="image/png", label=f"Screenshot of {self._page.url}")
                ],
                "note": "The screenshot is attached to this observation as an image.",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_wait_for(
        self,
        selector: str,
        timeout_ms: int = 10000,
        state: str = "visible",
        **kwargs,
    ) -> Dict[str, Any]:
        """Wait for an element to reach the specified state."""
        err = self._ensure_page()
        if err:
            return err
        try:
            await self._page.wait_for_selector(
                selector,
                state=state,
                timeout=timeout_ms,
            )
            return {"status": "success", "selector": selector, "state": state}
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "selector": selector,
                "hint": "Element not found. Check selector with screenshot().",
            }

    async def _tool_evaluate(
        self,
        script: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute JavaScript on the page and return the result."""
        err = self._ensure_page()
        if err:
            return err
        try:
            result = await self._page.evaluate(script)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_get_links(
        self,
        selector: str = "",
        max: int = 50,
        **kwargs,
    ) -> Dict[str, Any]:
        """Extract all links from the current page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            scope = f"'{selector} a'" if selector else "'a'"
            links = await self._page.evaluate(f"""() => {{
                const anchors = Array.from(document.querySelectorAll({scope}));
                return anchors.slice(0, {max}).map(a => ({{
                    text: a.innerText.trim().slice(0, 100),
                    href: a.href,
                    title: a.title || ''
                }})).filter(l => l.href && l.href.startsWith('http'));
            }}""")
            return {"status": "success", "links": links, "count": len(links)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_fill_form(
        self,
        fields: List[Dict[str, str]],
        **kwargs,
    ) -> Dict[str, Any]:
        """Fill multiple form fields at once."""
        err = self._ensure_page()
        if err:
            return err
        results = []
        for field in fields:
            ref = field.get("ref", "")
            selector = field.get("selector", "")
            target = ref or selector
            value = field.get("value", "")
            if not target:
                results.append({"target": target, "status": "error", "error": "No ref or selector"})
                continue
            try:
                if ref:
                    locator, refusal = await self._actionable(ref)
                    if refusal:
                        results.append({"target": ref, **refusal})
                        continue
                    await locator.fill(value, timeout=10000)
                else:
                    await self._page.fill(selector, value, timeout=10000)
                results.append({"target": target, "status": "success"})
            except Exception as e:
                results.append({"target": target, "status": "error", "error": str(e)})
        success_count = sum(1 for r in results if r["status"] == "success")
        return {
            "status": "success" if success_count == len(fields) else "partial",
            "filled": success_count,
            "total": len(fields),
            "results": results,
        }

    async def _tool_select_option(
        self,
        selector: str = "",
        value: str = "",
        ref: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Select an option from a <select> dropdown."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if ref:
                locator, refusal = await self._actionable(ref)
                if refusal:
                    return refusal
            else:
                locator = self._page.locator(selector).first
            # Try by value first, then by label
            selected = await locator.select_option(value=value, timeout=10000)
            if not selected:
                selected = await locator.select_option(label=value, timeout=10000)
            return {"status": "success", "target": ref or selector, "selected": selected}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_scroll(
        self,
        direction: str = "down",
        pixels: int = 500,
        selector: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Scroll the page or a specific element."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if direction == "top":
                await self._page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "up":
                await self._page.evaluate(f"window.scrollBy(0, -{pixels})")
            else:  # down
                await self._page.evaluate(f"window.scrollBy(0, {pixels})")
            await asyncio.sleep(0.3)
            return {"status": "success", "direction": direction, "pixels": pixels}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_get_cookies(self, **kwargs) -> Dict[str, Any]:
        """Get all cookies for the current page."""
        err = self._ensure_page()
        if err:
            return err
        try:
            cookies = await self._context.cookies()
            # Sanitize — don't leak httpOnly/secure flags values
            safe_cookies = [
                {"name": c["name"], "domain": c["domain"], "path": c["path"]}
                for c in cookies
            ]
            return {"status": "success", "count": len(safe_cookies), "cookies": safe_cookies}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def _tool_close_page(self, **kwargs) -> Dict[str, Any]:
        """Close the current page and open a fresh one."""
        err = self._ensure_page()
        if err:
            return err
        try:
            await self._page.close()
            self._page = await self._context.new_page()
            self._current_url = ""
            return {"status": "success", "message": "Fresh page opened. Call navigate() next."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ──────────────────────────────────────────────────────────────────────
    # Run override — ensure browser is always closed even on exception
    # ──────────────────────────────────────────────────────────────────────

    async def run(self, task, context=None, max_turns=20, model=None, **kwargs):
        """Run with browser lifecycle management; the base loop opens it with state.

        A run that ends because its execution epoch ran out leaves the browser open
        for the step's next epoch, which continues on the same page.
        """
        output = None
        try:
            output = await super().run(task, context, max_turns, model, **kwargs)
            return output
        finally:
            if getattr(output, "status", None) == "epoch_exhausted" and self._page is not None:
                self._hold((context or {}).get("workflow_id"), (context or {}).get("step_id"))
            else:
                await self._post_run_hook()

    def _hold(self, workflow_id, step_id) -> None:
        self._held_for = (workflow_id, step_id)
        loop = asyncio.get_running_loop()
        self._hold_expiry = loop.call_later(
            self.continuation_hold_s, lambda: asyncio.ensure_future(self._expire_hold()),
        )

    def _release_hold(self) -> None:
        if self._hold_expiry is not None:
            self._hold_expiry.cancel()
        self._hold_expiry = None
        self._held_for = None

    async def _expire_hold(self) -> None:
        """The continuation never came: close what was held open for it."""
        if self._held_for is not None:
            self._release_hold()
            await self._post_run_hook()

    async def teardown(self) -> None:
        self._release_hold()
        await self._post_run_hook()
