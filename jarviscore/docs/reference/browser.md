---
icon: material/web-box
title: "Browser Reference: Tools, Approvals, Sessions and Proxies"
description: "Every BrowserSubAgent tool, how Playwright programs run confined, how consequential actions wait for approval, and how sessions, pacing and proxies work."
---

# Browser Reference

What a browser agent can do and how it behaves. To get one running, start with
the [Browser Automation guide](../guides/browser-automation.md). Every setting
named here is in [Configuration](configuration.md).

You don't call these tools yourself: the agent chooses them. This page tells you
what it can choose from, what it is never allowed to do, and what you can tune.

---

## Tools

| Tool | What it does | Main parameters |
|---|---|---|
| `navigate` | Opens a URL, waits for the page to settle, returns the page | `url`, `wait_for` (`domcontentloaded`, `load`, `commit`) |
| `snapshot` | The page as text, with a ref on everything it can act on | `ref` (read one region) |
| `screenshot` | An image of the page for the next model turn | `full_page` |
| `click` | Clicks an element | `ref`, `selector` or `text` |
| `type_text` | Types into a field, clearing it first | `ref` or `selector`, `text`, `clear_first`, `delay_ms` |
| `fill_form` | Fills a whole form, optionally submits it | `fields`, `submit` |
| `select_option` | Picks a dropdown value by value or label | `ref` or `selector`, `value` |
| `run_playwright` | Runs a Playwright program on the live page ([below](#browser-programs)) | `code`, `timeout_s` |
| `find` | The element that meets a goal, with alternatives | `goal` |
| `act` | Finds the element for a goal and clicks, types or selects it | `goal`, `action`, `text`, `value` |

`find` and `act` appear only when the Mesh has a
[decision model](../concepts/decision-models.md). `act` performs the action only
above `BROWSER_ACT_MIN_CONFIDENCE` (default 0.7); below it, it returns the
candidates.

## How the agent reads a page

A page comes back as a person reads it: headings, text, tables as rows,
notices and dialogs. Every element it can act on carries a ref:

```text
## Products
| SKU | Product | Price |
| rice-1kg | Basmati rice 1kg | £2.10 |
[e11] textbox "Search products"
[e12] button "Add to basket"
[e14] button "Place order" (disabled)
```

- `navigate` and every interaction return the page as it stands afterwards,
  so the agent never spends a turn just looking.
- Clickable table rows get refs; invisible frames (a closed chat widget) are
  left out.
- A ref lasts until the next page view. An old one returns `STALE_REF` and does
  nothing.
- An element that is disabled, hidden or covered (a cookie banner) is refused
  with `ELEMENT_NOT_ACTIONABLE`, naming what covers it, before anything is
  clicked.

## Browser programs

For work that spans many pages, the agent writes one `run_playwright` program
instead of making hundreds of clicks. Inside it, `page` is the live page and
these helpers are available:

| In a program | What it is for |
|---|---|
| `result = ...` | What the program returns to the agent, in full |
| `state` | A JSON dict that survives restarts and is handed to later steps |
| `await read_pages(urls, script)` | Read many pages at once, up to `BROWSER_PARALLEL_PAGES` (default 4) |
| `read_pages(..., next_page=, until=)` | Read paged histories, turning pages until `until` is true or `BROWSER_HISTORY_PAGES` (default 50) is reached |
| `await open_each(items, script)` | Open each item of a list that has no links (click, read, go back) |
| `reads` | Everything the step has already read, so it computes instead of reading again |
| `prior` | What earlier workflow steps delivered |

A history result says how it ended in `stop_reason`: `until` or `end` mean it
was read completely, while `page_limit`, `unchanged`, `error` and `timeout` mean
it was not. A step cannot finish while one of its reads is incomplete.

**It is confined.** The program runs in a separate process with no network and
no files outside a scratch folder; the real page is driven on its behalf. It
cannot reach the browser's cookies, intercept requests or upload files. Clicks,
submits and scripts that could commit the person raise
`ConsequentialActionRefused`, so the agent asks for approval instead.

**Time limits.** Each program runs for up to `timeout_s` (default
`BROWSER_CODE_TIMEOUT_S`, 600 s, and never past the step's remaining time). A
program that runs out of time keeps its variables and `state` for the next call.

**Where it is offered.** Only where the host can confine a process (macOS
`sandbox-exec`, Linux bubblewrap) or `allow_unsafe_local_execution` is set.

**Learned procedures.** Once a step is accepted, the program that did the work
is kept in memory. The next task on the same site starts from it and repairs
what has changed on the page.

## Consequential actions

Placing an order, sending a message, paying, deleting: anything that commits a
person waits for that person.

1. The agent marks the action with `irreversible` and a `consequence` in plain
   words:

    ```text
    TOOL: click
    PARAMS: {"ref": "e14", "irreversible": true,
             "consequence": "Places order for 3 items, £18.40, delivery Thu 10:00-12:00"}
    ```

2. Nothing is clicked. The step pauses with `WAITING_FOR_APPROVAL` and a
   [HITL](../guides/hitl.md) request describing the exact action, for example
   *Click "Place order" on shop.example/checkout*. No tokens are spent while
   it waits.
3. The person decides with `Mesh.resolve_hitl()` (or in a room's chat), and the
   step resumes:

| Decision | What happens |
|---|---|
| Approved | The page is reopened with the form values the person saw, the same element is found again, and the action runs once |
| Declined | Nothing runs; the agent reports it |
| The element is gone | Nothing runs; the agent must ask again |
| Something blocks it (a cookie banner) | Nothing runs and the approval stays open; the agent clears the blocker and tries again |

If the agent forgets to mark an action, it is judged first: one that could
commit the person returns `APPROVAL_REQUIRED` instead of running. Approvals need
a workflow step with Redis; without one the action is refused with
`APPROVAL_UNAVAILABLE`. `act` and browser programs never perform consequential
actions.

## Which browser is used

| Setting | Browser |
|---|---|
| `BROWSER_CONTROL_URL` | Your own open Chrome, over CDP. The agent works in a new tab and closes only that tab. |
| `BROWSER_PROFILE_DIR` | A persistent profile per tenant (the Mesh's `memory_scope_field`), so logins survive between runs. A step with no tenant gets a fresh browser. |
| neither | A fresh Chromium for each run |

- **Long tasks.** When a step runs out of execution time, its browser is kept
  for the step's next epoch, with the same page, form values and login, for up
  to `BROWSER_CONTINUATION_HOLD_S` (default 120 s).
- **One process per profile.** Chromium locks a profile. Runs for the same
  tenant take turns, and a profile held by another process is reported to the
  agent.

## How it behaves on a site

| Behaviour | Setting (default) |
|---|---|
| Spaces requests to one site, like a person browsing | `BROWSER_SITE_INTERVAL_S` (1.5 s) |
| Waits for the site's own data requests after each action, ignoring third-party analytics and chat | `BROWSER_DATA_TIMEOUT_MS` (10000) |
| Then waits for the page to stop changing | `BROWSER_SETTLE_TIMEOUT_MS` (3000) |
| Runs headless | `BROWSER_HEADLESS` (true) |

- **Access.** With a decision model, `navigate` reports whether the site turned
  the browser away (a block, a bot check or a captcha) in `access`, alongside
  `http_status`.
- **Identity.** The browser presents itself as the Chrome actually running, on
  your OS, rather than `HeadlessChrome`, which many sites refuse.
- **Screenshots** reach the model as images on every provider; traces keep a
  hash, not the pixels.

## Your own proxy

Many sites refuse cloud and datacenter IPs. JarvisCore supplies none; point it
at your own provider:

```bash title=".env"
EGRESS_PROXY_URL=http://user-session-{session}:pass@gw.provider.example:7000
EGRESS_PROXY_BYPASS=searxng,.internal
BROWSER_LOCALE=en-GB
BROWSER_TIMEZONE=Europe/London
```

- The browser and the pages the researcher reads go through the proxy. Model
  calls, search APIs, Nexus, loopback and `EGRESS_PROXY_BYPASS` hosts go
  direct.
- `{session}` becomes a stable id (per tenant with a profile, otherwise per
  workflow), so a login or checkout keeps one exit IP. Use your provider's
  session syntax.
- Match `BROWSER_LOCALE` and `BROWSER_TIMEZONE` to the proxy's region.
- `http://` and `https://` proxies only; Chromium cannot authenticate to SOCKS.
  An attached browser (`BROWSER_CONTROL_URL`) uses its own network instead.

A proxy is for reliability and region, not for getting past sites that forbid
automated access.
