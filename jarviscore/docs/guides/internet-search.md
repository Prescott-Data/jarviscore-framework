---
icon: material/earth
title: "Internet Search for AI Agents with Multiple Providers"
description: "How the researcher searches: Google grounding first, then Serper and SearXNG, then arXiv and Crossref, with ranking, timeouts and per-call exclusions."
---

# Internet Search

The researcher searches the web with `InternetSearch`. It works out of the box
with a Gemini key, and you can add Serper or your own SearXNG. Agents use it on
their own; you only choose the providers.

---

## How it works

Providers are tried in tiers, most authoritative first. The providers in a tier
run in parallel, and the first tier that returns results answers the search:

| Tier | Providers | Used when |
|---|---|---|
| 1. Grounded | Google Search through Gemini | A Gemini key or Google Cloud project is set |
| 2. Web | Serper and SearXNG | Tier 1 is not configured or found nothing |
| 3. Scholarly | arXiv and Crossref | No web provider found anything |
| 4. Last resort | Wikipedia | Only with `RESEARCH_ALLOW_WIKIPEDIA_FALLBACK=true`, or when every web provider is excluded |

Within a tier, results are de-duplicated by URL and ranked by the provider's
weight (Google 1.4, Serper 1.2, SearXNG 1.1, arXiv 0.9, Crossref 0.8, Wikipedia
0.6), plus how many query words they contain, plus a small bonus for PDFs.

A provider that fails or times out is skipped, and the search moves on. When no
web provider could answer at all, the researcher is told the search was
unavailable rather than handed an empty list it might read as "nothing exists".

---

## Providers

| Provider | Setup | Notes |
|---|---|---|
| **Google grounded search** | `GEMINI_API_KEY` (or `GOOGLE_GENAI_API_KEY`), or `GOOGLE_CLOUD_PROJECT` with Application Default Credentials | The best results. `GEMINI_GROUNDING_API_KEY` and `GEMINI_GROUNDING_MODEL` (default `gemini-2.5-flash`) override the key and model; `GOOGLE_CLOUD_LOCATION` defaults to `global`. |
| **Serper** | `SERPER_API_KEY` from [serper.dev](https://serper.dev) | Google results through a paid API. |
| **SearXNG** | `SEARXNG_INSTANCE_URL` (default `http://localhost:8080`) | Self-hosted metasearch with no API keys. If you haven't set the URL and nothing is running there, it is skipped quietly. |
| **arXiv, Crossref** | None | Free public APIs for papers and DOIs. |
| **Wikipedia** | `RESEARCH_ALLOW_WIKIPEDIA_FALLBACK=true` | Off unless you turn it on (see above). |

To run SearXNG locally, with its JSON output turned on:

```bash
docker run -d -p 8080:8080 -e SEARXNG_SETTINGS_SEARCH_FORMATS="json" searxng/searxng
```

---

## Settings

```bash title=".env"
GEMINI_API_KEY=AIza...                     # Google grounded search
SERPER_API_KEY=...                         # optional
SEARXNG_INSTANCE_URL=http://searxng:8080   # optional

RESEARCH_SEARCH_TIMEOUT_SECONDS=15         # per provider
RESEARCH_GROUNDED_TIMEOUT_SECONDS=45       # Google grounding
RESEARCH_PDF_TIMEOUT_SECONDS=90
RESEARCH_PDF_MAX_RETRIES=3
RESEARCH_USER_AGENT="Acme Research research@acme.example"   # required by registers such as SEC EDGAR
```

Every setting is in [Configuration](../reference/configuration.md).

---

## Skipping providers per call

When you call search yourself, skip providers that don't fit the task. A
skipped provider makes no network call:

```python
from jarviscore.search import InternetSearch

async with InternetSearch() as search:
    results = await search.search(
        "latest SEC filings for AAPL",
        max_results=10,
        exclude_providers={"arxiv", "crossref", "wikipedia"},
    )
```

Provider names: `google_grounded`, `serper`, `searxng`, `arxiv`, `crossref`,
`wikipedia`.

---

## Reading pages

The researcher reads the pages it finds over plain HTTP, PDFs included. A page
that needs JavaScript is opened in a headless browser when the browser extra is
installed (`pip install "jarviscore-framework[browser]"`), or in your own
browser with `BROWSER_CONTROL_URL`. For pages that have to be used rather than
read, see [Browser Automation](browser-automation.md).

A page that fails to load carries the HTTP `status_code`; one the site refuses
with 401 or 403 is marked `access: protected`. The agent decides what to do
next; the runtime does not retry on its behalf.

---

## Which providers to use

| You want | Use |
|---|---|
| To get started | `GEMINI_API_KEY` alone |
| Google results without Gemini grounding | `SERPER_API_KEY`, and exclude `google_grounded` |
| No third-party search API | Self-hosted SearXNG, and exclude `google_grounded` and `serper` |
| Academic sources | arXiv and Crossref answer when the web finds nothing. To search them directly, exclude the web providers |
| News and markets | Google grounding and Serper, excluding the scholarly providers |
