---
icon: material/web
title: "AI Browser Automation with Playwright and Computer Use"
description: "Automate navigation, forms, and JavaScript-heavy websites with BrowserSubAgent using computer-use and multimodal language models."
---

# Browser Automation

JarvisCore's `BrowserSubAgent` drives a real Chromium browser via Playwright. It is activated when the Kernel routes a task to the `browser` role through a structured routing decision or by setting `default_kernel_role = "browser"` on your `AutoAgent`.

The browser subagent is **not** a replacement for web search. Use it only when the target page requires JavaScript execution, cookie-based authentication, interactive UI automation, or form submission. For static content and API-based research, the `ResearcherSubAgent`'s `web_search` and `read_url` tools are faster and cheaper.

---

## Installation

Playwright is not bundled with JarvisCore. Install it separately:

```bash
pip install playwright
playwright install chromium
```

JarvisCore imports Playwright lazily, the framework loads and runs correctly without it. When Playwright is not installed and a task is routed to the `browser` role, the sub-agent returns a clear error message rather than crashing.

---

## Enabling browser automation

Set `BROWSER_ENABLED=true` in your `.env`. Without this, the browser role should not be selected for normal tasks, even if Playwright is installed.

Also set `BROWSER_MODEL` to a CUA or multimodal model. Without it, the framework falls back to `TASK_MODEL_STANDARD`, which may be a text-only model that cannot interpret screenshots.

```bash title=".env"
BROWSER_ENABLED=true

# CUA model for browser automation (strongly recommended)
# Gemini:  BROWSER_MODEL=gemini-2.5-computer-use
# OpenAI:  BROWSER_MODEL=gpt-5.4-mini
# Fallback (multimodal, not CUA): BROWSER_MODEL=gpt-4o or gemini-2.5-flash
BROWSER_MODEL=gemini-2.5-computer-use

# Defaults to true (headless). Set false to see the browser window during development.
BROWSER_HEADLESS=true
```

The kernel reads `browser_headless` from settings and passes it to `BrowserSubAgent` at instantiation. The default viewport is `1280x720`, hardcoded in `BrowserSubAgent.__init__()` and not currently configurable via environment variable.

---

## How routing works

The Kernel routes tasks with a structured router. The router sees the task, context summary, valid roles, and role contracts, then returns a typed decision with confidence and reason. Invalid or low-confidence routing fails visibly instead of guessing.

A Mesh step that names the agent's own browser (`systems: ["browser"]`) goes to the browser sub-agent without a router call.

You can also make browser routing explicit by declaring it on your agent class:

```python
class MyAgent(AutoAgent):
    role = "web-scraper"
    capabilities = ["scraping"]
    system_prompt = "..."
    default_kernel_role = "browser"   # always routes to BrowserSubAgent
```

---

## Tools available to the LLM

The browser sub-agent registers the following tools. On providers that support native tool calls, the LLM calls them as functions; otherwise it emits `TOOL: <name>` in its OODA loop turns. See [Completion and result contracts](../concepts/contracts.md#completion-and-result-contracts).

### Seeing the page

`snapshot` is how the agent reads a page. It returns the page as a person reads it: headings, text, tables as rows, notices and dialogs, with a ref such as `[e12]` (or `[f3e12]` inside a frame) on every element that can be acted on and its state, for example `(disabled)`. Elements the page makes clickable without giving them a link or button role, such as a table row that opens a record, carry a ref too. Content a person cannot see is left out: a frame that is transparent, hidden or has no size (a closed support-chat widget, for example) does not appear. Every interaction tool accepts a ref. A ref lasts only until the next page view or page load; using an older one returns `STALE_REF` without acting.

`navigate` and the simple interactions (`click`, `type_text`, `fill_form`, `select_option` and `act`) return the page as it stands afterwards, in the same form, so the agent reads the result of an action without spending a turn on a separate snapshot. Only the latest page view stays in the agent's context; earlier ones are replaced by a pointer to `read_turn_result`. Code results remain ordinary data rather than replaceable page views.

```text
## Products
| SKU | Product | Price |
| rice-1kg | Basmati rice 1kg | £2.10 |
[e11] textbox "Search products"
[e12] button "Add to basket"
[e14] button "Place order" (disabled)
```

| Tool | Description | Key parameters |
|---|---|---|
| `snapshot` | The page as a person reads it, with refs on what can be acted on | `ref` (optional: read one region) |
| `screenshot` | See the current page; the image is attached to the next model turn | `full_page` (default false) |

### Navigation

| Tool | Description | Key parameters |
|---|---|---|
| `navigate` | Go to a URL, wait for the document and for the page to stop changing, and return the page. The result includes `http_status` and, when a decision model is configured, `access` (whether the site turned the browser away) | `url`, `wait_for` (default `domcontentloaded`; also `load`, `commit`) |

### Interaction

An element that is disabled, hidden, or covered by something else (a cookie dialog, a modal) is refused at once with the reason, before anything is clicked. The check looks at the point a click would land on; an element laid out without a box of its own (`display: contents`, common for table rows) is checked across the area its content covers and receives the click itself.

| Tool | Description | Key parameters |
|---|---|---|
| `click` | Click an element | `ref`, or `selector` (CSS), or `text` (visible text) |
| `type_text` | Type text into an input, clears field first by default | `ref` or `selector`, `text`, `clear_first` (default true), `delay_ms` (default 50) |
| `fill_form` | Fill a whole form in one call, then optionally submit it | `fields: [{"ref" or "selector": "...", "value": "..."}]` (`"checked": true/false` for checkboxes and radios), optional `submit` ref |
| `select_option` | Select a `<select>` dropdown value by value or label | `ref` or `selector`, `value` |

### With a decision model

When the Mesh has a [decision model](../concepts/decision-models.md), two more tools let the agent pick an element by goal instead of reading every ref.

| Tool | Description | Key parameters |
|---|---|---|
| `find` | The element that accomplishes a goal: its ref, confidence and the closest alternatives | `goal` |
| `act` | Find the element for a goal and click, type into or select it in one step. Below `BROWSER_ACT_MIN_CONFIDENCE` (default 0.7) it returns the candidates instead of acting. It never performs a consequential action: the decision model is asked whether the action would commit the person, and if so it returns the ref for an explicit, approved action | `goal`, `action` (`click`\|`type`\|`select`), `text`, `value` |

### Code

`run_playwright` runs a Python Playwright program against the live page, so work
that spans many views (every row, every page back to a date, each item in a
list) is one tool call rather than one per step. Where it is offered, the
agent's prompt makes it the default for anything beyond a single interaction.

| Tool | Description | Key parameters |
|---|---|---|
| `run_playwright` | Run Python Playwright code against the live page. `page` exposes the confined Playwright API; top-level `await` works. Set `result` to the observations to return; printed diagnostics and the action log come back too. Variables, helpers and locators persist within the code session | `code`, optional `timeout_s` (defaults to `BROWSER_CODE_TIMEOUT_S`, 600; bounded by the remaining execution lease) |

**Session.** The confined process lives for the browser step, across execution
epochs while its page stays open. A code error keeps earlier variables. At a
program's `timeout_s` the page stops serving it: its next page call raises
`PlaywrightTimeoutError`, so it ends with its variables and `state` kept for the
next call. A program that keeps running without the page for 30 s more is
stopped and its process reset (`session_reset`); teardown reaps it.

**State.** `state` is a JSON dictionary for inventories, URLs, findings and
coverage. Each page operation sends its current value to the parent; completed
code calls also save findings, programs and the current URL into the step's
checkpoint. These JSON values restore after a process restart; local variables
and locators do not. The step artifact carries findings as `browser_state`,
partial work included. Later steps read it whole through `prior` in code or
`read_workflow_step`; prompts carry its keys and size instead of repeating it.
The tool returns `state_keys`; values the model needs go through
`result`. Once the step is accepted, `state["procedure"]` (the reusable
navigation and extraction method, not findings) is retained in Athena through
UnifiedMemory.

**Results.** The result and printed output reach the model whole, and are not
replaced by later page snapshots.

**Many pages at once.** `await read_pages(urls, script)` reads a collection once
its addresses are known: the parent opens up to `BROWSER_PARALLEL_PAGES`
(default 4) pages in the same session, paced per site and settled like any
navigation, runs the JavaScript function on each, and returns one result per
address in order (`url`, `final_url`, `http_status`, `value`, or `error`). The
script is judged once per site; the pages it opened are closed again. At the
program deadline, batches cancel and await every worker's cleanup before
returning completed observations and explicit timeout records in input order.

**Histories over several pages.** With `next_page` (the control that turns the
page) and `until` (a function, called with what the script returned on that
page, that is true once the page has gone past the period: it shows an entry
from before the period began), `read_pages` reads each address
as a history, all of them at once: it runs the script, clicks the control, waits
for the page's data and repeats. Each result holds `values` (one per page),
`pages` and `more`, which is true when the history goes on beyond what was read:
past `BROWSER_HISTORY_PAGES` (default 50) pages, when the control did not turn
the page (its content stayed the same), or after interruption. `stop_reason`
distinguishes `until`, `end`, `page_limit`, `unchanged`, `error` and `timeout`;
only `until` and `end` close a history. Already-read pages remain in the result
on failure. `until` means the supplied boundary function returned true, not
that the runtime independently verified the requested period. The page-turn
click and `until` are judged once per site.

**Records the step keeps.** Every collection record a step reads, as a tool or
inside a program, is kept by the runtime. A program sees them as `reads`, a
dictionary keyed by address (`read_pages`) or by `"<list url>#<selector>#<index>"`
(`open_each`), so it computes over what was read instead of reading the site
again. A later read of the same address or item replaces the earlier record,
except that an unfinished read never replaces a finished one. `done` is refused
while any current record is open.

**Items that open on click.** `await open_each(items, script)` is for lists
whose items have no links. `items` is the locator the agent would click them
by, filters included, for example
`page.locator("tbody tr")`;
`open_each(list_url, selector, script)` names the list page instead. Each of
up to `BROWSER_PARALLEL_PAGES` pages loads the list once, then opens its share
of the items in turn: it clicks one, waits for what opens, runs the script, and
goes back. It returns each item's `index`, the `url` it opened and its `value`.
The click is judged once, from the selector and the items' texts. Live, it
opened all 26 Hightouch syncs in 65 seconds, and `read_pages` then read their
26 run histories in 73.

**Procedures as code.** A program that writes findings the step keeps in `state`
is recorded. When the step is accepted and its collection reads are closed,
`state["procedure"]` is retained in Athena together with those programs. A later
run whose task names that site runs those programs before the first turn and
repairs where the live page no longer matches. The collection calls behind the
step's current records (`browser_calls`: addresses, script, `next_page`,
`until`, list and selector) are retained with it, or on their own when the
agent wrote no procedure; a later task on the site recalls them and adapts
dates, scope and boundaries. An open read (`more`, or
`stop_reason` of `timeout`, `error` or `page_limit`) is not completion, and a
lease expiry does not turn it into success.

**Confinement.** The program runs in the Coder's confined child process: no
network, no files outside a scratch workspace. `page` is a proxy; the parent
performs each call on the real page. Locators, frames, keyboard, mouse and
responses are reachable; the browser, its context and cookies, request
interception, file uploads and host paths are refused. Navigation is paced and
actions settle as with the simple tools; a wait for `networkidle` gets the same
settling. An element action on something missing, disabled, hidden or covered
fails at once with the reason (for example, the dialog covering it) instead of
waiting out Playwright's timeout. Clicks, submitting key presses (Enter, Space), selects and scripts are
judged first by the decision model (or the agent's model). One that could
commit the person raises `ConsequentialActionRefused`, and the agent makes it
an approved action; a judgement that fails refuses the action.

The tool is offered only where the host can confine a child process (macOS
`sandbox-exec`, Linux bubblewrap) or `allow_unsafe_local_execution` is set.

---

## Consequential actions

Placing an order, sending a message, paying, deleting: an action that commits
the person waits for that person's approval. The agent marks it by adding
`"irreversible": true` and `"consequence"` (what will happen, in the person's
words) to `click`, `type_text`, `fill_form` or `select_option`:

```text
TOOL: click
PARAMS: {"ref": "e14", "irreversible": true,
         "consequence": "Places order for 3 items, £18.40, delivery Thu 10:00-12:00"}
```

The action is not performed. JarvisCore raises a typed [HITL](./hitl.md)
approval (`critical_action`) describing the exact element and page, for example
*Click "Place order" on shop.example/checkout*, and the step pauses with
`WAITING_FOR_APPROVAL`. The run stops; no tokens are spent while it waits.

When the person decides, the step resumes and JarvisCore carries out the
decision before the agent's next turn:

- **Approved.** JarvisCore reopens the page, restores the form values the person
  saw when approving (a reload loses them), finds the same element again by what
  it is rather than by its old ref, and performs the action through the normal
  tool path. The agent receives the receipt and observes the result.
- **Declined.** The action is never performed; the agent reports that outcome.
- **No longer there.** If the approved element is gone, nothing is performed
  and the agent must propose the action again for a new decision.
- **Blocked.** If something stops the action (a cookie dialog covering the
  button, a disabled control), nothing happened, so the approval stays open.
  The agent clears what blocked it and calls the same action again; it runs then.

One approval covers one exact action in one workflow step, and an approved
action runs at most once: calling it again returns its recorded outcome.
A `click`, `select_option`, submitting `fill_form` or submitting `type_text`
the agent did not mark is judged first by the decision model (or the agent's
model); one that could commit the person is not performed and returns
`APPROVAL_REQUIRED`, so the agent re-issues it marked. A judgement that fails
refuses the action.
`act` and `run_playwright` never perform a consequential action; `act` hands
back the ref so the agent proposes it explicitly. Approvals need durable workflow state (a Redis store
and a workflow step); without it the action is refused with
`APPROVAL_UNAVAILABLE`.

---

## Session lifecycle

The browser a run works in depends on configuration:

| Setting | Browser |
|---|---|
| `BROWSER_CONTROL_URL` | The browser the person already has open, attached over CDP. The run opens its own tab and closes only that tab. |
| `BROWSER_PROFILE_DIR` | A persistent profile per tenant, so logins and cookies survive between runs. The tenant is the Mesh's `memory_scope_field`; a step that names no tenant gets a fresh browser, never someone else's profile. Without a scope field the Mesh has one shared profile. |
| neither | A fresh Chromium for each `run()` call. |

Within a single `run()`:
- Pages are reused, so cookies and auth state persist across tool calls
- What the run opened is closed when `run()` exits; an attached browser stays open

A long task can outlast one execution epoch. When `run()` ends because the
epoch ran out (`epoch_exhausted`), the browser is not closed: it is held for
the same workflow step's next epoch, which continues on the same page with its
form values, basket and login intact, and with the conversation so far. If no
continuation arrives within `BROWSER_CONTINUATION_HOLD_S` (default 120 s), the
held browser is closed. Any other ending closes it at once.

### Pace, settling and access

- **Pace.** Requests to the same site are spaced by `BROWSER_SITE_INTERVAL_S`
  (default 1.5 s), the way a person's browsing is spaced, across every run in
  the process.
- **Settling.** After navigating, clicking or typing (through any tool or code),
  the browser waits for the document to load, then for the site's own fetch and
  XHR requests to finish (up to `BROWSER_DATA_TIMEOUT_MS`, default 10000), then
  for the page to stop changing for half a second (up to
  `BROWSER_SETTLE_TIMEOUT_MS`, default 3000). Client-rendered apps are read with
  their data. Requests to other domains (analytics, session replay, chat) and
  requests abandoned by a navigation are not waited for. When time runs out, the
  page is returned as it stands.
- **Access.** With a decision model configured, `navigate` reports whether the
  site served the page or turned the browser away (an access block, bot check
  or captcha): `"access": {"denied": true, "probability": 0.97, "decision_request_id": "..."}`.
  The agent reads this as evidence, alongside `http_status` and the page itself.

Chromium locks a profile to one process. Runs for the same tenant in one
process take turns; if another process holds the profile, the browser tools
report that error to the agent.

Screenshots reach the model as images on every provider (Azure OpenAI,
Claude, Gemini, Vertex AI, vLLM). The tool result keeps a receipt with the
image's hash and size, not the pixels.

The browser launch arguments disable sandbox and automation flags to reduce detection:
```
--no-sandbox
--disable-setuid-sandbox
--disable-dev-shm-usage
--disable-blink-features=AutomationControlled
```

Headless Chromium announces itself as `HeadlessChrome`, which sites behind bot
defences refuse outright. The browser instead identifies as the Chrome that is
actually running, on the operating system it runs on: the real version and
platform, given consistently in the `User-Agent` header and the client hints
(set over CDP for every page the run opens).

### Your own proxy

Where traffic comes from matters as much as how the browser presents itself:
many sites refuse datacenter and cloud IPs outright. JarvisCore supplies no IP
addresses; point it at your own proxy provider (residential or ISP proxies for
reputation, a regional pool for local content):

```bash title=".env"
EGRESS_PROXY_URL=http://user-session-{session}:pass@gw.provider.example:7000
EGRESS_PROXY_BYPASS=searxng,.internal
BROWSER_LOCALE=en-GB
BROWSER_TIMEZONE=Europe/London
```

- The browser and the pages the researcher reads leave through the proxy.
  Search-provider APIs, LLM calls and Nexus authenticate by key and go direct;
  loopback and the hosts in `EGRESS_PROXY_BYPASS` go direct too.
- `{session}` is replaced with a stable id: per tenant when the browser uses a
  persistent profile, otherwise per workflow. Providers that pin an exit IP to
  a session id in the username then keep one IP for a whole login or
  checkout, which breaks if the IP changes underneath it. Use the session
  syntax your provider documents.
- Set `BROWSER_LOCALE` and `BROWSER_TIMEZONE` to the proxy's region so the
  browser's language and clock agree with where its traffic comes from.
- An attached browser (`BROWSER_CONTROL_URL`) leaves from its own network; the
  proxy is not applied. Hosted browser services that manage IPs themselves are
  attached this way.
- Only `http://` and `https://` proxies are accepted; Chromium cannot
  authenticate to a SOCKS proxy.

When a site still turns the browser away, `navigate` reports it in `access`.
A proxy is for reliability and region, not for getting past sites that forbid
automated access.

---

## What tasks suit `BrowserSubAgent`

Good fits:
- Logging into a web application and extracting account data
- Filling and submitting forms that don't have an API
- Scraping JavaScript-rendered content (SPAs, dashboards)
- Automating multi-step UI workflows
- Downloading files via browser interactions

Poor fits, use the Researcher instead:
- Reading static HTML pages (use `read_url`)
- Querying public APIs (use `web_search` or a Nexus atom)
- Fetching RSS feeds or structured data endpoints

---

## Example agent

```python title="agents/dashboard_scraper.py"
from jarviscore import AutoAgent

class DashboardScraper(AutoAgent):
    role = "scraper"
    capabilities = ["web-scraping", "dashboard"]
    default_kernel_role = "browser"
    system_prompt = """
    You are a web automation specialist. Your task is to log into dashboards and
    extract structured data. Always:
    1. Call navigate() first.
    2. Read the page each action returns and act on elements by their ref.
    3. Take a screenshot when the layout matters.
    4. Report the figures exactly as the page shows them, with the page they came from.
    """
```

```python title="main.py"
from jarviscore import Mesh
from agents.dashboard_scraper import DashboardScraper

mesh = Mesh()
mesh.add(DashboardScraper)
await mesh.start()

results = await mesh.workflow("dashboard-job", [
    {
        "id":    "extract",
        "agent": "scraper",
        "task":  "Navigate to https://app.example.com/login, log in with username 'admin' "
                 "and password from the DASHBOARD_PASSWORD env var, then extract the "
                 "monthly revenue figure from the summary panel.",
    }
])
```

---

## Connecting to an existing browser (CDP)

Start Chrome with `--remote-debugging-port=9222` and set
`BROWSER_CONTROL_URL=http://127.0.0.1:9222`. `BrowserSubAgent` and the
Researcher both attach to it, so the person watches the agent work and can take
over in the same window.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Task not routed to browser | `BROWSER_ENABLED` not set | Add `BROWSER_ENABLED=true` to `.env` |
| `Playwright not installed` error in tool result | Playwright not installed | `pip install playwright && playwright install chromium` |
| `Browser not initialized` error from tools | Playwright launched but Chromium failed | Check system dependencies; try running `playwright install chromium` again |
| Page read as a loading shell or empty table | The site's data took longer than `BROWSER_DATA_TIMEOUT_MS` | Raise `BROWSER_DATA_TIMEOUT_MS` for slow back ends |
| Element not found | Stale ref or page not fully loaded | Take a new `snapshot` after the page changes and use its refs |
| `STALE_REF` | The ref came from an earlier snapshot or the page reloaded | Nothing was done; take a new `snapshot` and use its refs |
| `ELEMENT_NOT_ACTIONABLE` from `click` or `type_text` | The element is disabled, hidden or covered (often a cookie dialog) | The error names what covers it; deal with that first, then act again |
| `navigate` result has `"access": {"denied": true}` | The site turned the browser away (block, bot check, captcha) | The page was not served. Datacenter IPs are often refused; set [`EGRESS_PROXY_URL`](#your-own-proxy) to your own provider |
| `APPROVAL_REQUIRED` | The agent clicked or submitted something that could commit the person without marking it | Nothing was done; the agent re-issues it with `irreversible` and `consequence` |
| `APPROVAL_UNAVAILABLE` | A consequential action without durable workflow state | Run the agent in a Mesh workflow step with Redis configured |
| `find` and `act` are missing | No decision model on the Mesh | Configure a [decision model](../concepts/decision-models.md) |
| Step resumes on a fresh page after its epoch ended | The continuation came after `BROWSER_CONTINUATION_HOLD_S` | Raise `BROWSER_CONTINUATION_HOLD_S` |

---

## Further Reading

- [AutoAgent Guide](./autoagent.md), execution budgets for the browser role (300k thinking + 900k action tokens, 5 min wall clock, 28-turn fuse)
- [Internet Search](./internet-search.md), the researcher's alternative for pages that don't need a real browser
- [Model Routing](../concepts/model-routing.md), CUA and multimodal model requirements for the browser tier
