---
icon: material/web
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

### Navigation

| Tool | Description | Key parameters |
|---|---|---|
| `navigate` | Go to a URL and wait for load | `url`, `wait_for` (`networkidle`\|`domcontentloaded`\|`load`) |
| `close_page` | Close current page, open a fresh one |, |

### Inspection

| Tool | Description | Key parameters |
|---|---|---|
| `get_text` | Extract text from an element or the full page | `selector` (empty = full page), `max_chars` (default 5000) |
| `get_attribute` | Get an attribute value from an element | `selector`, `attribute` |
| `get_links` | Extract all `<a>` links from the page | `selector` (optional scope), `max` (default 50) |
| `get_cookies` | Get cookies for the current page, returns name, domain, path only (httpOnly values are not exposed) |, |
| `screenshot` | Take a PNG screenshot, returned as base64 in the LLM context | `full_page` (default false) |

### Interaction

| Tool | Description | Key parameters |
|---|---|---|
| `click` | Click an element by CSS selector or visible text | `selector` (CSS), `text` (text match, used if selector is empty) |
| `type_text` | Type text into an input, clears field first by default | `selector`, `text`, `clear_first` (default true), `delay_ms` (default 50) |
| `fill_form` | Fill multiple form fields in one call | `fields: [{"selector": "...", "value": "..."}]` |
| `select_option` | Select a `<select>` dropdown value by value or label | `selector`, `value` |
| `scroll` | Scroll the page | `direction` (`down`\|`up`\|`top`\|`bottom`), `pixels` (default 500) |
| `hover` | Hover over an element | `selector` |

### Waiting

| Tool | Description | Key parameters |
|---|---|---|
| `wait_for` | Wait for an element to reach a state | `selector`, `timeout_ms` (default 10000), `state` (`visible`\|`hidden`\|`attached`\|`detached`) |

### JavaScript

| Tool | Description | Key parameters |
|---|---|---|
| `evaluate` | Execute a JavaScript expression on the page and return the result | `script` |

---

## Session lifecycle

One Chromium browser is launched **per `run()` call**, not per task dispatch. If the Kernel dispatches the same workflow step to `BrowserSubAgent` multiple times (e.g. two browser-classified steps in the same workflow), each dispatch gets its own browser session.

Within a single `run()`:
- Pages are reused, so cookies and auth state persist across tool calls
- `close_page` opens a fresh page but keeps the same browser context (cookies survive)
- The browser is closed unconditionally when `run()` exits via the `finally` block of `_post_run_hook()`

The browser launch arguments disable sandbox and automation flags to reduce detection:
```
--no-sandbox
--disable-setuid-sandbox
--disable-dev-shm-usage
--disable-blink-features=AutomationControlled
```

The user agent is set to a realistic Chrome string to avoid bot detection on common sites.

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
    2. Use wait_for() to confirm interactive elements are present before clicking.
    3. Take a screenshot if you are unsure about page state.
    4. Store all extracted data in a variable named `result`.
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

The `BrowserController` in `jarviscore.browser` supports connecting to an already-running Chromium instance via Chrome DevTools Protocol. This is useful for testing against a persistent browser profile or for debugging. The `BrowserSubAgent` itself always launches its own browser, CDP connection is available through `BrowserController` directly if you need it for custom tooling.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Task not routed to browser | `BROWSER_ENABLED` not set | Add `BROWSER_ENABLED=true` to `.env` |
| `Playwright not installed` error in tool result | Playwright not installed | `pip install playwright && playwright install chromium` |
| `Browser not initialized` error from tools | Playwright launched but Chromium failed | Check system dependencies; try running `playwright install chromium` again |
| Page load timeout | `networkidle` timeout (30s default) | Add `wait_for: "domcontentloaded"` in the navigate call for slow pages |
| Element not found | Selector wrong or page not fully loaded | Use `wait_for` before `click` or `type_text`; use `screenshot` to inspect page state |

---

## Further Reading

- [AutoAgent Guide](./autoagent.md), execution budgets for the browser role (60k thinking + 60k action tokens, 5 min wall clock, 28-turn fuse)
- [Internet Search](./internet-search.md), the researcher's alternative for pages that don't need a real browser
- [Model Routing](../concepts/model-routing.md), CUA and multimodal model requirements for the browser tier
