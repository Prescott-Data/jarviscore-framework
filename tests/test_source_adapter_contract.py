import pytest

from jarviscore.execution.sources import (
    SourceContractError,
    SourceIntegrityError,
    capture_source,
)
from jarviscore.execution.workspace import BlobSnapshotStore, SourceRef
from jarviscore.storage import LocalBlobStorage


@pytest.mark.asyncio
async def test_adapter_contract_accepts_persisted_snapshot(tmp_path):
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    source = SourceRef("fixture", "project", "main")
    snapshot = await store.capture(source, "commit-1", {"README.md": "hello\n"})

    class Adapter:
        async def capture(self, requested):
            assert requested == source
            return snapshot

    assert await capture_source(Adapter(), store, source) == snapshot


@pytest.mark.asyncio
async def test_adapter_contract_rejects_changed_identity(tmp_path):
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    source = SourceRef("fixture", "project", "main")
    snapshot = await store.capture(
        SourceRef("fixture", "other", "main"),
        "commit-1",
        {"README.md": "hello\n"},
    )

    class Adapter:
        async def capture(self, requested):
            return snapshot

    with pytest.raises(SourceContractError, match="locator"):
        await capture_source(Adapter(), store, source)


@pytest.mark.asyncio
async def test_adapter_contract_rejects_unpersisted_manifest(tmp_path):
    source = SourceRef("fixture", "project", "main")
    foreign_store = BlobSnapshotStore(
        LocalBlobStorage(str(tmp_path / "foreign-blobs"))
    )
    snapshot = await foreign_store.capture(
        source, "commit-1", {"README.md": "hello\n"}
    )
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "mesh-blobs")))

    class Adapter:
        async def capture(self, requested):
            return snapshot

    with pytest.raises(SourceIntegrityError, match="persisted integrity"):
        await capture_source(Adapter(), store, source)


@pytest.mark.asyncio
async def test_adapter_contract_rejects_corrupted_blob(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    source = SourceRef("fixture", "project", "main")
    snapshot = await store.capture(source, "commit-1", {"README.md": "hello\n"})
    await blobs.save(snapshot.entries[0].blob_path, b"tampered")

    class Adapter:
        async def capture(self, requested):
            return snapshot

    with pytest.raises(SourceIntegrityError, match="integrity validation"):
        await capture_source(Adapter(), store, source)


@pytest.mark.asyncio
async def test_adapter_contract_rejects_forged_snapshot_identity(tmp_path):
    from dataclasses import replace

    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    source = SourceRef("fixture", "project", "main")
    snapshot = await store.capture(source, "commit-1", {"README.md": "hello\n"})
    forged = replace(snapshot, snapshot_id="0" * 64)
    await store.blob_storage.save(
        forged.manifest_blob_path,
        __import__("json").dumps({
            "snapshot_id": forged.snapshot_id,
            "source": {
                "provider": source.provider,
                "locator": source.locator,
                "revision": source.revision,
            },
            "resolved_revision": forged.resolved_revision,
            "entries": [entry.__dict__ for entry in forged.entries],
            "manifest_blob_path": forged.manifest_blob_path,
        }),
    )

    class Adapter:
        async def capture(self, requested):
            return forged

    with pytest.raises(SourceIntegrityError, match="identity"):
        await capture_source(Adapter(), store, source)