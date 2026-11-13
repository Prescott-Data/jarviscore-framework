"""Only reviewed native direct binary POST reads may opt in; POST never redirects."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_original_download import Chunks

from jarviscore import OnBehalfOf, act_for
from jarviscore.control.operations import read_operations
from jarviscore.control.policy import ControlPolicy, PolicyDenied, ProviderCall
from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR
from jarviscore.nexus import call_proxy as module
from jarviscore.nexus.call_proxy import NexusCallProxy
from jarviscore.nexus.models import DynamicStrategy

URL = "https://content.dropboxapi.com/2/files/download"
SIGNED = "https://download.content.example/private?signature=DO-NOT-EXPOSE"
REAL_CLIENT = httpx.AsyncClient
pytest_plugins = ["test_scopes"]


def authority(**more):
    source = (SHIPPED_ATOMS_DIR / "dropbox/dropbox_download_file.py").read_text()
    return {"atom": "dropbox_download_file", "effect": "read", "code_origin": "shipped",
            "contract": read_operations(source, entry="dropbox_download_file"), **more}


@pytest.fixture
def direct_proxy(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVISCORE_CONTROL_MODE", "strict")
    monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
    def make(handler):
        sent = []
        def transport(request):
            sent.append(request)
            return handler(request)
        monkeypatch.setattr(module, "_original_download_client", lambda **kwargs: REAL_CLIENT(
            transport=httpx.MockTransport(transport), headers={"Authorization": "Bearer ambient", "X-Ambient": "private"},
            cookies={"ambient": "private"}, auth=("ambient", "private"), **kwargs))
        auth = SimpleNamespace(_connections={"dropbox": "dropbox-handle"}, _strategy_cache={},
                               forget_strategy=lambda _: None,
                               nexus_client=SimpleNamespace(refresh_connection=AsyncMock()),
                               resolve_strategy=AsyncMock(return_value=DynamicStrategy(
                                   type="oauth2", credentials={"access_token": "native-credential"})))
        return NexusCallProxy(auth, original_download_hosts={"dropbox": ["download.content.example"]}), auth, sent
    return make


@pytest.mark.asyncio
@pytest.mark.parametrize("original", [b"", b"\x00\xff\x80\xe2\x98\x83"])
async def test_verified_native_post_direct_bytes_are_bounded_and_ambient_auth_is_refused(direct_proxy, original):
    selector = '/Deal/quote"\\\n☃.pdf'
    def handler(request):
        assert request.method == "POST" and request.url == URL
        assert request.headers["authorization"] == "Bearer native-credential"
        assert "cookie" not in request.headers and "x-ambient" not in request.headers
        assert request.headers["accept-encoding"] == "identity" and request.content == b""
        assert json.loads(request.headers["Dropbox-API-Arg"]) == {"path": selector}
        return httpx.Response(200, stream=Chunks([original]), headers={"Location": SIGNED})
    proxy, auth, sent = direct_proxy(handler)
    result = await proxy.call("dropbox-handle", "POST", URL, original_download=True, max_bytes=8,
                              authority=authority(), headers={"Dropbox-API-Arg": json.dumps({"path": selector})})
    assert result["ok"] and result["content"] == original
    assert result["headers"] == {} and "DO-NOT-EXPOSE" not in repr(result)
    assert len(sent) == 1 and auth.resolve_strategy.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_native_post_refuses_every_redirect_even_operator_allowed_hosts(direct_proxy, status):
    proxy, auth, sent = direct_proxy(lambda _: httpx.Response(status, headers={"Location": SIGNED}))
    result = await proxy.call("dropbox-handle", "POST", URL, original_download=True, authority=authority())
    assert not result["ok"] and result["content"] == b"" and result["status_code"] == status
    assert result["headers"] == {} and len(sent) == 1 and "DO-NOT-EXPOSE" not in repr(result)
    auth.nexus_client.refresh_connection.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides,url", [
    ({"code_origin": "model"}, URL), ({"code_origin": "registry"}, URL),
    ({"code_origin": "direct"}, URL), ({"effect": "write"}, URL),
    ({"contract": None}, URL), ({}, "https://content.dropboxapi.com/2/files/upload"),
])
async def test_original_post_requires_native_verified_read_not_model_post_claims(direct_proxy, overrides, url):
    proxy, auth, sent = direct_proxy(lambda _: httpx.Response(200, stream=Chunks([b"original"])))
    with pytest.raises(ValueError):
        await proxy.call("dropbox-handle", "POST", url, original_download=True, authority=authority(**overrides))
    assert not sent
    auth.resolve_strategy.assert_not_awaited()
    call = ProviderCall(provider="dropbox", method="POST", url=URL, atom="model_download",
                        declared_effect="read", code_origin="model", contract=authority()["contract"])
    assert call.effect == "write" and not ControlPolicy(mode="strict").decide(call).allowed


@pytest.mark.asyncio
async def test_native_post_scope_refusal_precedes_credentials(broker, monkeypatch):
    proxy, auth, _ = broker("strict", {"scopes": {"require": [{
        "name": "selected-original", "match": {"provider": "dropbox"}, "requires": "sources.read",
        "limits": [{"field": "headers.dropbox-api-arg", "kind": "exact", "one_of": "selectors"}],
    }]}})
    auth._connections = {"dropbox": "dropbox-handle"}
    auth.resolve_strategy.return_value = DynamicStrategy(type="oauth2", credentials={"access_token": "native"})
    sent = []
    def transport(request):
        sent.append(request)
        return httpx.Response(200, stream=Chunks([b"original"]))
    monkeypatch.setattr(module, "_original_download_client", lambda **kwargs: REAL_CLIENT(
        transport=httpx.MockTransport(transport), **kwargs))
    selected = json.dumps({"path": "/selected.pdf"})
    person = OnBehalfOf.of("acme", "owner", scopes={"sources.read": {"selectors": [selected]}})
    with act_for(person):
        assert (await proxy.call("dropbox-handle", "POST", URL, original_download=True,
                                 authority=authority(), headers={"Dropbox-API-Arg": selected}))["ok"]
        with pytest.raises(PolicyDenied):
            await proxy.call("dropbox-handle", "POST", URL, original_download=True, authority=authority(),
                             headers={"Dropbox-API-Arg": json.dumps({"path": "/other.pdf"})})
    assert len(sent) == 1 and auth.resolve_strategy.await_count == 1


@pytest.mark.asyncio
async def test_native_post_preview_is_held_before_credentials_or_network(direct_proxy):
    from jarviscore.control.policy import PreviewHeld

    proxy, auth, sent = direct_proxy(lambda _: httpx.Response(200, stream=Chunks([b"original"])))
    preview = []
    with pytest.raises(PreviewHeld):
        await proxy.call("dropbox-handle", "POST", URL, original_download=True,
                         authority=authority(preview=preview))
    assert preview and not sent
    auth.resolve_strategy.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_post_refresh_keeps_method_and_byte_limit(direct_proxy):
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        assert request.method == "POST"
        return httpx.Response(401) if count == 1 else httpx.Response(200, stream=Chunks([b"0123456789"]))
    proxy, auth, sent = direct_proxy(handler)
    result = await proxy.call("dropbox-handle", "POST", URL, original_download=True, authority=authority(), max_bytes=8)
    assert not result["ok"] and result["content"] == b"" and len(sent) == 2
    auth.nexus_client.refresh_connection.assert_awaited_once()
