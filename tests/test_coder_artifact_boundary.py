"""Artifact collection cannot turn workspace links into host-data reads."""

import os

import pytest

from jarviscore.execution.coder_sandbox import CoderResult, CoderSandbox


class Storage:
    def __init__(self):
        self.saved = {}

    async def save(self, key, content):
        self.saved[key] = content


@pytest.mark.asyncio
async def test_symlink_to_another_workspace_is_never_published(tmp_path):
    private = tmp_path / "other-person"
    private.mkdir()
    secret = private / "original.pdf"
    secret.write_bytes(b"other person's private original")
    storage = Storage()
    sandbox = CoderSandbox(tmp_path / "current-person", output_subdir="output", blob_storage=storage)
    (sandbox.output_dir / "original.pdf").symlink_to(secret)
    result = CoderResult(success=True)
    await sandbox._collect_artifacts(result, {})
    assert storage.saved == {}
    assert result.artifacts == []


@pytest.mark.asyncio
async def test_replacing_output_directory_with_a_link_cannot_publish_external_files(tmp_path):
    private = tmp_path / "other-person"
    private.mkdir()
    (private / "original.pdf").write_bytes(b"private")
    storage = Storage()
    sandbox = CoderSandbox(tmp_path / "current-person", output_subdir="output", blob_storage=storage)
    sandbox.output_dir.rmdir()
    sandbox.output_dir.symlink_to(private, target_is_directory=True)
    result = CoderResult(success=True)
    await sandbox._collect_artifacts(result, {})
    assert storage.saved == {}
    assert result.artifacts == []


@pytest.mark.asyncio
async def test_regular_binary_artifacts_remain_lossless(tmp_path):
    storage = Storage()
    sandbox = CoderSandbox(tmp_path / "workspace", output_subdir="output", blob_storage=storage)
    payload = bytes(range(256))
    (sandbox.output_dir / "original.pdf").write_bytes(payload)
    result = CoderResult(success=True)
    await sandbox._collect_artifacts(result, {})
    assert storage.saved == {"artifacts/original.pdf": payload}
    assert result.artifacts[0]["bytes"] == len(payload)


def test_artifact_read_rejects_a_link_installed_after_the_snapshot(tmp_path):
    sandbox = CoderSandbox(tmp_path / "workspace", output_subdir="output")
    artifact = sandbox.output_dir / "original.pdf"
    artifact.write_bytes(b"own original")
    assert str(artifact) in sandbox._snapshot_output()
    secret = tmp_path / "other-person.pdf"
    secret.write_bytes(b"private")
    artifact.unlink()
    artifact.symlink_to(secret)
    with pytest.raises((OSError, ValueError)):
        sandbox._read_artifact(artifact)


def test_artifact_read_rejects_a_parent_link_installed_after_snapshot(tmp_path):
    sandbox = CoderSandbox(tmp_path / "workspace", output_subdir="output")
    nested = sandbox.output_dir / "nested"
    nested.mkdir()
    artifact = nested / "original.pdf"
    artifact.write_bytes(b"own original")
    assert str(artifact) in sandbox._snapshot_output()
    private = tmp_path / "other-person"
    private.mkdir()
    (private / "original.pdf").write_bytes(b"private")
    artifact.unlink()
    nested.rmdir()
    nested.symlink_to(private, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        sandbox._read_artifact(artifact)


def test_artifact_read_rejects_an_external_path(tmp_path):
    sandbox = CoderSandbox(tmp_path / "workspace", output_subdir="output")
    external = tmp_path / "other-person.pdf"
    external.write_bytes(b"private")
    with pytest.raises((OSError, ValueError)):
        sandbox._read_artifact(external)


@pytest.mark.asyncio
async def test_confined_generated_code_cannot_publish_an_external_link(tmp_path):
    private = tmp_path / "other-person.pdf"
    private.write_bytes(b"private")
    storage = Storage()
    sandbox = CoderSandbox(tmp_path / "workspace", output_subdir="output", blob_storage=storage)
    if not sandbox.confined:
        pytest.skip("OS confinement is unavailable")
    result = await sandbox.execute(
        f"blob_path('original.pdf').symlink_to({str(private)!r})\nresult = {{'data': 'done'}}\n"
    )
    assert result["status"] == "success"
    assert result["artifacts"] == []
    assert storage.saved == {}


def test_artifact_read_rejects_hard_links(tmp_path):
    sandbox = CoderSandbox(tmp_path / "workspace", output_subdir="output")
    private = tmp_path / "other-person.pdf"
    private.write_bytes(b"private")
    linked = sandbox.output_dir / "original.pdf"
    os.link(private, linked)
    with pytest.raises((OSError, ValueError)):
        sandbox._read_artifact(linked)
