"""
jarviscore.search — Internet search and content extraction.

Multi-provider parallel search with circuit breaker resilience,
HTML→Markdown extraction, and optional browser escalation for SPAs.

Ported from integration-agent-javiscore's InternetSearch class.

Providers:
    - Google Grounded Search (via Gemini, highest quality)
    - Serper (Google Search API)
    - SearXNG (free, self-hosted metasearch — aggregates Google/Bing)
    - Wikipedia (encyclopedia fallback)
    - arXiv (academic papers)
    - Crossref (scholarly DOIs)

Usage:
    from jarviscore.search import InternetSearch

    async with InternetSearch() as search:
        results = await search.search("Stripe API authentication")
        content = await search.extract_content("https://docs.stripe.com/api")

Install:
    pip install jarviscore-framework          # search uses core deps (aiohttp)
    pip install jarviscore-framework[browser]  # + browser escalation for SPAs
"""

from .internet_search import InternetSearch, CircuitBreaker

__all__ = ["InternetSearch", "CircuitBreaker"]
