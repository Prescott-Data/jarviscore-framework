"""Agents' web traffic leaves through the developer's own proxy."""

import asyncio
import base64
from types import SimpleNamespace

import pytest

from jarviscore.core.egress import Egress, configured_egress
from jarviscore.kernel.state import KernelState


def test_only_http_proxies_with_host_and_port_are_accepted():
    with pytest.raises(ValueError, match="socks5://"):
        Egress("socks5://user:secret@gw.example:1080")
    with pytest.raises(ValueError, match="host and port"):
        Egress("http://gw.example")


def test_errors_never_carry_the_provider_password():
    with pytest.raises(ValueError) as caught:
        Egress("ftp://user:hunter2@gw.example:21")
    assert "hunter2" not in str(caught.value)
    assert "hunter2" not in Egress("http://user:hunter2@gw.example:7000").redacted()


def test_playwright_receives_server_and_credentials_separately():
    egress = Egress("http://us%40er:p%3Ass@gw.example:7000", bypass="searxng,.internal")
    assert egress.playwright() == {
        "server": "http://gw.example:7000",
        "username": "us@er",
        "password": "p:ss",
        "bypass": "searxng,.internal",
    }


def test_a_sticky_session_keeps_one_exit_per_key():
    egress = Egress("http://user-session-{session}:pw@gw.example:7000")
    ada = egress.playwright("tenant-ada")["username"]
    assert ada == egress.playwright("tenant-ada")["username"]
    assert ada != egress.playwright("tenant-bo")["username"]
    assert "{session}" not in ada and len(ada) == len("user-session-") + 16
    # Without a key each use is its own session rather than a literal placeholder.
    assert "{session}" not in egress.http_proxy("https://example.com")


def test_loopback_and_bypassed_hosts_go_direct():
    egress = Egress("http://gw.example:7000", bypass="searxng, *.corp.example, .internal")
    assert egress.http_proxy("https://shop.example/basket") == "http://gw.example:7000"
    for direct in (
        "http://localhost:8082/search",
        "http://127.0.0.1:8082/",
        "http://[::1]:8080/",
        "http://searxng:8080/search",
        "https://wiki.corp.example/page",
        "http://api.internal/x",
        "http://internal/x",
    ):
        assert egress.http_proxy(direct) is None, direct


def test_mesh_config_overrides_the_environment():
    assert configured_egress({"egress_proxy_url": ""}) is None
    egress = configured_egress({"egress_proxy_url": "http://gw.example:7000", "egress_proxy_bypass": "searxng"})
    assert egress == Egress("http://gw.example:7000", bypass="searxng")


# ── The browser subagent launches through the proxy ─────────────────────────


class _Recorder:
    def __init__(self):
        self.calls = []

    async def start(self):
        return self

    async def stop(self):
        pass

    @property
    def chromium(self):
        return self

    async def launch(self, **kwargs):
        self.calls.append(("launch", kwargs))
        return self

    async def launch_persistent_context(self, user_data_dir, **kwargs):
        self.calls.append(("launch_persistent_context", kwargs))
        return self

    async def connect_over_cdp(self, url, **kwargs):
        self.calls.append(("connect_over_cdp", kwargs))
        return SimpleNamespace(contexts=[self])

    async def new_context(self, **kwargs):
        self.calls.append(("new_context", kwargs))
        return self

    pages = ()

    async def new_page(self):
        return SimpleNamespace(url="about:blank", is_closed=lambda: False)

    async def new_cdp_session(self, page):
        return self

    async def send(self, method, params=None):
        self.calls.append((method, params or {}))
        return {"product": "HeadlessChrome/153.0.7390.54"} if method == "Browser.getVersion" else {}

    async def detach(self):
        pass

    def on(self, event, handler):
        pass


@pytest.fixture
def recorder(monkeypatch):
    from jarviscore.kernel.defaults import browser as browser_module

    rec = _Recorder()
    monkeypatch.setattr(browser_module, "PLAYWRIGHT_AVAILABLE", True)
    monkeypatch.setattr(browser_module, "async_playwright", lambda: rec, raising=False)
    return rec


def _opened(agent, context):
    asyncio.run(agent._pre_run_hook(KernelState(context=context)))


def test_a_fresh_browser_launches_through_the_workflows_sticky_exit(recorder):
    from jarviscore.kernel.defaults.browser import BrowserSubAgent

    egress = Egress("http://user-session-{session}:pw@gw.example:7000")
    agent = BrowserSubAgent("b", None, egress=egress, locale="en-GB", timezone="Europe/London")
    _opened(agent, {"workflow_id": "wf-1"})

    launch = dict(recorder.calls)["launch"]
    assert launch["proxy"] == egress.playwright("wf-1")
    assert dict(recorder.calls)["new_context"]["locale"] == "en-GB"
    assert dict(recorder.calls)["new_context"]["timezone_id"] == "Europe/London"


def test_a_tenant_profile_keeps_its_exit_across_runs(recorder, tmp_path):
    from jarviscore.kernel.defaults.browser import BrowserSubAgent

    egress = Egress("http://user-session-{session}:pw@gw.example:7000")
    agent = BrowserSubAgent("b", None, profile_root=str(tmp_path), scope_field="owner", egress=egress)
    _opened(agent, {"owner": "ada", "workflow_id": "wf-1"})
    first = dict(recorder.calls)["launch_persistent_context"]["proxy"]
    asyncio.run(agent._post_run_hook())
    recorder.calls.clear()
    _opened(agent, {"owner": "ada", "workflow_id": "wf-2"})
    assert dict(recorder.calls)["launch_persistent_context"]["proxy"] == first


def test_an_attached_browser_keeps_its_own_network(recorder):
    from jarviscore.kernel.defaults.browser import BrowserSubAgent

    agent = BrowserSubAgent("b", None, control_url="http://127.0.0.1:9222", egress=Egress("http://gw.example:7000"))
    _opened(agent, {"workflow_id": "wf-1"})
    assert next(name for name, _ in recorder.calls) == "connect_over_cdp"
    assert not any("proxy" in kwargs for _, kwargs in recorder.calls)


def test_the_researchers_page_reads_and_browser_share_one_exit(monkeypatch):
    from jarviscore.config import settings
    from jarviscore.kernel.defaults import researcher as researcher_module

    monkeypatch.setattr(settings, "egress_proxy_url", "http://user-session-{session}:pw@gw.example:7000")
    monkeypatch.delenv("BROWSER_CONTROL_URL", raising=False)
    monkeypatch.delenv("BROWSER_SERVICE_URL", raising=False)
    if not researcher_module._HAS_BROWSER:
        pytest.skip("browser extra not installed")
    agent = researcher_module.ResearcherSubAgent(agent_id="r", llm_client=None)

    page_proxy = agent.internet_search._page_proxy("https://shop.example/")
    browser_user = agent._browser_config.proxy["username"]
    assert browser_user in page_proxy
    other = researcher_module.ResearcherSubAgent(agent_id="r2", llm_client=None)
    assert other._browser_config.proxy["username"] != browser_user


# ── End to end through a real local proxy ───────────────────────────────────


class _Proxy:
    """A forward HTTP proxy that serves every absolute-URI request itself."""

    def __init__(self):
        self.requests = []

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()

    async def _serve(self, reader, writer):
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1").split("\r\n")
        headers = {k.lower(): v.strip() for k, _, v in (line.partition(":") for line in head[1:] if line)}
        self.requests.append((head[0], headers))
        if "proxy-authorization" not in headers:
            writer.write(
                b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                b"Proxy-Authenticate: Basic realm=\"egress\"\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
        else:
            body = b"<html><head><title>Through the proxy</title></head><body><p>Served by the egress proxy.</p></body></html>"
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
            )
        await writer.drain()
        writer.close()

    def credentials(self):
        return [
            base64.b64decode(h["proxy-authorization"].split()[1]).decode()
            for _, h in self.requests if "proxy-authorization" in h
        ]


def test_the_researcher_reads_pages_through_the_proxy():
    from jarviscore.search.internet_search import InternetSearch

    async def scenario():
        async with _Proxy() as proxy:
            egress = Egress(f"http://user-session-{{session}}:pw@127.0.0.1:{proxy.port}")
            search = InternetSearch(egress=egress)
            try:
                page = await search.extract_content("http://shop.example/basket")
            finally:
                await search.close()
            return page, proxy

    page, proxy = asyncio.run(scenario())
    assert page["title"] == "Through the proxy" and "Served by the egress proxy" in page["content"]
    assert proxy.requests[0][0] == "GET http://shop.example/basket HTTP/1.1"
    user = proxy.credentials()[0]
    assert user.startswith("user-session-") and user.endswith(":pw") and "{session}" not in user


def _chromium_installed():
    import os

    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Error:
        return False


@pytest.mark.skipif(not _chromium_installed(), reason="Playwright Chromium not installed")
def test_the_browser_agent_browses_through_the_proxy_as_the_configured_region():
    from jarviscore.kernel.defaults.browser import BrowserSubAgent

    async def scenario():
        async with _Proxy() as proxy:
            egress = Egress(f"http://user-session-{{session}}:pw@127.0.0.1:{proxy.port}")
            agent = BrowserSubAgent("b", None, egress=egress, locale="en-GB", timezone="Europe/London")
            await agent._pre_run_hook(KernelState(context={"workflow_id": "wf-1"}))
            try:
                result = await agent._tool_navigate("http://shop.example/basket", wait_for="load")
                zone = await agent._page.evaluate("Intl.DateTimeFormat().resolvedOptions().timeZone")
            finally:
                await agent._post_run_hook()
            return result, zone, proxy, egress

    result, zone, proxy, egress = asyncio.run(scenario())
    assert result["title"] == "Through the proxy"
    assert zone == "Europe/London"
    served = [h for line, h in proxy.requests if line == "GET http://shop.example/basket HTTP/1.1"]
    assert served and all(h["accept-language"].startswith("en-GB") for h in served)
    assert all("HeadlessChrome" not in h["user-agent"] for h in served)
    expected = egress.playwright("wf-1")
    assert f"{expected['username']}:{expected['password']}" in proxy.credentials()
