"""Actual shipped sandbox -> native policy -> credential-bound streamed provider reads."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_direct_original_atoms import ATOMS as DIRECT
from test_original_download import Chunks
from test_source_original_atoms import ATOMS as REDIRECTED

from jarviscore.control.operations import read_operations
from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR, read_contract
from jarviscore.execution.coder_sandbox import create_coder_sandbox
from jarviscore.nexus import call_proxy as module
from jarviscore.nexus.call_proxy import NexusCallProxy
from jarviscore.nexus.models import DynamicStrategy

REAL_CLIENT = httpx.AsyncClient
SIGNED = "https://operator.content.example/selected-original?capability=DO-NOT-EXPOSE"
ATOMS = {**DIRECT, **{name: (provider, args, "GET", url) for name, (provider, args, url) in REDIRECTED.items()}}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("original,status", [(b"", 200), (b"\x00\xff\x80\xe2\x98\x83", 200), (b"denied", 403), (b"oversized original", 200)])
async def test_native_original_atom_sandbox_keeps_credentials_and_signed_urls_private(name, original, status, monkeypatch, tmp_path, caplog):
    provider, args, method, url = ATOMS[name]
    source = (SHIPPED_ATOMS_DIR / provider / f"{name}.py").read_text()
    atom = read_contract(source, system=provider, expected_name=name).atom
    contract = read_operations(source, entry=name)
    assert contract.verified and contract.allows(method, url)
    sent = []
    def handler(request):
        sent.append(request)
        assert "cookie" not in request.headers and "x-ambient" not in request.headers
        if request.url.host != "operator.content.example":
            assert request.method == method and str(request.url).split("?", 1)[0] == url
            assert request.headers["authorization"] == "Bearer native-DO-NOT-EXPOSE"
            if provider == "dropbox":
                assert json.loads(request.headers["Dropbox-API-Arg"]) == {"path": args["dropbox_path"]}
            if provider == "google_drive":
                assert request.url.params["alt"] == "media"
            if name in REDIRECTED and status == 200:
                return httpx.Response(302, headers={"Location": SIGNED, "Set-Cookie": "DO-NOT-EXPOSE"})
        else:
            assert request.method == "GET" and "authorization" not in request.headers
        return httpx.Response(status, stream=Chunks([original]), headers={"Location": SIGNED, "Content-Disposition": SIGNED})
    monkeypatch.setattr(module, "_original_download_client", lambda **kwargs: REAL_CLIENT(
        transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer ambient", "X-Ambient": "private"},
        cookies={"ambient": "private"}, auth=("ambient", "private"), **kwargs))
    monkeypatch.setenv("JARVISCORE_CONTROL_MODE", "strict")
    monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
    auth = SimpleNamespace(_connections={provider: "selected-source-connection"}, _strategy_cache={}, nexus_client=None,
                           resolve_strategy=AsyncMock(return_value=DynamicStrategy(
                               type="oauth2", credentials={"access_token": "native-DO-NOT-EXPOSE"})))
    proxy = NexusCallProxy(auth, original_download_hosts={provider: ["operator.content.example"]})
    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "workspace", timeout=20, nexus_call_proxy=proxy)
    # These are the parent-side grants supplied by native Coder's registered-atom path.
    # The legacy transport identity key retains the READ effect; no POST mutation is relabeled.
    grant = {"atom": name, "effect": "read", "code_origin": "shipped", "contract": contract,
             "action_id": "native-original-read"}
    result = await sandbox.execute_shipped_atom(
        atom, {**args, "destination_path": "nested/original-☃.bin", "max_bytes": 8},
        context={"_nexus_connection_id": "selected-source-connection", "_nexus_provider": provider,
                 "_atom_authority": {**grant, "system": provider}, "_mutation_authority": grant})
    if status == 200 and len(original) <= 8:
        assert result["status"] == "success", result
        assert (sandbox.output_dir / "nested/original-☃.bin").read_bytes() == original
        assert result["artifacts"][0]["bytes"] == len(original)
    else:
        assert result["status"] == "failure", result
        assert not list(sandbox.output_dir.rglob("*")) and not result["artifacts"]
    assert "DO-NOT-EXPOSE" not in json.dumps(result) and "DO-NOT-EXPOSE" not in caplog.text
    assert auth.resolve_strategy.await_count == 1
    assert len(sent) == (2 if name in REDIRECTED and status == 200 else 1)
