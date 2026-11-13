"""Original download selectors survive JSON and HTTP header encoding."""

import importlib
import json

import pytest

atom = importlib.import_module("jarviscore.integrations.atoms.dropbox.dropbox_download_file")


@pytest.mark.parametrize(
    "selector",
    [
        '/Deal/quote".pdf',
        "/Deal/back\\slash.xlsx",
        "/Deal/line\nbreak.docx",
        "/Deal/évidence 📄.pdf",
    ],
)
async def test_original_selector_and_bytes(monkeypatch, tmp_path, selector):
    original = bytes(range(256))
    calls = []

    async def nexus_call(method, url, **kwargs):
        calls.append((method, url, kwargs))
        header = kwargs["headers"]["Dropbox-API-Arg"]
        assert header.encode("ascii")
        assert json.loads(header) == {"path": selector}
        return {"status_code": 200, "content": original, "body": {}}

    monkeypatch.setattr(atom, "nexus_call", nexus_call, raising=False)
    destination = tmp_path / "owner-private" / "original.bin"
    result = await atom.dropbox_download_file(selector, str(destination))
    assert result["success"], result["error"]
    assert destination.read_bytes() == original
    assert result["data"]["bytes"] == len(original)
    assert len(calls) == 1
    assert calls[0][:2] == ("POST", "https://content.dropboxapi.com/2/files/download")
    assert atom.ATOM_POLICY == {"effect": "read", "approval": "never"}


async def test_failure_does_not_create_original(monkeypatch, tmp_path):
    async def nexus_call(*args, **kwargs):
        return {"status_code": 403, "content": b"denied", "body": "denied"}

    monkeypatch.setattr(atom, "nexus_call", nexus_call, raising=False)
    destination = tmp_path / "original.bin"
    result = await atom.dropbox_download_file("/file.pdf", str(destination))
    assert not result["success"]
    assert not destination.exists()
