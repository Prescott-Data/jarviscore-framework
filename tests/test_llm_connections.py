"""Provider connections outlive the call that opened them.

Each promotion and vLLM completion opened a new aiohttp session, so every call
paid a TCP + TLS handshake (0.6-0.7 s measured to the promotion endpoint). The
Azure and Claude SDK pools closed idle connections after 5 s,
shorter than the tool work between agent turns, so most calls after the first
paid about a second to reconnect. The first call of every agent paid it too.

These tests hold the fixes: one session per client per event loop, a
configurable keep-alive on every SDK pool, a warm-up that can never fail a
start, and a ``close()`` that releases it all (the method the Profile
docstring already told developers to call).
"""

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

import jarviscore.execution.llm as llm_module
from jarviscore.execution.llm import LLMProvider, UnifiedLLMClient
from jarviscore.promo.client import PromoLLMClient


class _Response:
    status = 200
    headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async def text(self):
        return "{}"

    async def read(self):
        return b""


class _Session:
    created = []

    def __init__(self, *, timeout=None, connector=None):
        self.timeout = timeout
        self.connector = connector
        self.closed = False
        self.requests = []
        _Session.created.append(self)

    def post(self, url, **kwargs):
        self.requests.append(("POST", url))
        return _Response()

    def head(self, url, **kwargs):
        self.requests.append(("HEAD", url))
        return _Response()

    async def close(self):
        self.closed = True


@pytest.fixture
def sessions(monkeypatch):
    _Session.created = []
    monkeypatch.setattr(llm_module.aiohttp, "ClientSession", _Session)
    monkeypatch.setattr("jarviscore.promo.client.aiohttp.ClientSession", _Session)
    return _Session.created


def _vllm_client(**config):
    llm = UnifiedLLMClient.__new__(UnifiedLLMClient)
    llm.config = {"llm_max_retries_429": 0, "llm_model": "local", **config}
    llm._semaphore = None
    llm.provider_order = [LLMProvider.VLLM]
    llm.vllm_endpoint = "http://vllm.invalid"
    return llm


class TestVllmKeepsItsConnection:
    async def test_calls_on_one_loop_share_one_session(self, sessions):
        llm = _vllm_client(llm_keepalive_seconds=42.0)
        await llm.generate("one")
        await llm.generate("two")
        assert len(sessions) == 1
        assert len(sessions[0].requests) == 2
        assert sessions[0].connector._keepalive_timeout == 42.0

    async def test_a_closed_session_is_replaced(self, sessions):
        llm = _vllm_client()
        await llm.generate("one")
        await sessions[0].close()
        await llm.generate("two")
        assert len(sessions) == 2

    async def test_close_releases_the_session(self, sessions):
        llm = _vllm_client()
        await llm.generate("one")
        await llm.close()
        assert sessions[0].closed

    def test_each_event_loop_gets_its_own_session(self, sessions):
        llm = _vllm_client()
        asyncio.run(llm.generate("one"))
        asyncio.run(llm.generate("two"))
        assert len(sessions) == 2


class TestPromoKeepsItsConnection:
    async def test_calls_share_one_session(self, sessions, tmp_path):
        client = PromoLLMClient(token="jc_trial_x", artifact_dir=str(tmp_path), keepalive_seconds=33.0)
        await client._send({"call_id": "a"}, "a")
        await client._send({"call_id": "b"}, "b")
        assert len(sessions) == 1
        assert [method for method, _ in sessions[0].requests] == ["POST", "POST"]
        assert sessions[0].connector._keepalive_timeout == 33.0
        assert sessions[0].timeout.total == client.timeout

    async def test_warming_touches_only_the_host_root(self, sessions, tmp_path):
        client = PromoLLMClient(token="jc_trial_x", artifact_dir=str(tmp_path))
        await client.warm()
        method, url = sessions[0].requests[0]
        assert method == "HEAD"
        assert url == "https://jarviscore-promo.developers.prescottdata.io/"

    async def test_close_releases_the_session(self, sessions, tmp_path):
        client = PromoLLMClient(token="jc_trial_x", artifact_dir=str(tmp_path))
        await client._send({"call_id": "a"}, "a")
        await client.close()
        assert sessions[0].closed
        await client.close()


class TestSdkPoolsKeepIdleConnections:
    def test_azure_and_claude_pools_use_the_configured_keepalive(self, monkeypatch):
        captured = {}

        def recording(name, original):
            def build(*args, **kwargs):
                captured[name] = kwargs.get("limits")
                return original(*args, **kwargs)
            return build

        monkeypatch.setattr(
            llm_module, "DefaultAsyncHttpxClient",
            recording("azure", llm_module._sdk("DefaultAsyncHttpxClient")),
        )
        monkeypatch.setattr(
            llm_module, "AnthropicHttpxClient",
            recording("claude", llm_module._sdk("AnthropicHttpxClient")),
        )
        llm = UnifiedLLMClient({
            "promo_token": None,
            "azure_api_key": "k", "azure_endpoint": "https://example.openai.azure.com",
            "claude_api_key": "k",
            "gemini_api_key": None, "vertex_ai_enabled": False,
            "llm_endpoint": None, "vllm_endpoint": None,
            "llm_keepalive_seconds": 77.0,
        })
        assert llm.azure_client is not None and llm.claude_client is not None
        for name in ("azure", "claude"):
            limits = captured[name]
            assert isinstance(limits, httpx.Limits)
            assert limits.keepalive_expiry == 77.0
            assert limits.max_connections == 1000
            assert limits.max_keepalive_connections == 100

    def test_the_default_keepalive_outlasts_a_turn(self):
        from jarviscore.config.settings import Settings

        assert Settings.model_fields["llm_keepalive_seconds"].default == 120.0
        assert Settings.model_fields["llm_prewarm"].default is True


class TestWarmingNeverFailsAStart:
    def _azure_client(self, **config):
        llm = UnifiedLLMClient.__new__(UnifiedLLMClient)
        llm.config = {"llm_connect_timeout": 1.0, **config}
        llm.provider_order = [LLMProvider.AZURE]
        llm.azure_client = MagicMock(base_url=httpx.URL("https://example.openai.azure.com/openai/"))
        llm._azure_http = MagicMock()
        return llm

    async def test_warming_opens_the_azure_host_root(self):
        llm = self._azure_client()
        seen = []

        async def head(url):
            seen.append(url)

        llm._azure_http.head = head
        llm.start_warming()
        await llm._warm_task
        assert seen == ["https://example.openai.azure.com/"]

    async def test_a_failed_warm_up_is_swallowed(self):
        llm = self._azure_client()

        async def head(url):
            raise httpx.ConnectError("offline")

        llm._azure_http.head = head
        llm.start_warming()
        await llm._warm_task

    async def test_warming_can_be_turned_off(self):
        llm = self._azure_client(llm_prewarm=False)
        llm.start_warming()
        assert getattr(llm, "_warm_task", None) is None

    def test_warming_outside_a_loop_does_nothing(self):
        llm = self._azure_client()
        llm.start_warming()
        assert getattr(llm, "_warm_task", None) is None

    async def test_close_cancels_a_pending_warm_up(self):
        llm = self._azure_client()
        llm.azure_client.close = MagicMock(side_effect=lambda: asyncio.sleep(0))

        async def head(url):
            await asyncio.sleep(30)

        llm._azure_http.head = head
        llm.start_warming()
        await asyncio.sleep(0)
        await llm.close()
        # Nothing of a closed client is left pending, on any supported Python.
        assert llm._warm_task.done()
        llm.azure_client.close.assert_called_once()
