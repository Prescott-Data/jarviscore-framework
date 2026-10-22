---
icon: material/web
title: "AI Browser Automation with Playwright and Computer Use"
description: "Give an AutoAgent a real browser: read JavaScript sites page after page, fill forms, stay logged in, and wait for approval before anything that commits you."
---

# Browser Automation

An `AutoAgent` can work a real Chromium browser: read sites that need
JavaScript, go through every page of a catalogue, log in, fill forms. You
describe the goal; the agent decides when the browser is the right tool.

Use it when a page has to be *used*. When it only has to be *read*, the
[researcher's](internet-search.md) `web_search` and `read_url` are faster and
cheaper, and the agent picks them on its own.

| Good fit | Use search instead |
|---|---|
| Sites that render with JavaScript (dashboards, single-page apps) | Static articles and docs |
| Every page of a listing, or every record behind a click | One page you already have the address of |
| Logging in, filling and submitting forms | Public APIs and feeds |

---

## Set up in three steps

**1. Install the browser extra and Chromium.**

```bash
pip install "jarviscore-framework[browser]"
playwright install chromium
```

**2. Turn the browser on** in `.env`, next to your model key:

```bash title=".env"
BROWSER_ENABLED=true
```

`BROWSER_MODEL` picks the model that drives the browser. Without it your
standard task model is used, which is enough for reading pages as text. Set it
to a computer-use or multimodal model (for example `gemini-2.5-computer-use`,
`gpt-5.4-mini` or `gpt-4o`) when the agent should also see screenshots.

**3. Give an agent a goal that needs a browser.**

```python title="catalogue.py"
import asyncio
from jarviscore import AutoAgent, Mesh


class Analyst(AutoAgent):
    role = "analyst"
    capabilities = ["web_research", "data_analysis", "reporting"]
    system_prompt = "You collect complete data, compute with code and report clearly."
    goal_oriented = True


async def main():
    mesh = Mesh()
    mesh.add(Analyst)
    await mesh.start()
    try:
        result = await mesh.run_task(agent="analyst", task=(
            "Collect every book in the Mystery category of https://books.toscrape.com, "
            "across all pages, with its title, price and star rating. Report how many "
            "there are, the count per rating, the average price and the three most "
            "expensive, and save the report as mystery_report.md."
        ))
        print(result["result_summary"])   # the answer
        print(result["evidence"])         # what it read and the files it wrote
    finally:
        await mesh.stop()


asyncio.run(main())
```

The agent opens the site, reads every page of the category in one Playwright
program, computes the figures in code and writes the report. `result_summary`
holds the answer; `evidence` lists the pages and files behind it. To watch it
work, add `BROWSER_HEADLESS=false` to `.env`.

---

## What the agent does on a page

- **Reads the page as text**, the way a person reads it: headings, tables as
  rows, notices, and a ref such as `[e12]` on everything it can act on.
- **Acts by ref:** `click`, `type_text`, `fill_form`, `select_option`. Each
  action returns the page as it stands afterwards. A covered or disabled
  element is refused with the reason, before anything is clicked.
- **Writes Playwright code** for work that spans many pages, so a whole listing
  is one step, not a hundred clicks. The code runs confined: no network and no
  files beyond its scratch space.
- **Waits for the site's data** after every action and **paces its requests**
  to each site the way a person browses.
- **Keeps what it read** in the step's record, so a later step or a crash
  recovery picks up where it was instead of reading the site again.

Every tool and its parameters are in the [Browser Reference](../reference/browser.md#tools).

---

## Always use the browser

An agent with a goal chooses its tools. To make one a browser agent on every
task, declare it:

```python
class PortalAgent(AutoAgent):
    role = "portal"
    capabilities = ["portal_operations"]
    system_prompt = "You operate our supplier portal."
    default_kernel_role = "browser"
```

---

## Consequential actions

Placing an order, sending a message, paying, deleting: anything that commits
the person waits for that person's approval. The agent proposes the exact
action ("Click *Place order* on shop.example/checkout: 3 items, £18.40"),
the step pauses, and no tokens are spent while it waits. Approved, JarvisCore
reopens the page, restores what the person saw and performs that one action
once. Declined, nothing happens.

The agent does not have to remember to ask: a click or submit it did not mark
is judged first, and one that could commit the person is refused until it is
approved. Approvals need a workflow step with Redis
([HITL Escalation](hitl.md)). The full rules are in the
[Browser Reference](../reference/browser.md#consequential-actions).

---

## Recipes

### Use the browser you already have open

Start Chrome with `--remote-debugging-port=9222`, then:

```bash title=".env"
BROWSER_CONTROL_URL=http://127.0.0.1:9222
```

The agent opens its own tab in your browser, with your logins, and closes only
that tab. You watch it work and can take over in the same window.

### Stay logged in between runs

```bash title=".env"
BROWSER_PROFILE_DIR=.jarviscore/browser-profiles
```

Each tenant gets its own persistent profile, so cookies and logins survive
restarts. A step that names no tenant gets a fresh browser, never someone
else's profile.

### Behind your own proxy

Many sites refuse cloud and datacenter IPs. JarvisCore supplies none; point it
at your provider:

```bash title=".env"
EGRESS_PROXY_URL=http://user-session-{session}:pass@gw.provider.example:7000
BROWSER_LOCALE=en-GB
BROWSER_TIMEZONE=Europe/London
```

`{session}` becomes a stable id, so a login or checkout keeps one exit IP.
Model calls, search APIs and Nexus go direct. Details, including
`EGRESS_PROXY_BYPASS`, are in the [Browser Reference](../reference/browser.md#your-own-proxy).

### Long tasks

A task that outlasts one execution epoch keeps its browser: the next epoch
continues on the same page, with forms, basket and login intact
([Session lifecycle](../reference/browser.md#which-browser-is-used)).

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
| `navigate` result has `"access": {"denied": true}` | The site turned the browser away (block, bot check, captcha) | The page was not served. Datacenter IPs are often refused; set [`EGRESS_PROXY_URL`](#behind-your-own-proxy) to your own provider |
| `APPROVAL_REQUIRED` | The agent clicked or submitted something that could commit the person without marking it | Nothing was done; the agent re-issues it with `irreversible` and `consequence` |
| `APPROVAL_UNAVAILABLE` | A consequential action without durable workflow state | Run the agent in a Mesh workflow step with Redis configured |
| `find` and `act` are missing | No decision model on the Mesh | Configure a [decision model](../concepts/decision-models.md) |
| Step resumes on a fresh page after its epoch ended | The continuation came after `BROWSER_CONTINUATION_HOLD_S` | Raise `BROWSER_CONTINUATION_HOLD_S` |

---

## Next

- [Browser Reference](../reference/browser.md): every tool, programs, approvals, sessions and pacing
- [Configuration](../reference/configuration.md): every `BROWSER_*` setting
- [AutoAgent Guide](autoagent.md): execution budgets for the browser role
- [Internet Search](internet-search.md): the researcher, for pages that only need reading
