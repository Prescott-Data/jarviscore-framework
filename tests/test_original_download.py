"""Original bytes cross Nexus; credentials and redirect capabilities never do."""
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from jarviscore import OnBehalfOf, act_for
from jarviscore.control.operations import read_operations
from jarviscore.control.policy import PolicyDenied
from jarviscore.nexus import call_proxy as module
from jarviscore.nexus.call_proxy import NexusCallProxy
from jarviscore.nexus.models import DynamicStrategy

API = "https://api.box.com/2.0/files/selected/content"
SIGNED = "https://dl.boxcloud.com/d/capability-DO-NOT-EXPOSE/download?signature=private"
REAL_CLIENT = httpx.AsyncClient
pytest_plugins = ["test_scopes"]


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.fixture
def make_proxy(monkeypatch):
    def make(handler, hosts=("dl.boxcloud.com",)):
        sent = []

        def transport(request):
            sent.append(request)
            return handler(request)

        def client(**kwargs):
            # Deliberately contaminated ambient client state must never be merged.
            return REAL_CLIENT(transport=httpx.MockTransport(transport),
                               headers={"Authorization": "Bearer ambient", "X-Ambient": "secret"},
                               cookies={"ambient": "secret"}, auth=("ambient", "secret"), **kwargs)

        monkeypatch.setattr(module, "_original_download_client", client, raising=False)
        auth = SimpleNamespace(
            _connections={"box": "box-handle"}, nexus_client=SimpleNamespace(refresh_connection=AsyncMock()),
            _strategy_cache={}, forget_strategy=lambda _: None,
            resolve_strategy=AsyncMock(return_value=DynamicStrategy(
                type="oauth2", credentials={"access_token": "credential-DO-NOT-EXPOSE"})),
        )
        return NexusCallProxy(auth, original_download_hosts={"box": hosts}), auth, sent
    return make


async def download(proxy, **kwargs):
    return await proxy.call("box-handle", "GET", API, original_download=True, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"", b"\xff\x00\xe2\x98\x83", b"a" * 64])
async def test_original_bytes_and_sanitized_metadata(make_proxy, content, caplog):
    caplog.set_level(logging.DEBUG)
    def handler(request):
        if request.url.host == "api.box.com":
            assert request.headers["Authorization"] == "Bearer credential-DO-NOT-EXPOSE"
            return httpx.Response(302, headers={"Location": SIGNED, "Set-Cookie": "secret=1"})
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert "x-ambient" not in request.headers
        assert request.headers["host"] == "dl.boxcloud.com"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, stream=Chunks([content]), headers={
            "Content-Type": "application/octet-stream", "Location": SIGNED,
            "Set-Cookie": "secret=1", "Content-Disposition": SIGNED, "X-Secret": SIGNED})
    proxy, auth, sent = make_proxy(handler)
    result = await download(proxy, max_bytes=64, headers={"X-Selector": "selected"})
    assert result["ok"] and result["content"] == content
    assert result["body"] == "" and result["json"] is None
    assert result["headers"] == {"content-type": "application/octet-stream"}
    assert "x-selector" not in sent[1].headers
    assert "cookie" not in sent[0].headers and "x-ambient" not in sent[0].headers
    assert auth.resolve_strategy.await_count == 1
    assert "DO-NOT-EXPOSE" not in caplog.text
    assert "DO-NOT-EXPOSE" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [
    "https://evil.example/download", "https://dl.boxcloud.com.evil.example/download",
    "http://dl.boxcloud.com/download", "https://user:password@dl.boxcloud.com/download",
    "https://dl.boxcloud.com:444/download", "https://dl.boxcloud.com/download#fragment",
    "/another", "https://api.box.com/2.0/files/other/content",
    "https://dl.boxcloud.com/download?token=credential-DO-NOT-EXPOSE",
    "https://dl.boxcloud.com/download?token=credential%2DDO%2DNOT%2DEXPOSE",
])
async def test_redirects_fail_closed_without_sending_or_exposing_target(make_proxy, target):
    proxy, auth, sent = make_proxy(lambda _: httpx.Response(302, headers={"Location": target}))
    result = await download(proxy)
    assert not result["ok"] and len(sent) == 1
    assert result["content"] == b"" and result["headers"] == {}
    assert target not in repr(result) and "DO-NOT-EXPOSE" not in repr(result)
    auth.nexus_client.refresh_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_redirect_hops_are_bounded(make_proxy):
    proxy, _, sent = make_proxy(lambda _: httpx.Response(302, headers={"Location": SIGNED}))
    assert not (await download(proxy))["ok"]
    assert len(sent) == 4  # initial + three operator-bounded redirects


@pytest.mark.asyncio
@pytest.mark.parametrize("hosts", [(), ("*.boxcloud.com",), ("{}.boxcloud.com",), ("https://dl.boxcloud.com",)])
async def test_only_exact_operator_hosts_are_accepted(make_proxy, hosts):
    if hosts:
        with pytest.raises(ValueError):
            make_proxy(lambda _: httpx.Response(200), hosts)
    else:
        proxy, _, sent = make_proxy(lambda _: httpx.Response(302, headers={"Location": SIGNED}), hosts)
        assert not (await download(proxy))["ok"]
        assert len(sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"follow_redirects": True}, {"allowed_download_hosts": ["evil.example"]},
    {"auth": ("user", "secret")}, {"cookies": {"x": "secret"}},
    {"headers": {"Host": "evil.example"}}, {"headers": {"Authorization": "Bearer model"}},
    {"headers": {"Cookie": "secret=1"}}, {"max_bytes": 0}, {"max_bytes": True},
    {"max_bytes": 64 * 1024 * 1024 + 1},
])
async def test_callers_cannot_control_transport_trust(make_proxy, kwargs):
    proxy, auth, sent = make_proxy(lambda _: httpx.Response(200))
    with pytest.raises(ValueError):
        await download(proxy, **kwargs)
    assert not sent
    auth.resolve_strategy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers", [
    (200, {}), (200, {"Content-Length": "9"}), (200, {"Content-Encoding": "gzip"}),
    (403, {"Location": SIGNED}),
])
async def test_byte_limit_stream_closure_and_failure_bodies(make_proxy, status, headers):
    stream = Chunks([b"abcd", b"efgh", b"ijkl", b"mnop"])
    proxy, _, _ = make_proxy(lambda _: httpx.Response(status, headers=headers, stream=stream))
    result = await download(proxy, max_bytes=8)
    assert not result["ok"] and result["content"] == b"" and result["body"] == ""
    assert stream.closed and stream.read <= 3


@pytest.mark.asyncio
async def test_401_refreshes_only_initial_source(make_proxy):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        if count == 1:
            return httpx.Response(401)
        if request.url.host == "api.box.com":
            return httpx.Response(302, headers={"Location": SIGNED})
        return httpx.Response(401, content=SIGNED.encode())
    proxy, auth, sent = make_proxy(handler)
    result = await download(proxy)
    assert not result["ok"] and result["status_code"] == 401
    assert auth.resolve_strategy.await_count == 2
    auth.nexus_client.refresh_connection.assert_awaited_once_with("box-handle")
    assert len(sent) == 3 and "DO-NOT-EXPOSE" not in repr(result)


@pytest.mark.asyncio
async def test_transport_errors_are_opaque(make_proxy, caplog):
    def handler(request):
        if request.url.host == "api.box.com":
            return httpx.Response(302, headers={"Location": SIGNED})
        raise httpx.ConnectError(SIGNED + " credential-DO-NOT-EXPOSE", request=request)
    proxy, _, _ = make_proxy(handler)
    result = await download(proxy)
    assert not result["ok"]
    assert "DO-NOT-EXPOSE" not in repr(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_multihost_continuations_never_receive_original_headers(make_proxy, status):
    def handler(request):
        if request.url.host == "api.box.com":
            return httpx.Response(status, headers={"Location": SIGNED})
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert "x-selector" not in request.headers and "x-ambient" not in request.headers
        if request.url.host == "dl.boxcloud.com":
            return httpx.Response(status, headers={"Location": "https://other.content.example/original"})
        assert request.headers["host"] == "other.content.example"
        return httpx.Response(200, stream=Chunks([b"original"]))
    proxy, _, sent = make_proxy(handler, ("dl.boxcloud.com", "other.content.example"))
    result = await download(proxy, headers={"X-Selector": "selected"})
    assert result["content"] == b"original" and len(sent) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("locations", [[], [("Location", SIGNED), ("Location", SIGNED)]])
async def test_missing_or_ambiguous_location_fails_closed(make_proxy, locations):
    proxy, _, sent = make_proxy(lambda _: httpx.Response(302, headers=locations))
    assert not (await download(proxy))["ok"] and len(sent) == 1


@pytest.mark.asyncio
async def test_operator_api_host_cannot_be_a_redirect_resource_escape(make_proxy):
    target = "https://api.box.com/2.0/files/other/content"
    proxy, _, sent = make_proxy(lambda _: httpx.Response(302, headers={"Location": target}),
                                ("api.box.com", "dl.boxcloud.com"))
    assert not (await download(proxy))["ok"] and len(sent) == 1


@pytest.mark.asyncio
async def test_caller_handle_cannot_download_signed_url_or_bridge_failed_credentials(make_proxy):
    proxy, auth, sent = make_proxy(lambda _: httpx.Response(200, stream=Chunks([b"original"])))
    result = await proxy.call("box-handle", "GET", SIGNED, original_download=True)
    assert not result["ok"] and not sent
    # Broker refusal is final: this mode never substitutes local credentials.
    auth.resolve_strategy.side_effect = RuntimeError("credential-DO-NOT-EXPOSE")
    result = await download(proxy)
    assert not result["ok"] and not sent and "DO-NOT-EXPOSE" not in repr(result)


@pytest.mark.asyncio
async def test_second_original_401_is_not_refreshed_again(make_proxy):
    proxy, auth, sent = make_proxy(lambda _: httpx.Response(401, content=SIGNED.encode()))
    result = await download(proxy)
    assert result["status_code"] == 401 and not result["ok"]
    assert len(sent) == 2 and auth.resolve_strategy.await_count == 2
    auth.nexus_client.refresh_connection.assert_awaited_once()


def test_operator_configuration_is_frozen_and_environment_setting_is_supported(make_proxy, monkeypatch):
    import importlib

    from jarviscore.config.settings import Settings

    _, auth, _ = make_proxy(lambda _: httpx.Response(200))
    configured = {"box": ["dl.boxcloud.com"]}
    proxy = NexusCallProxy(auth, original_download_hosts=configured)
    configured["box"].append("evil.example")
    assert proxy._original_download_hosts["box"] == frozenset({"dl.boxcloud.com"})
    monkeypatch.setenv("NEXUS_ORIGINAL_DOWNLOAD_HOSTS", '{"box": ["dl.boxcloud.com"]}')
    settings = Settings(_env_file=None)
    assert settings.nexus_original_download_hosts == {"box": ["dl.boxcloud.com"]}
    monkeypatch.setattr(importlib.import_module("jarviscore.config.settings"), "settings", settings)
    assert NexusCallProxy(auth)._original_download_hosts == proxy._original_download_hosts


@pytest.mark.asyncio
async def test_private_logging_is_context_local(make_proxy, caplog):
    import asyncio

    caplog.set_level(logging.DEBUG)
    entered = asyncio.Event()
    resume = asyncio.Event()
    async def handler(request):
        if request.url.host == "api.box.com":
            return httpx.Response(302, headers={"Location": SIGNED})
        logging.getLogger("httpcore.http11").debug("private path %s", SIGNED)
        entered.set()
        await resume.wait()
        return httpx.Response(200, stream=Chunks([b"original"]))
    async def unrelated():
        await entered.wait()
        logging.getLogger("httpx").info("unrelated-provider-visible")
        resume.set()
    proxy, _, _ = make_proxy(handler)
    result, _ = await asyncio.gather(download(proxy), unrelated())
    assert result["ok"]
    assert "unrelated-provider-visible" in caplog.text and "DO-NOT-EXPOSE" not in caplog.text


@pytest.mark.asyncio
async def test_total_timeout_is_opaque(make_proxy):
    import asyncio

    async def handler(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, stream=Chunks([b"original"]))
    proxy, _, sent = make_proxy(handler)
    result = await download(proxy, timeout=0.01)
    assert not result["ok"] and len(sent) == 1
    assert result["content"] == b"" and result["status_code"] == 0


@pytest.mark.asyncio
async def test_refresh_uses_same_native_operation_identity_and_new_credential(make_proxy):
    from jarviscore.auth.principal import operation

    count = 0
    def handler(request):
        nonlocal count
        count += 1
        expected = "credential-DO-NOT-EXPOSE" if count == 1 else "new-credential-DO-NOT-EXPOSE"
        assert request.headers["authorization"] == "Bearer " + expected
        return httpx.Response(401) if count == 1 else httpx.Response(200, stream=Chunks([b"original"]))
    proxy, auth, _ = make_proxy(handler)
    operations = []
    async def resolve(_):
        operations.append(operation.get())
        token = "credential-DO-NOT-EXPOSE" if len(operations) == 1 else "new-credential-DO-NOT-EXPOSE"
        return DynamicStrategy(type="oauth2", credentials={"access_token": token})
    auth.resolve_strategy.side_effect = resolve
    assert (await download(proxy, authority={"action_id": "original-operation"}))["ok"]
    assert operations == ["original-operation", "original-operation"]


@pytest.mark.asyncio
async def test_native_scope_and_operation_contract_hold_before_credentials(broker, monkeypatch):
    document = {"scopes": {"require": [{
        "name": "selected-original", "match": {"provider": "erp", "path": "/files/{id}/content"},
        "requires": "sources.read", "limits": [{"field": "request_path", "kind": "exact", "one_of": "paths"}],
    }]}}
    proxy, auth, _ = broker("strict", document)
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, stream=Chunks([b"original"]))
    monkeypatch.setattr(module, "_original_download_client", lambda **kw: REAL_CLIENT(
        transport=httpx.MockTransport(handler), **kw), raising=False)
    source = 'async def original():\n    return await nexus_call("GET", "https://erp.example.test/files/selected/content", original_download=True)'
    authority = {"atom": "original", "effect": "read", "code_origin": "model",
                 "contract": read_operations(source, entry="original")}
    person = OnBehalfOf.of("acme", "owner", scopes={"sources.read": {"paths": ["/files/selected/content"]}})
    with act_for(person):
        result = await proxy.call("conn-erp", "GET", "https://erp.example.test/files/selected/content",
                                  original_download=True, authority=authority)
        assert result["ok"]
        with pytest.raises(PolicyDenied):
            await proxy.call("conn-erp", "GET", "https://erp.example.test/files/other/content",
                             original_download=True, authority=authority)
        with pytest.raises(PolicyDenied):
            await proxy.call("conn-erp", "GET", "https://erp.example.test/delete",
                             original_download=True, authority=authority)
    assert len(sent) == 1 and auth.resolve_strategy.await_count == 1
