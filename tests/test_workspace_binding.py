import json
from pathlib import Path

import pytest

from jarviscore.execution.workspace import (
    BlobSnapshotStore,
    SandboxBinding,
    SourceRef,
    WorkspaceDeltaConflict,
    cleanup_stale_bindings,
)
from jarviscore.storage import LocalBlobStorage


def test_workspace_contracts_are_public_framework_api():
    from jarviscore import (
        BlobSnapshotStore as PublicBlobSnapshotStore,
        SandboxBinding as PublicSandboxBinding,
        SourceRef as PublicSourceRef,
        SourceSnapshot as PublicSourceSnapshot,
        WorkspaceDelta as PublicWorkspaceDelta,
    )

    assert PublicBlobSnapshotStore is BlobSnapshotStore
    assert PublicSandboxBinding is SandboxBinding
    assert PublicSourceRef is SourceRef
    assert PublicSourceSnapshot.__name__ == "SourceSnapshot"
    assert PublicWorkspaceDelta.__name__ == "WorkspaceDelta"


@pytest.mark.asyncio
async def test_snapshot_round_trips_through_blob_storage(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    source = SourceRef(provider="archive", locator="fixture", revision="main")

    snapshot = await store.capture(
        source,
        "commit-1",
        {"README.md": "hello\n", "src/main.py": b"print('hello')\n"},
        executable_paths={"src/main.py"},
    )
    restored = await store.load(snapshot.manifest_blob_path)

    assert restored == snapshot
    assert len(await blobs.list("source_snapshots/objects/")) == 2


@pytest.mark.asyncio
async def test_binding_materializes_snapshot_and_exports_copy_on_write_delta(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {
            "README.md": "before\n",
            "src/delete.py": "delete me\n",
            "src/unchanged.py": "same\n",
        },
    )
    binding_root = tmp_path / "binding"

    async with SandboxBinding(
        store, snapshot, temporary_root=binding_root, cleanup=True
    ) as binding:
        assert binding.workspace is not None
        assert (binding.workspace / "README.md").read_text() == "before\n"
        (binding.workspace / "README.md").write_text("after\n")
        (binding.workspace / "src/delete.py").unlink()
        (binding.workspace / "src/new.py").write_text("new\n")

        delta = await binding.export_delta("workflows/wf-1/workspaces/step-1")

        assert [entry.path for entry in delta.modified] == ["README.md"]
        assert [entry.path for entry in delta.added] == ["src/new.py"]
        assert delta.deleted == ("src/delete.py",)
        assert await blobs.read(delta.modified[0].blob_path) == "after\n"
        assert await blobs.read(delta.manifest_blob_path) is not None

    assert not binding_root.exists()


@pytest.mark.asyncio
async def test_snapshot_rejects_paths_that_escape_workspace(tmp_path):
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))

    with pytest.raises(ValueError, match="safe relative"):
        await store.capture(
            SourceRef(provider="archive", locator="fixture", revision="main"),
            "commit-1",
            {"../outside.txt": "no"},
        )


@pytest.mark.asyncio
async def test_materialization_rejects_corrupted_blob(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {"value.txt": "expected\n"},
    )
    await blobs.save(snapshot.entries[0].blob_path, "corrupted\n")

    binding_root = tmp_path / "failed-binding"
    with pytest.raises(ValueError, match="integrity"):
        async with SandboxBinding(store, snapshot, temporary_root=binding_root):
            pass
    assert not binding_root.exists()


@pytest.mark.asyncio
async def test_binding_rejects_existing_or_symlinked_cleanup_root(tmp_path):
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {"value.txt": "safe\n"},
    )
    real = tmp_path / "real"
    real.mkdir()
    (real / "keep.txt").write_text("safe\n")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(FileExistsError):
        async with SandboxBinding(store, snapshot, temporary_root=alias):
            pass

    assert (real / "keep.txt").read_text() == "safe\n"


def test_stale_binding_cleanup_removes_only_marked_dead_processes(tmp_path):
    stale = tmp_path / "jarviscore-workspace-stale"
    stale.mkdir()
    (stale / ".jarviscore-binding.json").write_text(
        json.dumps({"pid": 999_999_999, "created_at": 0, "snapshot_id": "snapshot"})
    )
    unmarked = tmp_path / "jarviscore-workspace-unmarked"
    unmarked.mkdir()

    removed = cleanup_stale_bindings(tmp_path, minimum_age_seconds=0)

    assert removed == [stale]
    assert not stale.exists()
    assert unmarked.exists()


@pytest.mark.asyncio
async def test_binding_creates_coder_sandbox_at_materialized_workspace(tmp_path):
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {"value.txt": "42\n"},
    )

    async with SandboxBinding(store, snapshot) as binding:
        sandbox = binding.create_sandbox()

        assert sandbox.workspace == binding.workspace
        assert Path(sandbox.workspace, "value.txt").read_text() == "42\n"


@pytest.mark.asyncio
async def test_binding_applies_a_prior_delta_to_a_fresh_projection(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {"value.txt": "before\n"},
    )

    async with SandboxBinding(store, snapshot) as first:
        (first.workspace / "value.txt").write_text("after\n")
        (first.workspace / "new.txt").write_text("new\n")
        delta = await first.export_delta("workflows/wf-1/workspace_deltas/step-1")

    restored = await store.load_delta(delta.manifest_blob_path)
    async with SandboxBinding(store, snapshot) as second:
        await second.apply_delta(restored)

        assert (second.workspace / "value.txt").read_text() == "after\n"
        assert (second.workspace / "new.txt").read_text() == "new\n"


@pytest.mark.asyncio
async def test_binding_rejects_conflicting_parallel_deltas(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {"value.txt": "before\n"},
    )
    deltas = []
    for index, value in enumerate(("left\n", "right\n"), 1):
        async with SandboxBinding(store, snapshot) as branch:
            (branch.workspace / "value.txt").write_text(value)
            deltas.append(await branch.export_delta(f"workflows/wf/branch-{index}"))

    async with SandboxBinding(store, snapshot) as merged:
        with pytest.raises(WorkspaceDeltaConflict, match="value.txt"):
            await merged.apply_deltas(deltas)


@pytest.mark.asyncio
async def test_empty_delta_does_not_persist_manifest(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {"value.txt": "same\n"},
    )

    async with SandboxBinding(store, snapshot) as binding:
        delta = await binding.export_delta("workflows/wf/unchanged")

    assert delta.manifest_blob_path == ""
    assert await blobs.list("workflows/wf/unchanged") == []


@pytest.mark.asyncio
async def test_delta_ignores_build_outputs_without_deleting_tracked_files(tmp_path):
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    snapshot = await store.capture(
        SourceRef(provider="archive", locator="fixture", revision="main"),
        "commit-1",
        {"src/main.rs": "fn main() {}\n", "target/tracked.txt": "tracked\n"},
    )

    async with SandboxBinding(store, snapshot) as binding:
        (binding.workspace / "target/new.bin").write_bytes(b"build output")
        delta = await binding.export_delta("workflows/wf/build")

    assert delta.added == ()
    assert delta.modified == ()
    assert delta.deleted == ()