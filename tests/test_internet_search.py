import pytest

from jarviscore.search.internet_search import InternetSearch


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


def test_page_text_keeps_the_words_a_reader_sees():
    from bs4 import BeautifulSoup

    # The FTC early-termination notice: label and value are sibling blocks.
    html = (
        "<main><h1>20251399: Salesforce, Inc.; Informatica Inc.</h1>"
        '<div class="field"><div class="field__label">Granting Status</div>'
        '<div class="field__items"><div class="field__item">Granted</div></div></div>'
        '<div class="field"><div class="field__label">Acquiring Party</div>'
        '<div class="field__item">Salesforce, Inc.</div></div>'
        "<p>The <b>HSR</b> waiting period was <em>terminated</em> early. Hello <b>world</b>!</p>"
        "<table><tr><td><span>Date</span><div>August 26, 2025</div></td></tr></table>"
        "</main>"
    )

    text = InternetSearch._html_to_markdown(BeautifulSoup(html, "html.parser"))

    assert "Granting Status Granted" in text
    assert "Acquiring Party Salesforce, Inc." in text
    assert "The HSR waiting period was terminated early. Hello world!" in text
    assert "| Date August 26, 2025 |" in text
    assert "StatusGranted" not in text
