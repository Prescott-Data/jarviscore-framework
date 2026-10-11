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

The browser sub-agent registers the following tools. The LLM calls them by emitting `TOOL: <name>` in its OODA loop turns.

### Seeing the page

`snapshot` is how the agent reads a page. It returns the page as a person reads it: headings, text, tables as rows, notices and dialogs, with a ref such as `[e12]` (or `[f3e12]` inside a frame) on every element that can be acted on and its state, for example `(disabled)`. Every interaction tool accepts that ref. A ref names an element only in the snapshot it came from, so the agent takes a new snapshot after the page changes.

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
| `navigate` | Go to a URL and wait for load. The result includes `http_status` and, when a decision model is configured, `access` (whether the site turned the browser away) | `url`, `wait_for` (`networkidle`\|`domcontentloaded`\|`load`) |
| `close_page` | Close current page, open a fresh one |, |

### Inspection

| Tool | Description | Key parameters |
|---|---|---|
| `get_text` | Extract text from an element or the full page | `ref` or `selector` (neither = full page), `max_chars` (default 5000) |
| `get_attribute` | Get an attribute value from an element | `selector`, `attribute` |
| `get_links` | Extract all `<a>` links from the page | `selector` (optional scope), `max` (default 50) |
| `get_cookies` | Get cookies for the current page, returns name, domain, path only (httpOnly values are not exposed) |, |

### Interaction

An element that is disabled, hidden, or covered by something else (a cookie dialog, a modal) is refused at once with the reason, before anything is clicked.

| Tool | Description | Key parameters |
|---|---|---|
| `click` | Click an element | `ref`, or `selector` (CSS), or `text` (visible text) |
| `type_text` | Type text into an input, clears field first by default | `ref` or `selector`, `text`, `clear_first` (default true), `delay_ms` (default 50) |
| `fill_form` | Fill multiple form fields in one call | `fields: [{"ref" or "selector": "...", "value": "..."}]` |
| `select_option` | Select a `<select>` dropdown value by value or label | `ref` or `selector`, `value` |
| `scroll` | Scroll the page | `direction` (`down`\|`up`\|`top`\|`bottom`), `pixels` (default 500) |

### With a decision model

When the Mesh has a [decision model](../concepts/decision-models.md), two more tools let the agent pick an element by goal instead of reading every ref.

| Tool | Description | Key parameters |
|---|---|---|
| `find` | The element that accomplishes a goal: its ref, confidence and the closest alternatives | `goal` |
| `act` | Find the element for a goal and click, type into or select it in one step. Below `BROWSER_ACT_MIN_CONFIDENCE` (default 0.7) it returns the candidates instead of acting. It never performs a consequential action: the decision model is asked whether the action would commit the person, and if so it returns the ref for an explicit, approved action | `goal`, `action` (`click`\|`type`\|`select`), `text`, `value` |

### Waiting

| Tool | Description | Key parameters |
|---|---|---|
| `wait_for` | Wait for an element to reach a state | `selector`, `timeout_ms` (default 10000), `state` (`visible`\|`hidden`\|`attached`\|`detached`) |

### JavaScript

| Tool | Description | Key parameters |
|---|---|---|
| `evaluate` | Execute a JavaScript expression on the page and return the result | `script` |

---

## Consequential actions

Placing an order, sending a message, paying, deleting: an action that commits
the person waits for that person's approval. The agent marks it by adding
`"irreversible": true` and `"consequence"` (what will happen, in the person's
words) to `click`, `type_text`, `fill_form`, `select_option` or `evaluate`:

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
`act` never performs a consequential action; it hands back the ref so the agent
proposes it explicitly. Approvals need durable workflow state (a Redis store
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
- `close_page` opens a fresh page but keeps the same browser context (cookies survive)
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
- **Settling.** After a click or typing (including through `act`), the page is
  given up to `BROWSER_SETTLE_TIMEOUT_MS` (default 3000) to finish loading what
  the action started before the agent looks again. A page that keeps a
  connection open is still used once the time is up.
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
    2. Read the page with snapshot() and act on elements by their ref.
    3. Take a new snapshot after the page changes; take a screenshot when the
       layout matters.
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
| Page load timeout | `networkidle` timeout (30s default) | Add `wait_for: "domcontentloaded"` in the navigate call for slow pages |
| Element not found | Stale ref or page not fully loaded | Take a new `snapshot` after the page changes and use its refs |
| `ELEMENT_NOT_ACTIONABLE` from `click` or `type_text` | The element is disabled, hidden or covered (often a cookie dialog) | The error names what covers it; deal with that first, then act again |
| `navigate` result has `"access": {"denied": true}` | The site turned the browser away (block, bot check, captcha) | The page was not served. Datacenter IPs are often refused; set [`EGRESS_PROXY_URL`](#your-own-proxy) to your own provider |
| `APPROVAL_UNAVAILABLE` | A consequential action without durable workflow state | Run the agent in a Mesh workflow step with Redis configured |
| `find` and `act` are missing | No decision model on the Mesh | Configure a [decision model](../concepts/decision-models.md) |
| Step resumes on a fresh page after its epoch ended | The continuation came after `BROWSER_CONTINUATION_HOLD_S` | Raise `BROWSER_CONTINUATION_HOLD_S` |

---

## Further Reading

- [AutoAgent Guide](./autoagent.md), execution budgets for the browser role (60k thinking + 60k action tokens, 5 min wall clock, 28-turn fuse)
- [Internet Search](./internet-search.md), the researcher's alternative for pages that don't need a real browser
- [Model Routing](../concepts/model-routing.md), CUA and multimodal model requirements for the browser tier
