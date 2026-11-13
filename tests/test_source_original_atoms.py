"""Registry-first original provider atoms, native contracts and sandbox byte RPC."""
import base64
import json
from unittest.mock import AsyncMock

import pytest

from jarviscore.control.operations import read_operations
from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR, read_contract, shipped_source
from jarviscore.execution.code_registry import create_function_registry
from jarviscore.execution.coder_sandbox import create_coder_sandbox
from jarviscore.integrations.seed_registry import PROVIDER_META
from jarviscore.nexus.hosts import allowed_hosts

ATOMS = {
    "box_download_file": ("box", {"file_id": "selected"}, "https://api.box.com/2.0/files/selected/content"),
    "msgraph_download_drive_item": ("msgraph", {"item_id": "selected"},
                                    "https://graph.microsoft.com/v1.0/me/drive/items/selected/content"),
}
PRIVATE = "https://signed.example/?credential=DO-NOT-EXPOSE"


def response(content=b"", status=200):
    return {"ok": status == 200, "status_code": status, "content": content,
            "body": PRIVATE, "json": {"downloadUrl": PRIVATE},
            "headers": {"Location": PRIVATE, "Content-Disposition": PRIVATE, "Authorization": PRIVATE}}


def load(name, content=b"", status=200, output_dir=None):
    provider, _, _ = ATOMS[name]
    source = (SHIPPED_ATOMS_DIR / provider / f"{name}.py").read_text()
    contract = read_contract(source, system=provider, expected_name=name)
    assert contract.ok, contract.problems
    assert contract.atom.policy.effect == "read" and not contract.atom.policy.requires_approval
    assert shipped_source(contract.atom) == source
    operations = read_operations(source, entry=name)
    assert operations.verified, operations.as_dict()
    call = AsyncMock(return_value=response(content, status))
    namespace = {"nexus_call": call, "output_dir": output_dir}
    exec(source, namespace)  # noqa: S102 - exercise canonical shipped code, not model code
    return namespace[name], call, contract.atom, operations


@pytest.mark.parametrize("name", ATOMS)
def test_original_atoms_are_seeded_in_canonical_provider_registry(name, tmp_path):
    provider, _, url = ATOMS[name]
    _, _, atom, operations = load(name)
    assert provider in PROVIDER_META
    assert ("api.box.com" if provider == "box" else "graph.microsoft.com") in allowed_hosts(provider)
    assert operations.allows("GET", url)
    assert not operations.allows("POST", url)
    registry = create_function_registry(str(tmp_path / "registry"))
    assert name in {item["function_name"] for item in registry.get_functions_by_system(provider)}
    assert registry.get_function_metadata(name)["system"] == atom.system


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("original", [b"", b"\x00\xff\x80\xe2\x98\x83\r\n"])
@pytest.mark.parametrize("envelope", [False, True])
async def test_direct_and_native_byte_envelopes_preserve_originals(name, original, envelope):
    content = {"__bytes__": base64.b64encode(original).decode("ascii")} if envelope else original
    atom, call, _, _ = load(name, content)
    result = await atom(**ATOMS[name][1])
    assert result["success"] and result["error"] is None
    assert base64.b64decode(result["data"]["content_base64"], validate=True) == original
    assert result["data"]["byte_count"] == len(original)
    assert call.await_args.args == ("GET", ATOMS[name][2])
    assert call.await_args.kwargs == {"provider": ATOMS[name][0], "original_download": True,
                                     "max_bytes": 16 * 1024 * 1024}
    assert "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args,url", [
    ("box_download_file", {"file_id": "a/b?x#y%"}, "https://api.box.com/2.0/files/a%2Fb%3Fx%23y%25/content"),
    ("msgraph_download_drive_item", {"item_id": "a/b?x#y%", "drive_id": "drive/id"},
     "https://graph.microsoft.com/v1.0/drives/drive%2Fid/items/a%2Fb%3Fx%23y%25/content"),
])
async def test_source_identifiers_are_encoded_single_segments(name, args, url):
    atom, call, _, contract = load(name)
    assert (await atom(**args))["success"]
    assert call.await_args.args == ("GET", url) and contract.allows("GET", url)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("path", ["/absolute.pdf", "../outside.pdf", "nested/../outside.pdf", ".",
                                  "nested//file.pdf", "nested/./file.pdf", "C:\\file.pdf", "a\\b.pdf",
                                  "https://signed.example/file", "file\x00.pdf", "file\n.pdf", None])
async def test_unsafe_destination_paths_fail_before_download(name, path, tmp_path):
    atom, call, _, _ = load(name, b"original", output_dir=tmp_path)
    result = await atom(**ATOMS[name][1], destination_path=path)
    assert not result["success"] and result["data"] is None
    call.assert_not_awaited()
    assert not list(tmp_path.iterdir()) and "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("content,status", [
    (b"original", 302), (b"original", 401), (b"original", 403),
    (None, 200), ("replacement text", 200), ({"__bytes__": "invalid!"}, 200),
    ({"__bytes__": "AA==", "extra": PRIVATE}, 200), (b"oversized", 200),
])
async def test_failed_downloads_and_malformed_bytes_write_no_file(name, content, status, tmp_path):
    atom, _, _, _ = load(name, content, status, output_dir=tmp_path)
    result = await atom(**ATOMS[name][1], destination_path="nested/original.pdf", max_bytes=8)
    assert not result["success"] and result["data"] is None
    assert not list(tmp_path.rglob("*")) and "DO-NOT-EXPOSE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
async def test_destination_links_and_existing_files_are_not_followed_or_overwritten(name, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    private = tmp_path / "private"
    private.mkdir()
    existing = private / "original.pdf"
    existing.write_bytes(b"private original")
    (output / "linked").symlink_to(private, target_is_directory=True)
    (output / "original.pdf").symlink_to(existing)
    (output / "existing.pdf").write_bytes(b"previous original")
    atom, _, _, _ = load(name, b"new original", output_dir=output)
    for path in ("linked/original.pdf", "original.pdf", "existing.pdf"):
        assert not (await atom(**ATOMS[name][1], destination_path=path))["success"]
    assert existing.read_bytes() == b"private original"
    assert (output / "existing.pdf").read_bytes() == b"previous original"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
@pytest.mark.parametrize("original", [b"", b"\x00\xff\x80original\r\n"])
async def test_shipped_sandbox_downloads_empty_and_nonascii_originals_losslessly(name, original, tmp_path):
    _, _, metadata, contract = load(name)
    calls = []
    class Proxy:
        async def call(self, connection_id, method, url, **kwargs):
            calls.append((connection_id, method, url, kwargs))
            return response(original)

        def connection_handle(self, provider):
            assert provider == ATOMS[name][0]
            return "selected-source-connection"

    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "workspace", timeout=20, nexus_call_proxy=Proxy())
    result = await sandbox.execute_shipped_atom(
        metadata, {**ATOMS[name][1], "destination_path": "nested/original-☃.bin", "max_bytes": 64},
        context={"_nexus_connection_id": "selected-source-connection", "_nexus_provider": ATOMS[name][0],
                 "_atom_authority": {"system": ATOMS[name][0], "atom": name, "effect": "read", "code_origin": "shipped", "contract": contract}},
    )
    assert result["status"] == "success", result
    assert (sandbox.output_dir / "nested/original-☃.bin").read_bytes() == original
    assert base64.b64decode(result["data"]["content_base64"], validate=True) == original
    assert result["data"]["destination_path"] == "nested/original-☃.bin"
    assert result["data"]["byte_count"] == len(original)
    assert result["artifacts"][0]["bytes"] == len(original)
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
    assert calls[0][:3] == ("selected-source-connection", "GET", ATOMS[name][2])
    assert calls[0][3]["original_download"] is True and calls[0][3]["max_bytes"] == 64
    assert contract.allows(calls[0][1], calls[0][2])


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ATOMS)
async def test_shipped_sandbox_failed_download_creates_no_artifact(name, tmp_path):
    _, _, metadata, _ = load(name)
    class Proxy:
        async def call(self, *args, **kwargs):
            return {"ok": False, "status_code": 403, "content": b"", "body": "", "headers": {}}

        def connection_handle(self, provider):
            return "selected-source-connection"

    sandbox = create_coder_sandbox(workspace_dir=tmp_path / "workspace", timeout=20, nexus_call_proxy=Proxy())
    result = await sandbox.execute_shipped_atom(
        metadata, {**ATOMS[name][1], "destination_path": "original.pdf"},
        context={"_nexus_connection_id": "selected-source-connection", "_nexus_provider": ATOMS[name][0]},
    )
    assert result["status"] == "failure", result
    assert not result["artifacts"] and not list(sandbox.output_dir.rglob("*"))
    assert "DO-NOT-EXPOSE" not in json.dumps(result)
