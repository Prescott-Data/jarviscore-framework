import pytest

from jarviscore.search.internet_search import (
    InternetSearch,
    SearchProviderError,
    SearchUnavailable,
)


@pytest.mark.asyncio
async def test_search_stops_before_wikipedia_when_searxng_returns_results(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GROUNDING_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)

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

    async def wikipedia(query, max_results=10):
        calls.append("wikipedia")
        return [{
            "title": "Should not be called",
            "snippet": "",
            "url": "https://wikipedia.org",
            "source": "wikipedia",
        }]

    search.initialize = noop_initialize
    search._search_searxng = searxng
    search._search_wikipedia = wikipedia

    results = await search.search("prescott data")

    assert [result["source"] for result in results] == ["searxng"]
    assert calls == ["searxng"]


@pytest.mark.asyncio
async def test_search_does_not_use_wikipedia_when_searxng_available_but_empty(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GROUNDING_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_ALLOW_WIKIPEDIA_FALLBACK", raising=False)

    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def empty(provider):
        async def run(query, max_results=10):
            calls.append(provider)
            return []
        return run

    async def wikipedia(query, max_results=10):
        calls.append("wikipedia")
        return [{
            "title": "Fallback",
            "snippet": "Last resort result",
            "url": "https://wikipedia.org/wiki/Fallback",
            "source": "wikipedia",
        }]

    search.initialize = noop_initialize
    search._search_searxng = await empty("searxng")
    search._search_arxiv = await empty("arxiv")
    search._search_crossref = await empty("crossref")
    search._search_wikipedia = wikipedia

    results = await search.search("obscure query")

    assert results == []
    assert calls == ["searxng", "arxiv", "crossref"]


@pytest.mark.asyncio
async def test_search_uses_wikipedia_when_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GROUNDING_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("RESEARCH_ALLOW_WIKIPEDIA_FALLBACK", "true")

    search = InternetSearch()
    calls = []

    async def noop_initialize():
        return None

    async def empty(provider):
        async def run(query, max_results=10):
            calls.append(provider)
            return []
        return run

    async def wikipedia(query, max_results=10):
        calls.append("wikipedia")
        return [{
            "title": "Fallback",
            "snippet": "Last resort result",
            "url": "https://wikipedia.org/wiki/Fallback",
            "source": "wikipedia",
        }]

    search.initialize = noop_initialize
    search._search_searxng = await empty("searxng")
    search._search_arxiv = await empty("arxiv")
    search._search_crossref = await empty("crossref")
    search._search_wikipedia = wikipedia

    results = await search.search("obscure query")

    assert results[0]["source"] == "wikipedia"
    assert calls == ["searxng", "arxiv", "crossref", "wikipedia"]


def _web_only_search(monkeypatch):
    for key in (
        "GEMINI_API_KEY", "GEMINI_GROUNDING_API_KEY", "GOOGLE_GENAI_API_KEY",
        "GOOGLE_CLOUD_PROJECT", "SERPER_API_KEY", "RESEARCH_ALLOW_WIKIPEDIA_FALLBACK",
    ):
        monkeypatch.delenv(key, raising=False)
    search = InternetSearch()

    async def noop_initialize():
        return None

    async def no_results(query, max_results=10):
        return []

    search.initialize = noop_initialize
    search._search_arxiv = no_results
    search._search_crossref = no_results
    return search


@pytest.mark.asyncio
async def test_search_answered_returns_a_genuine_empty_result(monkeypatch):
    search = _web_only_search(monkeypatch)

    async def answered_empty(query, max_results=10):
        return []

    search._search_searxng = answered_empty

    assert await search.search_answered("no such firm") == []


@pytest.mark.asyncio
async def test_search_answered_raises_when_no_web_provider_answered(monkeypatch):
    search = _web_only_search(monkeypatch)

    async def blocked(query, max_results=10):
        raise SearchProviderError("searxng engines did not answer: [['google', 'CAPTCHA']]")

    search._search_searxng = blocked

    with pytest.raises(SearchUnavailable) as error:
        await search.search_answered("any firm")
    assert "CAPTCHA" in str(error.value)
    assert await search.search("any firm") == []


@pytest.mark.asyncio
async def test_searxng_reports_engines_that_refused_instead_of_an_empty_answer(monkeypatch):
    search = _web_only_search(monkeypatch)

    class Response:
        status = 200

        async def json(self):
            return {"results": [], "unresponsive_engines": [["google", "CAPTCHA"]]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    search.session = Session()

    with pytest.raises(SearchProviderError, match="CAPTCHA"):
        await search._search_searxng("any firm")
