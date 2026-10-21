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
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from jarviscore.contracts.hitl import HITLAction
from jarviscore.core.egress import Egress
from jarviscore.kernel.gate import GateEvidence
from jarviscore.execution.multimodal import OBSERVED_IMAGES, Image
from jarviscore.kernel import approval
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
_COMMITTING_TOOLS = frozenset({"click", "type_text", "fill_form", "select_option"})


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
_TREE_REF = re.compile(r"\[ref=([^\]]+)\]")


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
    shown = label + (f" ({state})" if state else "")
    return f"[{ref.group(1)}] {shown}" if ref else shown


def _clickable(role: str, flags: str) -> bool:
    """An element the agent can act on: an interactive role, or one the page gives a pointer cursor."""
    return role in _INTERACTIVE_ROLES or ("[cursor=pointer]" in flags and "[ref=" in flags)


def _inline(node) -> str:
    kind, role, name, flags, text, children = node
    if kind == "property":
        return f"{role}: {text}" if role != "url" and text else ""
    if kind == "text":
        return text
    if role == "row" and children:
        # A row's name joins its cells; read the cells.
        ref = _TREE_REF.search(flags)
        name, parts = "", [f"[{ref.group(1)}] row"] if ref and _clickable(role, flags) else []
    elif _clickable(role, flags):
        parts = [_element_label(role, name, flags)]
    elif role == "img":
        parts = [f'img "{name}"'] if name else []
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
            if _clickable(role, flags):
                # A clickable container keeps its structure: its label, then what it holds.
                lines.append(_element_label(role, name, flags))
                render(children)
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


_DOM_QUIET_MS = 500
# How long a program may keep running without the page after its deadline before it is stopped.
_CODE_DEADLINE_GRACE_S = 30
# Resolves once the document has gone quiet_ms without a change, or after limit_ms.
_DOM_QUIET = """([quietMs, limitMs]) => new Promise(resolve => {
    let quiet;
    const finish = () => { observer.disconnect(); clearTimeout(quiet); resolve(); };
    const observer = new MutationObserver(() => { clearTimeout(quiet); quiet = setTimeout(finish, quietMs); });
    observer.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
    quiet = setTimeout(finish, quietMs);
    setTimeout(finish, limitMs);
})"""
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
# The point a person would click: the element's own box, or the area its content covers
# when it has no box of its own (display: contents), kept inside the viewport.
_TARGET_POINT = """el => {
    const own = el.getBoundingClientRect();
    let box = own;
    if (!own.width || !own.height) {
        const rects = Array.from(el.querySelectorAll('*')).map(c => c.getBoundingClientRect())
            .filter(r => r.width && r.height);
        if (!rects.length) return null;
        box = {left: Math.min(...rects.map(r => r.left)), top: Math.min(...rects.map(r => r.top)),
               right: Math.max(...rects.map(r => r.right)), bottom: Math.max(...rects.map(r => r.bottom))};
    }
    const left = Math.max(box.left, 0), right = Math.min(box.right, innerWidth);
    const top = Math.max(box.top, 0), bottom = Math.min(box.bottom, innerHeight);
    return {x: (left + right) / 2, y: (top + bottom) / 2, own: !!(own.width && own.height)};
}"""
# What sits over the point a click would land on, or null when the click would reach the element.
_COVERED_BY = """el => {
    const point = (""" + _TARGET_POINT + """)(el);
    if (!point) return null;
    const top = document.elementFromPoint(point.x, point.y);
    if (!top || top === el || el.contains(top) || top.contains(el)) return null;
    const label = (top.getAttribute('aria-label') || top.innerText || '').trim().slice(0, 80);
    return `${top.tagName.toLowerCase()}${top.id ? '#' + top.id : ''}${label ? ' "' + label + '"' : ''}`;
}"""
# Whether a person can see an element: it has an area and nothing above it is transparent or hidden.
_SEEN = """el => {
    const box = el.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) return false;
    for (let e = el; e; e = e.parentElement) {
        const style = getComputedStyle(e);
        if (style.opacity === '0' || style.visibility === 'hidden' || style.display === 'none') return false;
    }
    return true;
}"""
# How a form field takes input: a dropdown, a box to tick, or text that may be completed from suggestions.
_FIELD_KIND = """el => {
    const role = (el.getAttribute('role') || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const completes = (el.getAttribute('aria-autocomplete') || '').toLowerCase();
    return {
        tag: el.tagName.toLowerCase(),
        checkable: ['checkbox', 'radio'].includes(type) || ['checkbox', 'radio', 'switch'].includes(role),
        suggests: el.tagName !== 'SELECT' && (role === 'combobox' || completes === 'list' || completes === 'both'
            || el.getAttribute('aria-haspopup') === 'listbox' || !!el.getAttribute('list')),
        listbox: el.getAttribute('aria-controls') || el.getAttribute('aria-owns') || '',
    };
}"""
_OPTION_NAME = "el => el.getAttribute('aria-label') || el.innerText || el.textContent || ''"
_TREE_FRAME = re.compile(r"^(\s*)- iframe\b.*\[ref=([^\]]+)\]")


def _without_subtrees(tree: str, refs: set) -> str:
    """The tree with the nodes carrying ``refs``, and everything under them, left out."""
    kept, cut_depth = [], None
    for line in tree.splitlines():
        depth = len(line) - len(line.lstrip())
        if cut_depth is not None and depth > cut_depth:
            continue
        cut_depth = None
        match = _TREE_FRAME.match(line)
        if match and match.group(2) in refs:
            cut_depth = depth
            continue
        kept.append(line)
    return "\n".join(kept)


_CLOSED_STOPS = frozenset({"until", "end"})
# The page's own content, to tell whether the next-page control turned it.
_PAGE_CONTENT = "() => document.body ? document.body.innerText : ''"


def read_is_open(record: Dict[str, Any]) -> bool:
    """Whether one collection record did not finish the read it started."""
    reason = str(record.get("stop_reason") or "")
    if reason in {"timeout", "error", "page_limit", "pending", "unchanged"}:
        return True
    if record.get("more") is True:
        return True
    return bool(record.get("error")) and reason not in _CLOSED_STOPS


def read_key(record: Dict[str, Any]) -> str:
    """What a collection record read: its address, or for a list item its list, selector and index."""
    if record.get("kind") == "open_each":
        return f"{record.get('list') or ''}#{record.get('selector') or ''}#{record.get('index')}"
    return str(record.get("url") or "")


def _read_rank(record: Dict[str, Any]) -> tuple:
    """How much a record claims: a paged history over a single page, then finished over not."""
    return ("values" in record, not read_is_open(record))


def reads_closed(records: Any) -> bool:
    """True when a retained artifact has no open collection read."""
    if not isinstance(records, list):
        return True
    return not any(isinstance(record, dict) and read_is_open(record) for record in records)


def _last_unfinished_program(state) -> str:
    """The latest collection program, when it ended before it finished."""
    unfinished = ""
    for receipt in getattr(state, "tool_history", []) or []:
        if getattr(receipt, "tool_name", "") not in {"run_playwright", "read_pages", "open_each"}:
            continue
        output = receipt.tool_output if isinstance(receipt.tool_output, dict) else {}
        if output.get("error_type") == "ExecutionTimeout":
            unfinished = str(output.get("error") or receipt.error or "program did not finish")
        elif receipt.status == "success":
            unfinished = ""
    return unfinished


class BrowserSubAgent(BaseSubAgent):
    """
    Headless browser automation subagent.

    Requires: pip install playwright && playwright install chromium

    Tools:
    - navigate: Go to a URL and wait for page load
    - snapshot: The page as a person reads it, with refs on what can be acted on
    - click: Click an element by ref, CSS selector or text
    - type_text: Type text into an input field
    - fill_form: Fill a whole form (dropdowns, checkboxes, suggestion fields) and optionally submit
    - select_option: Select an option from a <select> dropdown
    - screenshot: Take a screenshot (the model sees the image)
    - run_playwright: Playwright code against the live page, run confined, for loops and
      many-step reading; actions that could commit the person are refused
    - find, act: With a decision model, the element for a goal; act performs
      reversible actions on it, never consequential ones
    """

    whole_observation_tools = frozenset({"snapshot", "find", "act"})
    perception_tools = frozenset({
        "snapshot", "navigate", "click", "type_text", "fill_form", "select_option", "act",
    })
    #: Seconds between requests to the same site.
    site_interval_s: float = float(os.getenv("BROWSER_SITE_INTERVAL_S", "1.5"))
    #: How long an action may take to finish loading before the agent looks again.
    settle_timeout_ms: int = int(os.getenv("BROWSER_SETTLE_TIMEOUT_MS", "3000"))
    #: Longest an action waits for the page's own data requests to finish.
    data_timeout_ms: int = int(os.getenv("BROWSER_DATA_TIMEOUT_MS", "10000"))
    #: Decision confidence at which act() performs the action itself.
    act_min_confidence: float = float(os.getenv("BROWSER_ACT_MIN_CONFIDENCE", "0.7"))
    #: How long a browser stays open for the step's next execution epoch to pick it up.
    continuation_hold_s: float = float(os.getenv("BROWSER_CONTINUATION_HOLD_S", "120"))
    #: Longest attaching to BROWSER_CONTROL_URL may take; a browser that does not answer is not usable.
    attach_timeout_ms: int = int(os.getenv("BROWSER_ATTACH_TIMEOUT_MS", "30000"))
    #: Longest a run_playwright program may run.
    code_timeout_s: int = int(os.getenv("BROWSER_CODE_TIMEOUT_S", "600"))
    #: Pages read_pages opens at once in the run's browser session.
    parallel_pages: int = int(os.getenv("BROWSER_PARALLEL_PAGES", "4"))
    #: Most pages read_pages turns through one history before reporting that it goes on.
    history_pages: int = int(os.getenv("BROWSER_HISTORY_PAGES", "50"))

    SYSTEM_PROMPT = """\
You are the browser specialist: you complete the person's work accurately on the live page
and report what you observed.

## Reading And Acting On Pages

navigate, click, type_text, fill_form and select_option each return the page once its data
has loaded and it has stopped changing, so every result is ready to read. snapshot reads
the page again. Refs name elements in the latest snapshot. find/act resolve an ambiguous
element with the decision model when available.

Work in the site's own vocabulary: map what the person asked for onto the menus, filters
and names the site shows, and follow the routes the page offers.
When the task covers a whole set or a period, cover all of it: follow pagination to the
end or to the period boundary, and state exactly what you covered.

## Reading Collections

A collection is many pages of one kind: every item of a list, every item's detail or
history. read_pages and open_each read one in a single call, several pages at a time in
this signed-in session; reading such pages one click at a time spends a turn per page.
read_pages takes the addresses you know, and with next_page and until reads each one as
a paged history. open_each takes a list whose items open by clicking rather than through
links and returns each item's index, the url it opened and the script's value there;
those urls go straight into read_pages. A script is a JavaScript function run on every
page read. Which items a read covers is chosen in code too: a locator filter or a
script over the list's rows that keeps every row matching what the task names, not
indexes picked from a printout, where one row is easily missed.

next_page is the control that turns the page. until is a JavaScript function called with
what script returned on that page; it is true once the page has gone past the period: it
shows an entry from before the period began, so every entry of the period has been read.
Write it as a comparison of the entries' dates with the period's start (the oldest entry
is earlier than the start), not as a search for one date's text: a history with no entry
on the day before the period never shows that text and would be read to its end. Where
entries read "Today", "Yesterday", then dates, yesterday ends at the first entry that is
neither: rows => rows.some(row => !/^(Today|Yesterday) /.test(row)). A
history whose newest entry is already older than the period is past it on its first
page. Derive both from the site's observed controls, dates,
ordering and timezone, and try them on one address first: a single history returns in
seconds and shows whether the read stops where the period begins, before a read of every
address depends on it. Each
record holds `values`, one per page read, with `pages`, `more` and a `stop_reason`; only
until and end close a history. `until` records that your boundary function returned
true; it is not an independent assertion that the question has been answered. Pages
already read stay in the record when a later page fails or time runs out.

## Actions That Commit The Person

Placing an order, paying, booking, sending a message, submitting an application or form
to an organisation, deleting and publishing commit the person, so each is theirs to
approve. You ask by issuing that exact action with click, type_text, fill_form or
select_option on a fresh snapshot ref, adding `"irreversible": true` and a `consequence`
in the person's terms:
    click {"ref": "e14", "irreversible": true,
           "consequence": "Places the order for 3 items, £18.40, delivery Thu 10:00-12:00"}
The runtime pauses there and shows the person that consequence. On approval it performs
that exact action once and you observe the outcome on the page; a decline leaves it
undone, and you report it that way. Browsing, searching, signing in, adding to a basket
and filling a form you have not yet submitted are reversible, and you carry them out
directly.
{code}
## Authority And Evidence

Work within the requested account, scope and period. When the site denies access, the
denial is your finding to report. Handle overlays and disabled controls according to what
the page shows. Build the final answer from this run's observations: source URLs, cited
tool receipts, and the coverage achieved with any remaining gaps. Completeness comes from
what you read, item by item.
"""

    CODE_PROMPT = """
## Working In Code

run_playwright is for a page read_pages and open_each are not already reading. The same
two functions are available inside a program, and return a list, one result per address
or item, in the order asked.

A program works on the page it opens: it may move the page once, with goto or going
back, and other addresses are a collection for read_pages or open_each. `reads` in a
program is a dictionary of every collection record this step has read, as tools or
inside programs: `reads[url]` for an address read_pages read, and
`reads[f"{list_url}#{selector}#{index}"]` for an item open_each opened. A read that did
not finish never replaces one that did. A later program filters and combines these
records instead of reading the site again, and the figures an answer states (counts,
totals, which items match) come from such a program: a long record read by eye is
miscounted.

Read the structure and data the page actually exposes. A script can return its rows
together with their links:
    rows = await page.locator("tr").evaluate_all(
        "rs => rs.map(r => ({text: r.innerText, href: r.querySelector('a')?.href}))")
Keep what each page gave you in `state` so later code can build on it.

In a program the collection reads look like this:
    results = await read_pages(urls, "() => document.querySelector('main').innerText")
    runs = await read_pages(run_urls, rows_js, next_page=next_selector, until=boundary_js)
    items = await open_each(page.locator("tbody tr"), "() => location.href")
open_each takes the items as you would select them to click them; the addresses it
returns go into read_pages, and into state["procedure"] so later visits go straight there.

Write each item into `state` as soon as it is read. It is checkpointed with the step,
including across execution epochs. Local Python variables persist within the current
code session; use state for work that must survive a session restart. Programs use
the configured code limit and the step's remaining time, or a shorter timeout_s you set.

To learn how part of a page works (what is clickable, its role and name), read
`await locator.aria_snapshot()`: it shows the structure a person and the tools act on, in
a fraction of the size of the markup.

Every result reaches you whole and stays in the conversation, so return what you need to
reason over and keep bulk data whole in `state`, where later code reads it and the step's
artifact carries it. Completeness is what makes a "not found" trustworthy, so carry data
whole: complete text, every row, every item. To keep a result focused, select the element
that holds the data, such as its table or list.

`page` is your live page with the async Python Playwright API; top-level await works, and
json, re, datetime and asyncio are available. Locator.first and Locator.last are
properties. Variables and functions persist between calls in this step. `state` is a JSON
dictionary carried into the step's artifact and later steps: it holds the inventory, URLs,
findings and coverage, including unfinished work. `prior` holds earlier steps' artifacts
to build on. Set `result` to what the code found; print() is for diagnostics.

When your findings are complete, write state["procedure"] as the method that produced them:
the site URL, the addresses and URL patterns you used, how items open, and how you
extracted each part, so a later run can go straight to the data. Accepted work keeps it in
memory for next time, together with the programs that produced the findings. When earlier
sessions hold such a procedure for this site, run its programs first, adapted to this
task: they are a method that already worked. Where the live site no longer matches,
repair that part and continue. Current facts always come from this run.
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
        egress: Optional[Egress] = None,
        locale: Optional[str] = None,
        timezone: Optional[str] = None,
        allow_unsafe_local_execution: bool = False,
    ):
        self.headless = headless
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.profile_root = profile_root
        self.scope_field = scope_field
        self.control_url = control_url
        self.egress = egress
        self.locale = locale
        self.timezone = timezone
        self.allow_unsafe_local_execution = bool(allow_unsafe_local_execution)
        self._code_sandbox = None
        self._page_broker = None

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
        # Playwright resolves only the refs of the latest snapshot of the current document.
        self._live_refs: tuple = (None, frozenset())
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
        code = self.CODE_PROMPT if "run_playwright" in self._tools else ""
        return self.SYSTEM_PROMPT.replace("{code}", code)

    def _save_subagent_state(self, state) -> None:
        state.internal_variables["_browser_runtime"] = json.loads(json.dumps({
            "findings": getattr(self, "_browser_findings", {}),
            "programs": getattr(self, "_programs", []),
            "reads": getattr(self, "_browser_reads", []),
            "calls": getattr(self, "_collection_calls", []),
            "url": self._current_url,
        }))

    def _restore_subagent_state(self, state) -> None:
        saved = state.internal_variables.get("_browser_runtime") or {}
        saved = json.loads(json.dumps(saved))
        self._browser_findings = saved.get("findings", {})
        self._browser_reads = saved.get("reads", [])
        self._collection_calls = saved.get("calls", [])
        self._programs = saved.get("programs", [])
        self._current_url = saved.get("url", "")

    def _note_call(self, call: Dict[str, Any]) -> int:
        """The index of this collection call among the step's calls; the same call is one entry."""
        calls = self.__dict__.setdefault("_collection_calls", [])
        if call in calls:
            return calls.index(call)
        calls.append(call)
        return len(calls) - 1

    def _calls_behind_records(self) -> List[Dict[str, Any]]:
        """The collection calls that produced the step's current records, in the order they were made."""
        calls = getattr(self, "_collection_calls", [])
        used = sorted({
            record["call"] for record in self._read_records().values()
            if isinstance(record.get("call"), int) and record["call"] < len(calls)
        })
        return [calls[index] for index in used]

    def _remember_read(self, kind: str, record: Dict[str, Any], call: Optional[int] = None) -> None:
        """Keep the runtime's own record of a collection read, apart from what code assigns."""
        if not isinstance(record, dict):
            return
        self.__dict__.setdefault("_browser_reads", []).append(
            {"kind": kind, **record, **({"call": call} if call is not None else {})}
        )

    def _read_records(self) -> Dict[str, Dict[str, Any]]:
        """The step's collection records by what they read: an address, or a list item.

        A paged history of an address outranks a single page of it, and a finished read
        outranks an unfinished one of the same kind; among equals the later read is kept.
        So a page read never hides an unfinished history, and a failed re-read never
        hides a finished one.
        """
        records: Dict[str, Dict[str, Any]] = {}
        for record in getattr(self, "_browser_reads", []):
            if not isinstance(record, dict):
                continue
            key = read_key(record)
            kept = records.get(key)
            if kept is None or _read_rank(record) >= _read_rank(kept):
                records[key] = record
        return records

    def _open_read_facts(self) -> List[Dict[str, Any]]:
        """The current record for each read that did not close."""
        return [record for record in self._read_records().values() if read_is_open(record)]

    def _reads_closed(self, state) -> tuple:
        open_reads = self._open_read_facts()
        timed_out = _last_unfinished_program(state)
        if not open_reads and not timed_out:
            return True, ""
        observed = {
            "open_reads": [
                {
                    "kind": record.get("kind"),
                    "url": record.get("url"),
                    "list": record.get("list"),
                    "selector": record.get("selector"),
                    "index": record.get("index"),
                    "pages": record.get("pages"),
                    "more": record.get("more"),
                    "stop_reason": record.get("stop_reason"),
                    "error": record.get("error"),
                }
                for record in open_reads
            ],
        }
        if timed_out:
            observed["unfinished_program"] = timed_out
        return False, GateEvidence(
            check="browser_reads_closed",
            requirement=(
                "every collection read has closed: stop_reason until or end, "
                "more not true, and no unfinished program still the latest collection attempt"
            ),
            observed=observed,
        )

    def _can_complete(self, state, parsed):
        base_ok, base_reason = super()._can_complete(state, parsed)
        if not base_ok:
            return base_ok, base_reason
        reads_ok, reads_reason = self._reads_closed(state)
        if not reads_ok:
            return reads_ok, reads_reason
        return self._coverage_reviewed(state)

    def _coverage_reviewed(self, state):
        """The first answer is checked once against what was read, while there is time to read more."""
        lease = getattr(getattr(self, "_cognition", None), "lease", None)
        if state.internal_variables.get("coverage_reviewed") or (lease is not None and lease.is_expired()):
            return True, ""
        state.internal_variables["coverage_reviewed"] = True
        return False, GateEvidence(
            check="coverage_review",
            requirement=(
                "the answer covers the whole set and period the task names: how many items the "
                "source lists that match what the task names (counted in code over the list) and "
                "how many of them were read, and for each, the pages read and the range they span "
                "(first and last entry). A panel of recent items, a first page or a filtered view "
                "is part of a set; where the source goes on beyond what was read, read the rest, "
                "then answer again"
            ),
            observed={"answer_submitted_at_turn": state.turn},
        )

    def _records_support_completion(self, state, parsed):
        base_ok, base_reason = super()._records_support_completion(state, parsed)
        if not base_ok:
            return base_ok, base_reason
        return self._reads_closed(state)

    def setup_tools(self) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            # Register a single stub tool that explains how to install Playwright
            self.register_tool(
                "install_required",
                self._install_required,
                "Playwright not installed. Params: {}",
                phase="thinking",
            )
            return

        self.register_tool(
            "navigate",
            self._tool_navigate,
            'Go to a URL; returns the page once it has loaded and stopped changing. Params: {"url": "<url>"}',
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
            'Click an element; returns the page afterwards. Params: {"ref": "<ref>"} or {"selector": "<css>"} or {"text": "<visible text>"}',
            phase="action",
        )
        self.register_tool(
            "type_text",
            self._tool_type_text,
            'Type text into an input; returns the page afterwards. Params: {"ref": "<ref>" or "selector": "<css>", "text": "<text>", "clear_first": true}',
            phase="action",
        )
        self.register_tool(
            "screenshot",
            self._tool_screenshot,
            "Take a screenshot of the current page. Params: {}",
            phase="thinking",
        )
        self.register_tool(
            "read_pages",
            self._tool_read_pages,
            'Read many addresses at once in this signed-in session, several pages at a time. '
            'With next_page and until, each address is a paged history turned until `until`, '
            'called with what script returned on that page, is true: the page has gone past the '
            'period, showing an entry from before it began, so every entry of the period has been read. '
            'Returns one record per address, whole: value or values, pages, more and stop_reason '
            '(until, end, page_limit, unchanged, error, timeout). Only until and end close a '
            'history: unchanged means the next-page control did not turn the page. '
            'Params: {"urls": ["<url>"], "script": "<js function>", '
            '"next_page": "<optional css>", "until": "<optional js>"}',
            phase="action",
        )
        self.register_tool(
            "open_each",
            self._tool_open_each,
            'Open each item of a list that has no links, several at a time, and read what opens. '
            'Returns each item index, the url it opened and the script value, or an error. '
            'indexes opens only those items again. '
            'Params: {"url": "<list url>", "selector": "<css>", "script": "<js function>", '
            '"indexes": [<optional item index>]}',
            phase="action",
        )
        if self._code_confinable():
            self.register_tool(
                "run_playwright",
                self._run_playwright,
                'Run an async Python Playwright program against your live page (`page`, `state`, '
                '`prior`, `reads`; set `result`). A program works on the page it opens: it moves '
                'the page at most once. For a collection, `await read_pages(urls, js)` reads many '
                'addresses at once, with `next_page` and `until` reading each paged history to '
                'the start of a period, and `await open_each(items_locator, js)` clicks each item '
                'of a list in its own tab, several at a time, and reads what opens; both return '
                'one result per item. `reads` is a dictionary of every collection record this '
                'step has read, by address, or by "<list url>#<selector>#<index>" for a list '
                'item. An action that '
                'could commit the person raises ConsequentialActionRefused and goes through the '
                'approval call instead. Returns your result, print output, the keys in state and '
                'the actions taken. Params: {"code": "<python>", "timeout_s": <optional seconds>}',
                phase="action",
            )
        self.register_tool(
            "fill_form",
            self._tool_fill_form,
            'Fill a whole form in one call and optionally submit it; returns the page afterwards. '
            'Each field gets its value the way its element takes input: a dropdown has the option '
            'selected, a checkbox or radio takes "checked": true/false, and a field that suggests '
            'as you type has the text typed and the matching suggestion chosen (when several '
            'match, they are returned for you to pick). "submit" is the ref of the button to '
            'press once every field is set. Params: {"fields": [{"ref": "<ref>" or "selector": '
            '"<css>", "value": "<text or option>"} or {"ref": "<ref>", "checked": true}], '
            '"submit": "<optional button ref>"}',
            phase="action",
        )
        self.register_tool(
            "select_option",
            self._tool_select_option,
            'Select a dropdown option; returns the page afterwards. Params: {"ref": "<ref>" or "selector": "<css>", "value": "<option value or label>"}',
            phase="action",
        )

    # ──────────────────────────────────────────────────────────────────────
    # Lifecycle — open/close browser per run()
    # ──────────────────────────────────────────────────────────────────────

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
            "select_option": "Choose an option in",
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
                        "value": field.get("value", field.get("checked")),
                    }
                    for field in params.get("fields") or []
                ]
                submit = params.get("submit")
                return {
                    "page": where, "fields": fields,
                    **({"submit": await self._fingerprint("", ref=submit)} if submit else {}),
                }
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
        if tool_name == "run_playwright" and params.get("irreversible") is True:
            return {
                "status": "error",
                "error": (
                    "run_playwright never performs an irreversible action: a person approves an "
                    "exact element. Take a snapshot, then call click/type_text/fill_form with its "
                    "ref and irreversible plus consequence."
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
            if params.get("ref"):
                stale = await self._stale_ref(params["ref"])
                if stale:
                    return stale
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
            return result
        if await self._may_commit(tool_name, params):
            target = await self._action_target(tool_name, params)
            key = json.dumps([tool_name, target], sort_keys=True, default=str)
            verdicts = self.__dict__.setdefault("_commit_verdicts", {})
            if key not in verdicts:
                verdicts[key] = await self._judge_commits({"action": tool_name, "element": target})
            if verdicts[key]:
                return {
                    "status": "error",
                    "error": (
                        f"This {tool_name} could commit the person, so it waits for their approval. "
                        "If the task needs it, call it again with \"irreversible\": true and a "
                        "\"consequence\" saying what will happen."
                    ),
                    "semantic_error": "APPROVAL_REQUIRED",
                    "performed": False,
                }
        return await super()._execute_tool(tool_name, params)

    async def _may_commit(self, tool_name: str, params: Dict[str, Any]) -> bool:
        """Whether this unflagged action is one that could commit the person and needs judging."""
        if tool_name in {"click", "select_option"}:
            return True
        if tool_name == "fill_form":
            return bool(params.get("submit"))
        if tool_name == "type_text":
            return "\n" in str(params.get("text", "")) or params.get("submit") is True
        return False

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
        self._restore_subagent_state(state)
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
        await self._open_browser(state, replay=True)

    async def _pre_execute_hook(self, tool_name, params, state):
        """Before a tool runs, open the browser again if it went away mid-step."""
        page = self._page
        lost = page is not None and getattr(page, "is_closed", lambda: False)()
        if PLAYWRIGHT_AVAILABLE and (lost or (page is None and self._launch_error)):
            logger.warning("[browser] The browser went away; opening it again at %s", self._current_url or "a new page")
            await self._post_run_hook()
            await self._open_browser(state, replay=False)
        return await super()._pre_execute_hook(tool_name, params, state)

    async def _open_browser(self, state, *, replay: bool) -> None:
        """Open or attach the browser this run works in, on the page it last had."""
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
            # A tenant's profile keeps its exit IP across runs; otherwise the workflow does.
            egress_session = (
                os.path.basename(profile) if profile
                else str((getattr(state, "context", None) or {}).get("workflow_id") or "") or None
            )
            launch = {"proxy": self.egress.playwright(egress_session)} if self.egress and not self.control_url else {}
            presented = {
                key: value
                for key, value in (("locale", self.locale), ("timezone_id", self.timezone))
                if value
            }
            if self.control_url:
                if self.egress:
                    logger.info("[browser] An attached browser leaves from its own network; EGRESS_PROXY_URL is not applied")
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.control_url, timeout=self.attach_timeout_ms,
                )
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
                    **launch,
                    **presented,
                )
                self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            else:
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=args,
                    **launch,
                )
                self._context = await self._browser.new_context(
                    viewport=self.viewport,
                    java_script_enabled=True,
                    **presented,
                )
                self._page = await self._context.new_page()
            if not self._attached:
                await self._present_as_browser()
            self._watch_requests(self._page)
            if self._current_url:
                await self._pace(self._current_url)
                await self._page.goto(self._current_url, wait_until="domcontentloaded")
                await self._settle()
            logger.info(
                "[browser] Browser ready (mode=%s, headless=%s, egress=%s)",
                "shared" if self._attached else "persistent" if profile else "fresh",
                self.headless,
                self.egress.redacted() if launch else "direct",
            )
            try:
                if replay:
                    await self._replay_accepted_procedure(state)
            except Exception as replay_error:
                logger.warning("[browser] Accepted procedure was not replayed: %s", replay_error)
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
        if self._code_sandbox is not None:
            await self._code_sandbox.close_browser_session()
        self._page_broker = None
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

    # Not named _tool_*: autodiscovery would offer it where Playwright is installed.
    async def _install_required(self, **kwargs) -> Dict[str, Any]:
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
        wait_for: Literal["load", "domcontentloaded", "commit"] = "domcontentloaded",
        timeout_ms: int = 30000,
        **kwargs,
    ) -> Dict[str, Any]:
        """Navigate to a URL."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if wait_for == "networkidle":
                wait_for = "domcontentloaded"
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            await self._pace(url)
            response = await self._page.goto(
                url,
                wait_until=wait_for,
                timeout=timeout_ms,
            )
            await self._settle()
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
            return await self._observed(result)
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

    async def _observed(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """An action's result with the page as it stands afterwards, so acting includes looking."""
        try:
            result["title"] = await self._page.title()
            result["page"] = _reading_view(await self._aria(self._page.locator("body")))
        except Exception as exc:
            result["page_unavailable"] = f"The page could not be read after the action ({exc}); take a snapshot."
        return result

    def _watch_requests(self, page) -> None:
        """Track the page's in-flight data requests so settling can wait for its data.

        Only the site's own endpoints count: analytics, session-replay and chat beacons
        to other domains fire continuously and never carry the content being read.
        """
        if getattr(page, "_jc_pending", None) is not None:
            return
        pending: set = set()
        page._jc_pending = pending

        def own_site(url: str) -> bool:
            host = urlparse(url).hostname or ""
            page_host = urlparse(page.url).hostname or ""
            labels = page_host.split(".")
            site = ".".join(labels[1:]) if len(labels) > 2 else page_host
            return bool(site) and (host == site or host.endswith("." + site))

        def frame_of(request):
            try:
                return request.frame
            except Exception:  # service-worker requests have no frame
                return None

        def started(request):
            if request.is_navigation_request():
                # A frame loading a new document abandons its old document's requests, and
                # the browser reports no end for them.
                frame = frame_of(request)
                gone = {frame} if frame is not page.main_frame else None
                for old in list(pending):
                    if gone is None or frame_of(old) in gone:
                        pending.discard(old)
            elif request.resource_type in ("fetch", "xhr") and own_site(request.url):
                pending.add(request)

        def ended(request):
            pending.discard(request)

        def detached(frame):
            for old in list(pending):
                if frame_of(old) is frame:
                    pending.discard(old)

        page.on("request", started)
        page.on("requestfinished", ended)
        page.on("requestfailed", ended)
        page.on("framedetached", detached)

    async def _data_quiet(self, page=None) -> None:
        """Until no data request has been in flight for the quiet period, or the data timeout."""
        pending = getattr(page or self._page, "_jc_pending", None)
        if pending is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.data_timeout_ms / 1000
        quiet_since = None
        while loop.time() < deadline:
            if pending:
                quiet_since = None
            elif quiet_since is None:
                quiet_since = loop.time()
            elif loop.time() - quiet_since >= _DOM_QUIET_MS / 1000:
                return
            await asyncio.sleep(0.05)

    async def _settle(self, page=None) -> None:
        """Let what an action started finish loading its data and rendering before the next observation."""
        page = page or self._page
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self.settle_timeout_ms)
            # Client-rendered apps fill the page after load; wait for their data requests, not the network.
            await self._data_quiet(page)
            await page.evaluate(_DOM_QUIET, [_DOM_QUIET_MS, self.settle_timeout_ms])
        except Exception as exc:  # a navigation mid-wait or a page that never stops changing is still usable
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
                point = await locator.evaluate(_TARGET_POINT)
                if point and not point["own"]:
                    # An element laid out without a box of its own (display: contents) takes
                    # the click itself; a point inside it can land on a child that keeps it.
                    await locator.evaluate("el => el.click()")
                else:
                    await locator.click(timeout=timeout_ms)
            elif text and not selector:
                # Text-based click
                await self._page.get_by_text(text, exact=False).first.click(timeout=timeout_ms)
            elif selector:
                await self._page.click(selector, timeout=timeout_ms)
            else:
                return {"status": "error", "error": "One of ref, selector or text is required"}
            await self._settle()
            return await self._observed({"status": "success", "url": self._page.url})
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
            return await self._observed(
                {"status": "success", "target": ref or selector, "chars_typed": len(text)}
            )
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _ref(self, ref: str):
        return self._page.locator(f"aria-ref={ref}")

    async def _aria(self, locator) -> str:
        """An aria snapshot of what a person can see, remembering which refs it made resolvable."""
        tree = await locator.aria_snapshot(mode="ai")
        # A widget frame faded to transparent stays in the accessibility tree but not on screen.
        unseen = set()
        for line in tree.splitlines():
            match = _TREE_FRAME.match(line)
            if match:
                try:
                    if not await self._ref(match.group(2)).evaluate(_SEEN):
                        unseen.add(match.group(2))
                except Exception:
                    continue
        if unseen:
            tree = _without_subtrees(tree, unseen)
        self._live_refs = (await self._document(), frozenset(_TREE_REF.findall(tree)))
        return tree

    async def _document(self):
        return await self._page.evaluate("performance.timeOrigin")

    async def _stale_ref(self, ref: str) -> Optional[Dict[str, Any]]:
        """Why ``ref`` no longer names an element, or None while it does."""
        document, refs = self._live_refs
        if ref in refs and document == await self._document():
            return None
        return {
            "status": "error",
            "error": (
                f"Ref {ref} is from an earlier view of the page; refs last only until the "
                "next snapshot or page load. Take a new snapshot and use its refs."
            ),
            "semantic_error": "STALE_REF",
            "performed": False,
        }

    async def _actionable(self, ref: str):
        """The element behind ``ref``, or the reason it cannot be acted on now."""
        stale = await self._stale_ref(ref)
        if stale:
            return None, stale
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
        return _index_from_tree(await self._aria(self._page.locator("body")))

    async def _tool_snapshot(self, ref: str = "", **kwargs) -> Dict[str, Any]:
        """The page, or one region of it, as a person reads it, with refs on what can be acted on."""
        err = self._ensure_page()
        if err:
            return err
        try:
            if ref:
                stale = await self._stale_ref(ref)
                if stale:
                    return stale
                region = _reading_view(await self._aria(self._ref(ref)))
                return {"status": "success", "url": self._page.url, "region": region}
            view = _reading_view(await self._aria(self._page.locator("body")))
            return {
                "status": "success",
                "url": self._page.url,
                "title": await self._page.title(),
                "page": view,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

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

    async def _tool_fill_form(
        self,
        fields: List[Dict[str, Any]],
        submit: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Set every field the way its element takes input, then optionally submit."""
        err = self._ensure_page()
        if err:
            return err
        results = []
        for field in fields:
            ref = field.get("ref", "")
            selector = field.get("selector", "")
            target = ref or selector
            if not target:
                results.append({"target": target, "status": "error", "error": "No ref or selector"})
                continue
            try:
                if ref:
                    locator, refusal = await self._actionable(ref)
                    if refusal:
                        results.append({"target": ref, **refusal})
                        continue
                else:
                    locator = self._page.locator(selector).first
                results.append({"target": target, **await self._set_field(locator, field)})
            except Exception as e:
                results.append({"target": target, "status": "error", "error": str(e)})
        done = sum(1 for r in results if r["status"] == "success")
        outcome = {
            "status": "success" if done == len(fields) else "partial",
            "filled": done,
            "total": len(fields),
            "results": results,
        }
        if not submit:
            return await self._observed(outcome)
        if done != len(fields):
            return await self._observed({
                **outcome, "submitted": False,
                "submit_skipped": "not every field is set; the form was not submitted",
            })
        clicked = await self._tool_click(ref=submit)
        return {**clicked, **outcome, "submitted": clicked.get("status") == "success",
                **({"submit_error": clicked["error"]} if clicked.get("error") else {})}

    async def _set_field(self, locator, field: Dict[str, Any]) -> Dict[str, Any]:
        """Give one field its value as a person would: pick, tick, or type and choose a suggestion."""
        kind = await locator.evaluate(_FIELD_KIND)
        value = str(field.get("value", ""))
        if kind["tag"] == "select":
            selected = await locator.select_option(value=value, timeout=10000)
            if not selected:
                selected = await locator.select_option(label=value, timeout=10000)
            return {"status": "success", "selected": selected}
        if kind["checkable"]:
            if not isinstance(field.get("checked"), bool):
                return {"status": "error", "error": 'A checkbox or radio takes "checked": true or false.'}
            await locator.set_checked(field["checked"], timeout=10000)
            return {"status": "success", "checked": field["checked"]}
        if not kind["suggests"]:
            await locator.fill(value, timeout=10000)
            return {"status": "success"}
        # A field that suggests as you type only takes a value once a suggestion is chosen.
        await locator.fill("", timeout=10000)
        await locator.press_sequentially(value, delay=20)
        await self._settle()
        listbox = self._page.locator(f'[id="{kind["listbox"]}"]') if kind["listbox"] else self._page
        try:
            # Suggestions usually come back from a request a moment after the typing stops.
            await listbox.get_by_role("option").first.wait_for(
                state="visible", timeout=self.settle_timeout_ms
            )
        except Exception:
            pass
        options = [
            option for option in await listbox.get_by_role("option").all()
            if await option.is_visible()
        ]
        names = [
            " ".join(str(await option.evaluate(_OPTION_NAME)).split()) for option in options
        ]
        wanted = " ".join(value.split()).casefold()
        exact = [i for i, name in enumerate(names) if name.casefold() == wanted]
        containing = [i for i, name in enumerate(names) if wanted in name.casefold()]
        chosen = exact if len(exact) == 1 else containing
        if len(chosen) == 1:
            await options[chosen[0]].click(timeout=10000)
            await self._settle()
            return {"status": "success", "chose": names[chosen[0]]}
        if names:
            return {
                "status": "needs_choice",
                "typed": value,
                "suggestions": names,
                "note": "No single suggestion matches what was typed; click the right one by its ref.",
            }
        return {"status": "success", "note": "Typed; the field offered no suggestions."}

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
            return await self._observed({"status": "success", "target": ref or selector, "selected": selected})
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _code_confinable(self) -> bool:
        """Whether model-written code can run here: confined by the OS, or explicitly trusted."""
        if self.allow_unsafe_local_execution:
            return True
        from jarviscore.execution.isolation import confinement_unavailable_reason

        return confinement_unavailable_reason() is None

    def _sandbox_for_code(self):
        if self._code_sandbox is None:
            import tempfile
            from pathlib import Path

            from jarviscore.execution.coder_sandbox import CoderSandbox

            self._code_sandbox = CoderSandbox(
                workspace_dir=Path(tempfile.mkdtemp(prefix="jc-browser-code-")),
                timeout=self.code_timeout_s,
                allow_unsafe_local_execution=self.allow_unsafe_local_execution,
            )
        return self._code_sandbox

    async def _judge_commits(self, action: Dict[str, Any]) -> Optional[str]:
        """Why browser code may not perform ``action`` itself, or None when it may.

        Fails closed: an action that cannot be judged is not performed.
        """
        described = json.dumps(action, default=str, ensure_ascii=False)
        question = (
            "Would this action commit the person or be hard to undo: placing an order, paying, "
            "booking, sending a message, submitting an application or form to an organisation, "
            "publishing, deleting or changing a saved setting? Adding to a basket or cart, "
            "filling a form without submitting it, signing in, opening, filtering, sorting, "
            "paging, searching and reading are reversible."
        )
        try:
            if getattr(self, "decision_client", None) is not None:
                verdict = await self.decision_client.evaluate(
                    state=f"Browser code is about to perform this action:\n{described}",
                    questions={"commits": {"type": "noul", "instructions": question}},
                )
                commits = float(verdict.answers["commits"]["noul"]) >= 0.5
            else:
                call = {
                    "messages": [{"role": "user", "content": (
                        f"{question}\nAction: {described}\n"
                        'Return only JSON: {"commits": true|false}'
                    )}],
                    "response_format": {"type": "json_object"},
                    **({"model": self.llm_client.nano_model}
                       if getattr(self.llm_client, "nano_model", None) else {}),
                }
                response = await self.llm_client.generate(**call)
                content = response.get("content", "") if isinstance(response, dict) else str(response)
                commits = json.loads(content)["commits"] is not False
        except Exception as exc:
            return f"Whether this action commits the person could not be judged ({exc}); it was not performed."
        if not commits:
            return None
        target = action.get("element") or action.get("script")
        return (
            f"{action.get('action')} on {json.dumps(target, default=str, ensure_ascii=False)} could commit the person, "
            "so browser code does not perform it. If the task needs it, take a snapshot and call "
            "click/type_text/fill_form on its ref with irreversible and consequence so the person "
            "can decide."
        )

    async def _tool_read_pages(self, urls=None, script="", next_page="", until="", **kwargs):
        """Read a collection in this session. The records, not the model's summary, are the read."""
        err = self._ensure_page()
        if err:
            return err
        addresses = [str(url) for url in urls or [] if str(url)]
        script = str(script or "")
        if not addresses or not script:
            return {"status": "error", "error": "read_pages needs urls and a JavaScript function."}
        from urllib.parse import urlsplit

        sites = dict.fromkeys(urlsplit(url).netloc for url in addresses)
        for site in sites:
            refusal = await self._judge_commits({
                "action": "evaluate", "script": script, "url": f"https://{site}/",
            })
            if not refusal and until:
                refusal = await self._judge_commits({
                    "action": "evaluate", "script": str(until), "url": f"https://{site}/",
                })
            if not refusal and next_page:
                refusal = await self._judge_commits({
                    "action": "click",
                    "element": {"selector": str(next_page), "purpose": "turn to the next page"},
                    "url": f"https://{site}/",
                })
            if refusal:
                return {"status": "error", "error": refusal, "performed": False}
        records = await self._read_pages(addresses, script, 0, str(next_page or ""), str(until or ""))
        return {"status": "success", "results": records}

    async def _tool_open_each(self, url="", selector="", script="", indexes=None, **kwargs):
        """Open each list item, or the chosen ones, in its own page and read what the script returns there."""
        err = self._ensure_page()
        if err:
            return err
        url, selector, script = str(url or ""), str(selector or ""), str(script or "")
        if not url or not selector or not script:
            return {
                "status": "error",
                "error": "open_each needs a list url, a selector and a JavaScript function.",
            }
        sample = await self._open_each(url, selector, None, "")
        refusal = await self._judge_commits({
            "action": "click", "element": {"selector": selector, "items": sample}, "url": url,
        }) or await self._judge_commits({"action": "evaluate", "script": script, "url": url})
        if refusal:
            return {"status": "error", "error": refusal, "performed": False}
        chosen = list(range(len(sample))) if indexes is None else [int(index) for index in indexes]
        results = await self._open_each(url, selector, chosen, script, count=len(sample))
        return {"status": "success", "results": results}

    async def _replay_accepted_procedure(self, state) -> None:
        """Run an accepted site procedure before the first turn, when it names this task's site."""
        if getattr(self, "_browser_findings", None) or getattr(self, "_browser_reads", None):
            return
        task_text = " ".join([
            str(getattr(state, "task", "") or ""),
            str((getattr(state, "context", None) or {}).get("objective") or ""),
            self._current_url,
        ]).lower()
        programs = []
        for item in (getattr(state, "context", None) or {}).get("_recalled") or []:
            content = str(item.get("content") or "") if isinstance(item, dict) else str(item)
            if "Browser procedure:" not in content:
                continue
            hosts = {host.lower() for host in re.findall(r"https?://([^/\s\"']+)", content)}
            if not hosts or not any(host in task_text for host in hosts):
                continue
            programs.extend(re.findall(r"```python\n(.*?)```", content, re.S))
        for code in programs:
            result = await self._run_playwright(code)
            state.add_tool_result(
                "run_playwright",
                {"source": "accepted_procedure"},
                result,
                error=result.get("error") if isinstance(result, dict) else None,
            )

    async def _new_batch_page(self):
        opening = asyncio.create_task(self._context.new_page())
        try:
            return await asyncio.shield(opening)
        except asyncio.CancelledError:
            page = await opening
            await page.close()
            raise

    async def _read_pages(
        self, urls: List[str], script: str, concurrency: int = 0,
        next_page: str = "", until: str = "",
    ) -> List[Dict[str, Any]]:
        """Each address read in its own page of this session, several at once, in the given order.

        With ``next_page`` each address is a history read page by page: the control is clicked
        and the page settles until ``until`` holds or there is no further page.
        """
        slots = asyncio.Semaphore(max(1, min(concurrency or self.parallel_pages, self.parallel_pages)))
        await self._check_scripts(script, until)
        call = self._note_call({
            "kind": "read_pages", "urls": list(urls), "script": script,
            **({"next_page": next_page, "until": until} if next_page else {}),
        })

        async def history(page, record) -> None:
            values = record["values"]
            while True:
                value = await page.evaluate(script)
                values.append(value)
                record["pages"] = len(values)
                if until and await page.evaluate(until, value):
                    record.update(more=False, stop_reason="until")
                    return
                control = page.locator(next_page).first
                if not await control.count() or not await control.is_enabled():
                    record.update(more=False, stop_reason="end")
                    return
                if len(values) >= self.history_pages:
                    record["stop_reason"] = "page_limit"
                    return
                before = await page.evaluate(_PAGE_CONTENT)
                await control.click(timeout=10000)
                await self._settle(page)
                if await page.evaluate(_PAGE_CONTENT) == before:
                    record["stop_reason"] = "unchanged"
                    return

        records = [{"url": url, "error": "Not started", "stop_reason": "pending"} for url in urls]

        async def read(url: str, record) -> None:
            async with slots:
                page = await self._new_batch_page()
                record.pop("error", None)
                record.pop("stop_reason", None)
                if next_page:
                    record.update(values=[], pages=0, more=True)
                try:
                    self._watch_requests(page)
                    await self._pace(url)
                    response = await page.goto(url, wait_until="domcontentloaded")
                    await self._settle(page)
                    record.update(
                        final_url=page.url, http_status=response.status if response else None,
                    )
                    if next_page:
                        await history(page, record)
                    else:
                        record["value"] = await page.evaluate(script)
                except Exception as exc:  # noqa: BLE001 - one page's failure is that page's result
                    record.update(error=str(exc), stop_reason="error")
                finally:
                    await page.close()

        await self._finish_batch([read(url, record) for url, record in zip(urls, records)])
        for record in records:
            if record.get("stop_reason") == "pending" or (
                "value" not in record and not record.get("stop_reason")
            ):
                record.update(error="Program deadline reached", stop_reason="timeout")
            elif next_page and record.get("more") and not record.get("stop_reason"):
                record.update(error="Program deadline reached", stop_reason="timeout")
            self._remember_read("read_pages", record, call)
        return records

    async def _check_scripts(self, *scripts: str) -> None:
        """Refuse a collection read whose script is not valid JavaScript, before it opens any page."""
        page = getattr(self, "_page", None)
        for script in scripts:
            if not script or page is None:
                continue
            try:
                await page.evaluate(f"typeof ({script})")
            except Exception as exc:  # noqa: BLE001 - only a syntax error is the script's fault
                if "SyntaxError" in str(exc):
                    raise ValueError(
                        f"This script is not valid JavaScript, so no page was opened: {exc}"
                    ) from exc

    async def _finish_batch(self, operations) -> None:
        deadline = getattr(getattr(self, "_page_broker", None), "deadline", None)
        tool_time = self._tool_time_s()
        if deadline is None and tool_time is not None:
            # Called as a tool, a read stops where the step's time does and returns what it read.
            deadline = asyncio.get_running_loop().time() + tool_time
        workers = [asyncio.create_task(operation) for operation in operations]
        pending = asyncio.gather(*workers)
        try:
            if deadline is None:
                await pending
            else:
                await asyncio.wait_for(pending, max(0, deadline - asyncio.get_running_loop().time()))
        except asyncio.TimeoutError:
            pass
        finally:
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _open_each(
        self, url: str, selector: str, indexes: Optional[List[int]], script: str, concurrency: int = 0,
        count: Optional[int] = None,
    ) -> List[Any]:
        """Click each item of a list in its own page of this session, several at once, and read what opens.

        With ``indexes`` None and no script, returns the items' texts so the click can be judged first.
        ``count`` is how many items the selector matched there, when the caller has just looked.
        """
        async def opened(target: str):
            page = await self._new_batch_page()
            try:
                self._watch_requests(page)
                await self._pace(target)
                await page.goto(target, wait_until="domcontentloaded")
                await self._settle(page)
                return page
            except BaseException:
                await page.close()
                raise

        if not script:
            page = await opened(url)
            try:
                return await page.locator(selector).evaluate_all(
                    "els => els.map(e => (e.innerText || '').trim())"
                )
            finally:
                await page.close()
        await self._check_scripts(script)
        if count is None:
            count = len(await self._open_each(url, selector, None, ""))
        missing = [int(index) for index in indexes or [] if not 0 <= int(index) < count]
        if missing:
            raise ValueError(
                f"{selector!r} matches {count} item(s) on {url}, so items {missing} do not exist; "
                "nothing was opened."
            )
        call = self._note_call({"kind": "open_each", "list": url, "selector": selector, "script": script})
        if indexes is None:
            indexes = list(range(count))
        queue = list(indexes)
        results: Dict[int, Dict[str, Any]] = {}

        # Each page loads the list once, then opens its share of items, returning to the list between them.
        async def worker() -> None:
            page = None
            try:
                while queue:
                    index = queue.pop(0)
                    try:
                        if page is None:
                            page = await opened(url)
                        elif page.url != url:
                            await page.go_back(wait_until="domcontentloaded")
                            await self._settle(page)
                            if page.url != url:
                                await page.close()
                                page = await opened(url)
                        item = page.locator(selector).nth(index)
                        await item.wait_for(state="attached", timeout=self.data_timeout_ms)
                        point = await item.evaluate(_TARGET_POINT, timeout=5000)
                        if point and not point["own"]:
                            await item.evaluate("el => el.click()")
                        else:
                            await item.click(timeout=10000)
                        await self._settle(page)
                        results[index] = {
                            "list": url, "selector": selector, "index": index,
                            "url": page.url, "value": await page.evaluate(script),
                        }
                    except Exception as exc:  # noqa: BLE001 - one item's failure is that item's result
                        results[index] = {
                            "list": url, "selector": selector, "index": index, "error": str(exc),
                        }
            finally:
                if page is not None:
                    await page.close()

        workers = max(1, min(concurrency or self.parallel_pages, self.parallel_pages, len(indexes) or 1))
        await self._finish_batch([worker() for _ in range(workers)])
        finished = [results.get(index, {
            "list": url, "selector": selector, "index": index,
            "error": "Program deadline reached", "stop_reason": "timeout",
        }) for index in indexes]
        for record in finished:
            self._remember_read("open_each", record, call)
        return finished

    # Not named _tool_*: registered only where the code can be confined.
    async def _run_playwright(self, code: str, timeout_s: Optional[float] = None, **kwargs) -> Dict[str, Any]:
        """Run the agent's Playwright program, confined, against the live page."""
        err = self._ensure_page()
        if err:
            return err
        from jarviscore.execution.coder_sandbox import BashPermissionError
        from jarviscore.execution.page_proxy import PageBroker

        if self._page_broker is None:
            self._page_broker = PageBroker(
                self._page, judge=self._judge_commits, pace=self._pace, settle=self._settle,
                reader=self._read_pages, opener=self._open_each,
            )
        broker = self._page_broker
        action_start = len(broker.actions)
        sandbox = self._sandbox_for_code()
        sandbox.browser_proxy = broker
        limit = min(float(timeout_s) if timeout_s is not None else self.code_timeout_s, self.code_timeout_s)
        tool_time = self._tool_time_s()
        if tool_time is not None:
            limit = min(limit, tool_time)
        if limit <= 0:
            return {"status": "error", "error": "The execution lease has no wall-clock time remaining."}
        current = getattr(self, "_current_state", None)
        context = getattr(current, "context", None) or {}
        before = json.dumps(getattr(self, "_browser_findings", {}), sort_keys=True, default=str)
        # The page stops serving the program at its deadline; killing the process is the backstop.
        broker.deadline = asyncio.get_running_loop().time() + limit
        broker.navigated = None
        try:
            outcome = await sandbox.execute(code, context={
                "prior_outputs": context.get("previous_step_results") or {},
                "browser_state": getattr(self, "_browser_findings", {}),
                "browser_reads": self._read_records(),
            }, timeout=limit + _CODE_DEADLINE_GRACE_S)
        except BashPermissionError as exc:
            return {"status": "error", "error": str(exc), "semantic_error": "CODE_NOT_CONFINABLE"}
        finally:
            broker.deadline = None
            sandbox.browser_proxy = None
        await self._settle()
        self._current_url = self._page.url
        earlier = json.loads(before)
        self._browser_findings = outcome.get("browser_state", broker.state)
        if outcome.get("status") == "success":
            wrote = [
                key for key, value in self._browser_findings.items()
                if json.dumps(value, sort_keys=True, default=str)
                != json.dumps(earlier.get(key), sort_keys=True, default=str)
            ]
            if wrote:
                self.__dict__.setdefault("_programs", []).append({"code": code, "wrote": wrote})
        result: Dict[str, Any] = {
            "status": "success" if outcome.get("status") == "success" else "error",
            "result": outcome.get("data"),
            "stdout": outcome.get("stdout") or "",
            "actions": broker.actions[action_start:],
            "url": self._page.url,
            "state_keys": list(self._browser_findings),
        }
        if result["status"] == "error":
            if outcome.get("session_reset"):
                self._page_broker = None
                result["session_reset"] = True
            result["error"] = (
                f"The code did not finish within {limit:g}s; the actions it took are listed."
                if outcome.get("error_type") == "ExecutionTimeout" else outcome.get("error")
            )
            result["error_type"] = outcome.get("error_type")
        return result

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
            findings = getattr(self, "_browser_findings", None)
            reads = list(self._read_records().values())
            calls = self._calls_behind_records()
            if findings or reads:
                payload = output.payload
                body = payload if isinstance(payload, dict) else (
                    {"result": payload} if payload is not None else {}
                )
                output.payload = {
                    **body,
                    **({"browser_state": findings} if findings else {}),
                    **({"browser_reads": reads} if reads else {}),
                    **({"browser_calls": calls} if calls else {}),
                }
                # The programs whose findings the step kept: the method, as code, for next time.
                if findings:
                    programs = [
                        program["code"] for program in getattr(self, "_programs", [])
                        if set(program["wrote"]) & (set(findings) - {"procedure"})
                    ]
                    if programs:
                        output.payload["browser_programs"] = programs
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
        if self._code_sandbox is not None:
            import shutil

            shutil.rmtree(self._code_sandbox.workspace, ignore_errors=True)
            self._code_sandbox = None
