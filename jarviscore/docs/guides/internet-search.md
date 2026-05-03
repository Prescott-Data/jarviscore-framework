---
icon: material/earth
---

# Internet Search

JarvisCore includes a built-in `InternetSearch` module used primarily by `ResearcherSubAgent`. It runs multiple search providers in parallel, deduplicates and ranks results by relevance and source trust, then returns a unified result list your agents can reason over.

No configuration is required to get started — if you have `GEMINI_API_KEY` set, search is active immediately.

---

## How it works

When an agent triggers a search, the module fans out to all configured providers simultaneously, collects results, deduplicates by URL, and ranks them by a weighted trust score. All providers have circuit breakers — a failing provider is automatically bypassed after 8 consecutive failures and retried after 5 minutes.

```
Agent → InternetSearch.search(query)
           ├── Google Grounded Search  (score weight: 1.4)
           ├── Serper                  (score weight: 1.2)
           ├── SearXNG                 (score weight: 1.1)
           ├── arXiv                   (score weight: 0.9)  ← academic papers
           ├── Crossref                (score weight: 0.8)  ← academic papers
           └── Wikipedia               (score weight: 0.6)
                    ↓
           Deduplicate by URL
           Rank by (source weight + query-term overlap + pdf bonus)
                    ↓
           Return top N results
```

---

## Providers

### Google Grounded Search <span class="jc-badge jc-badge-primary">Primary</span>

Uses the Gemini API with Google Search grounding enabled. The model queries Google Search in real time and returns structured web results alongside a synthesised summary grounded in those sources.

**Required:** one of the following —

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Standard Gemini API key (starts with `AIza`). Uses the `v1alpha` endpoint. |
| `GOOGLE_CLOUD_PROJECT` + ADC | Vertex AI path. Uses `v1` endpoint via Application Default Credentials. |

**Optional:**

| Variable | Default | Description |
|---|---|---|
| `GEMINI_GROUNDING_API_KEY` | falls back to `GEMINI_API_KEY` | Override the key used specifically for grounded search |
| `GEMINI_GROUNDING_MODEL` | `gemini-2.5-flash` | Which Gemini model to use for grounded search |
| `GOOGLE_CLOUD_LOCATION` | `global` | GCP location for Vertex AI path |

> [!NOTE]
> Google Grounded Search is the highest-quality provider. If you have `GEMINI_API_KEY` set (which is already required for agents to function), this provider is active with zero additional setup.

---

### Serper <span class="jc-badge jc-badge-optional">Optional</span>

Serper calls the Google Search API via [serper.dev](https://serper.dev). It adds a second independent Google Search signal and is useful when you want results without burning Gemini API quota on grounding.

| Variable | Default | Description |
|---|---|---|
| `SERPER_API_KEY` | — | API key from [serper.dev](https://serper.dev). Provider is skipped if unset. |

Serper results score slightly lower than Google Grounded Search in the ranking (1.2 vs 1.4) because they don't carry grounding metadata or synthesised summaries.

---

### SearXNG <span class="jc-badge jc-badge-optional">Optional</span> <span class="jc-badge jc-badge-free">Self-hosted</span>

SearXNG is a self-hosted, privacy-respecting metasearch engine that aggregates results from Google, Bing, and dozens of other engines — without API keys. It is always attempted unless you point `SEARXNG_INSTANCE_URL` at a non-responsive host, in which case the circuit breaker takes it offline.

| Variable | Default | Description |
|---|---|---|
| `SEARXNG_INSTANCE_URL` | `http://localhost:8080` | URL of your SearXNG instance |

**Running SearXNG locally:**

```bash
docker run -d \
  -p 8080:8080 \
  -e SEARXNG_SETTINGS_SEARCH_FORMATS="json" \
  searxng/searxng
```

> [!IMPORTANT]
> SearXNG's JSON format must be enabled. Add `- json` under `search.formats` in `settings.yml`, or pass the env var shown above.

If SearXNG is not running, the connection fails silently and the circuit breaker skips it — no error reaches your agent.

---

### arXiv & Crossref <span class="jc-badge jc-badge-free">No config needed</span>

Both are always active. They use free public APIs with no authentication.

- **arXiv** — searches academic preprints via `export.arxiv.org`. Best for research-heavy queries.
- **Crossref** — searches published academic papers via `api.crossref.org`. Returns DOI links.

These providers score lower by default (0.9 and 0.8) because they are domain-specific. Use `exclude_providers` to skip them for non-academic tasks.

---

### Wikipedia <span class="jc-badge jc-badge-free">No config needed</span>

Always active. Uses the Wikipedia search API. Scores lowest (0.6) — useful as a broad fallback but not a primary signal for real-time queries.

---

## Configuration summary

```bash
# .env — minimum for search to work (also needed for agents)
GEMINI_API_KEY=AIza...

# Optional: add Serper for dual Google-source coverage
SERPER_API_KEY=your-serper-key

# Optional: self-hosted SearXNG
SEARXNG_INSTANCE_URL=http://your-searxng-host:8080

# Optional: override the Gemini model used for grounding
GEMINI_GROUNDING_MODEL=gemini-2.5-flash

# Optional: tune PDF extraction behaviour
RESEARCH_PDF_TIMEOUT_SECONDS=90
RESEARCH_PDF_MAX_RETRIES=3
```

---

## Excluding providers at call time

If your agent's task doesn't benefit from certain sources, exclude them per-call:

```python
results = await search.search(
    query="latest SEC filings for AAPL",
    max_results=10,
    exclude_providers={"arxiv", "crossref", "wikipedia"},  # skip academic sources
)
```

This prevents wasted network calls — the provider is skipped entirely, not just filtered from results.

---

## Browser escalation (SPAs and paywalled content)

When HTTP extraction returns empty content — common for single-page applications and some paywalled sites — the module can escalate to a headless browser. This is an opt-in extra:

```bash
pip install "jarviscore[browser]"
```

| Variable | Default | Description |
|---|---|---|
| `BROWSER_HEADLESS` | `true` | Run browser in headless mode |
| `BROWSER_CONTROL_URL` | — | CDP endpoint for remote browser (e.g. Browserless, Playwright server) |

---

## Resilience: circuit breakers

Every provider has an independent circuit breaker:

| Parameter | Default |
|---|---|
| Failure threshold | 8 consecutive failures |
| Recovery timeout | 300 seconds (5 minutes) |

Once a provider's breaker opens, it is skipped entirely until the recovery window passes. Healthy providers continue operating normally. You'll see circuit breaker state changes in agent logs at `WARNING` level.

---

## Which providers should I enable?

| Scenario | Recommendation |
|---|---|
| **Getting started** | Just `GEMINI_API_KEY` — Google Grounded Search alone is sufficient |
| **High-volume research agents** | Add `SERPER_API_KEY` to reduce Gemini quota usage |
| **Privacy-sensitive deployments** | Add self-hosted SearXNG, exclude `google_grounded` and `serper` |
| **Academic / scientific research** | Keep arXiv and Crossref enabled (they are by default) |
| **Real-time financial / news** | Google Grounded Search + Serper; exclude arxiv, crossref, wikipedia |
