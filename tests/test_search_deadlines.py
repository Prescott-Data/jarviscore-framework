"""Offline deadline contracts for both public search implementations (#147)."""

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.search import InternetSearch as ExecutionSearch
from jarviscore.search.internet_search import InternetSearch


@pytest.fixture(params=[InternetSearch, ExecutionSearch])
def search_class(request, monkeypatch):
    for key in (
        "GOOGLE_CLOUD_PROJECT", "GEMINI_API_KEY", "GEMINI_GROUNDING_API_KEY",
        "GOOGLE_GENAI_API_KEY", "SERPER_API_KEY", "RESEARCH_SEARCH_TIMEOUT_SECONDS",
        "RESEARCH_GROUNDED_TIMEOUT_SECONDS", "RESEARCH_ALLOW_WIKIPEDIA_FALLBACK",
    ):
        monkeypatch.delenv(key, raising=False)
    return request.param


def result(provider):
    return [{"title": "Example", "url": "https://example.org", "source": provider}]


@pytest.mark.parametrize("duration", [6.47, 7.86])
async def test_grounded_duration_is_not_cancelled_at_six_seconds(search_class, monkeypatch, duration):
    search = search_class()
    search.initialize = AsyncMock()
    search._gemini_api_key = "offline-test"
    search._search_google_grounded = AsyncMock(return_value=result("google_grounded"))
    deadlines = []

    async def virtual_wait_for(coro, timeout):
        deadlines.append(timeout)
        if duration > timeout:
            coro.close()
            raise TimeoutError()
        return await coro

    monkeypatch.setattr(asyncio, "wait_for", virtual_wait_for)
    rows = await search.search("example", exclude_providers={
        "searxng", "serper", "wikipedia", "arxiv", "crossref",
    })
    assert rows[0]["source"] == "google_grounded"
    assert deadlines == [45.0]


async def test_deadline_environment_and_constructor_override(search_class, monkeypatch):
    monkeypatch.setenv("RESEARCH_SEARCH_TIMEOUT_SECONDS", "23.5")
    monkeypatch.setenv("RESEARCH_GROUNDED_TIMEOUT_SECONDS", "61")
    search = search_class()
    assert search.search_timeout_seconds == 23.5
    assert search.grounded_timeout_seconds == 61
    search = search_class(search_timeout_seconds=12, grounded_timeout_seconds=32)
    assert search.search_timeout_seconds == 12
    assert search.grounded_timeout_seconds == 32
    monkeypatch.delenv("RESEARCH_SEARCH_TIMEOUT_SECONDS")
    assert search_class().search_timeout_seconds == 15


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "bad"])
@pytest.mark.parametrize("name", ["search_timeout_seconds", "grounded_timeout_seconds"])
def test_invalid_deadlines_fail_at_construction(search_class, name, value):
    with pytest.raises(ValueError, match="positive finite"):
        search_class(**{name: value})


def test_invalid_environment_deadline(search_class, monkeypatch):
    monkeypatch.setenv("RESEARCH_GROUNDED_TIMEOUT_SECONDS", "nan")
    with pytest.raises(ValueError, match="RESEARCH_GROUNDED_TIMEOUT_SECONDS"):
        search_class()


async def test_timeout_cancels_provider_preserves_other_results_and_logs_type(search_class, caplog):
    search = search_class(search_timeout_seconds=0.01, grounded_timeout_seconds=0.01)
    search.initialize = AsyncMock()
    search._gemini_api_key = "offline-test"
    cancelled = asyncio.Event()

    async def blocked(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    search._search_google_grounded = blocked
    search._search_searxng = AsyncMock(return_value=result("searxng"))
    with caplog.at_level(logging.WARNING):
        rows = await search.search("private query", exclude_providers={"wikipedia", "arxiv", "crossref"})
    assert rows[0]["source"] == "searxng"
    assert cancelled.is_set()
    assert "provider=google_grounded" in caplog.text
    assert "TimeoutError" in caplog.text
    assert "0.01" in caplog.text
    assert "private query" not in caplog.text


async def test_exception_type_and_provider_are_logged(search_class, caplog):
    search = search_class()
    search.initialize = AsyncMock()
    search._search_searxng = AsyncMock(side_effect=LookupError())
    with caplog.at_level(logging.WARNING):
        assert await search.search("example", exclude_providers={
            "google_grounded", "wikipedia", "arxiv", "crossref",
        }) == []
    assert "provider=searxng" in caplog.text
    assert "LookupError" in caplog.text


async def test_caller_cancellation_is_not_swallowed(search_class):
    search = search_class()
    search.initialize = AsyncMock()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    search._search_searxng = blocked
    task = asyncio.create_task(search.search("example", exclude_providers={
        "google_grounded", "wikipedia", "arxiv", "crossref",
    }))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()