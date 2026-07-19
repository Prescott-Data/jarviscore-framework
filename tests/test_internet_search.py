import pytest
import asyncio

from jarviscore.search.internet_search import InternetSearch


@pytest.mark.asyncio
async def test_general_query_uses_searxng_when_grounded_unavailable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GROUNDING_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def searxng(query, max_results=10):
        calls.append("searxng")
        return [{
            "title": "Prescott Data",
            "snippet": "Enterprise AI rails",
            "url": "https://prescottdata.io",
            "source": "searxng",
        }]

    search.initialize = noop_initialize
    search._search_searxng = searxng

    results = await search.search("prescott data")

    assert [result["source"] for result in results] == ["searxng"]
    assert calls == ["searxng"]


@pytest.mark.asyncio
async def test_general_query_tries_grounded_then_searxng(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def grounded(query, max_results=10):
        calls.append("google_grounded")
        return []

    async def searxng(query, max_results=10):
        calls.append("searxng")
        return [{
            "title": "Fallback",
            "snippet": "From SearXNG",
            "url": "https://example.com",
            "source": "searxng",
        }]

    search.initialize = noop_initialize
    search._search_google_grounded = grounded
    search._search_searxng = searxng

    results = await search.search("market news")

    assert results[0]["source"] == "searxng"
    assert calls == ["google_grounded", "searxng"]


@pytest.mark.asyncio
async def test_general_query_returns_empty_when_all_providers_empty(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def empty(provider):
        async def run(query, max_results=10):
            calls.append(provider)
            return []
        return run

    search.initialize = noop_initialize
    search._search_searxng = await empty("searxng")

    results = await search.search("obscure query")

    assert results == []
    assert calls == ["searxng"]


@pytest.mark.asyncio
async def test_general_query_prefers_serper_before_searxng(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "fake-serper-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def serper(query, max_results=10):
        calls.append("serper")
        return [{"title": "Serper", "snippet": "hit", "url": "https://example.com", "source": "serper"}]

    async def searxng(query, max_results=10):
        calls.append("searxng")
        return []

    search.initialize = noop_initialize
    search._search_serper = serper
    search._search_searxng = searxng

    results = await search.search("enterprise aml")

    assert results[0]["source"] == "serper"
    assert calls == ["serper"]


@pytest.mark.asyncio
async def test_searxng_semaphore_limits_parallel_inner_calls(monkeypatch):
    monkeypatch.setenv("SEARXNG_MAX_CONCURRENT", "2")
    from jarviscore.search.internet_search import reset_searxng_semaphore_for_tests

    reset_searxng_semaphore_for_tests()
    search = InternetSearch()
    in_flight = 0
    peak = 0

    async def noop_initialize():
        return None

    async def inner(query, max_results=10):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return [{"title": query, "snippet": "", "url": "https://example.com", "source": "searxng"}]

    search.initialize = noop_initialize
    search._search_searxng_inner = inner

    await asyncio.gather(*[search._search_searxng(f"q{i}") for i in range(6)])

    assert peak <= 2


@pytest.mark.asyncio
async def test_academic_query_uses_arxiv_then_crossref(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def arxiv(query, max_results=10):
        calls.append("arxiv")
        return []

    async def crossref(query, max_results=10):
        calls.append("crossref")
        return [{
            "title": "A Research Paper",
            "snippet": "Abstract",
            "url": "https://doi.org/10.1234/example",
            "source": "crossref",
        }]

    search.initialize = noop_initialize
    search._search_arxiv = arxiv
    search._search_crossref = crossref

    results = await search.search("transformer architecture arxiv paper")

    assert results[0]["source"] == "crossref"
    assert calls == ["arxiv", "crossref"]


@pytest.mark.asyncio
async def test_academic_query_stops_at_arxiv_when_results_found(monkeypatch):
    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def arxiv(query, max_results=10):
        calls.append("arxiv")
        return [{
            "title": "Preprint",
            "snippet": "We propose...",
            "url": "https://arxiv.org/abs/1234",
            "source": "arxiv",
        }]

    async def crossref(query, max_results=10):
        calls.append("crossref")
        return []

    search.initialize = noop_initialize
    search._search_arxiv = arxiv
    search._search_crossref = crossref

    results = await search.search("peer review journal paper")

    assert results[0]["source"] == "arxiv"
    assert calls == ["arxiv"]
