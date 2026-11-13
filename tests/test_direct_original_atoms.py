"""Existing Drive/Dropbox shapes survive bounded native originals and sandbox RPC."""
import base64
import importlib
import json

import pytest

from jarviscore.control.operations import read_operations
from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR, read_contract
from jarviscore.execution.coder_sandbox import create_coder_sandbox

ATOMS = {"google_drive_download_file": ("google_drive", {"file_id": "a/b?x#y%"}, "GET",
           "https://www.googleapis.com/drive/v3/files/a%2Fb%3Fx%23y%25"),
         "dropbox_download_file": ("dropbox", {"dropbox_path": '/Deal/évidence "\\\n.pdf'}, "POST",
           "https://content.dropboxapi.com/2/files/download")}
PRIVATE = "https://signed.example/?credential=DO-NOT-EXPOSE"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("original", [b"", b"\x00\xff\x80original"])
async def test_existing_direct_originals_use_bounded_native_mode_and_lossless_envelopes(name, original, tmp_path, monkeypatch):
    provider, args, method, url = ATOMS[name]
    module = importlib.import_module(f"jarviscore.integrations.atoms.{provider}.{name}")
    calls = []
    async def nexus_call(*call_args, **kwargs):
        calls.append((call_args, kwargs))
        return {"ok": True, "status_code": 200, "content": {"__bytes__": base64.b64encode(original).decode("ascii")},
                "body": PRIVATE, "headers": {"Location": PRIVATE}}
    monkeypatch.setattr(module, "nexus_call", nexus_call, raising=False)
    destination = tmp_path / "nested" / "original.bin"
    result = await getattr(module, name)(**args, destination_path=str(destination), max_bytes=32)
    assert result["success"] and destination.read_bytes() == original
    assert result["data"] == {"destination_path": str(destination), "bytes": len(original)}
    assert calls[0][0] == (method, url)
    assert calls[0][1]["original_download"] is True and calls[0][1]["max_bytes"] == 32
    assert calls[0][1]["provider"] == provider
    if provider == "dropbox":
        header = calls[0][1]["headers"]["Dropbox-API-Arg"]
        assert header.isascii() and json.loads(header) == {"path": args["dropbox_path"]}
    else:
        assert result["file_id"] == args["file_id"]
        assert calls[0][1]["params"] == {"alt": "media"}
    assert "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("content,status", [(b"oversized", 200), ({"__bytes__": "invalid!"}, 200), (b"denied", 403)])
async def test_existing_original_failure_never_writes_files_or_private_errors(name, content, status, tmp_path, monkeypatch):
    provider, args, _, _ = ATOMS[name]
    module = importlib.import_module(f"jarviscore.integrations.atoms.{provider}.{name}")
    async def nexus_call(*args, **kwargs):
        return {"ok": status == 200, "status_code": status, "content": content, "body": PRIVATE}
    monkeypatch.setattr(module, "nexus_call", nexus_call, raising=False)
    result = await getattr(module, name)(**args, destination_path=str(tmp_path / "nested/original.bin"), max_bytes=8)
    assert not result["success"] and not list(tmp_path.rglob("*"))
    assert "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("original", [b"", b"\x00\xff\x80original"])
async def test_existing_direct_original_sandbox_bytes_and_verified_read_contract(name, original, tmp_path):
    provider, args, method, url = ATOMS[name]
    source = (SHIPPED_ATOMS_DIR / provider / f"{name}.py").read_text()
    metadata = read_contract(source, system=provider, expected_name=name)
    assert metadata.ok and metadata.atom.policy.effect == "read"
    contract = read_operations(source, entry=name)
    assert contract.verified and contract.allows(method, url)
    calls = []
    class Proxy:
        async def call(self, connection_id, method, url, **kwargs):
            calls.append((connection_id, method, url, kwargs))
            return {"ok": True, "status_code": 200, "content": original, "body": PRIVATE}

        def connection_handle(self, system):
            return "native-source-connection"
    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "workspace", timeout=20, nexus_call_proxy=Proxy())
    result = await sandbox.execute_shipped_atom(
        metadata.atom, {**args, "destination_path": "nested/original-☃.bin", "max_bytes": 32},
        context={"_nexus_connection_id": "native-source-connection", "_nexus_provider": provider,
                 "_atom_authority": {"system": provider, "atom": name, "effect": "read", "code_origin": "shipped", "contract": contract},
                 "_mutation_authority": {"atom": name, "effect": "read", "code_origin": "shipped", "contract": contract, "action_id": "native-original-read"}})
    assert result["status"] == "success", result
    assert (sandbox.output_dir / "nested/original-☃.bin").read_bytes() == original
    assert result["data"] == {"destination_path": "nested/original-☃.bin", "bytes": len(original)}
    assert calls[0][:3] == ("native-source-connection", method, url)
    assert calls[0][3]["original_download"] is True and calls[0][3]["max_bytes"] == 32
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
