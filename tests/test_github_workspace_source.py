import base64

import pytest

from jarviscore.execution.sources import (
    GitHubRepositorySource,
    GitHubSourceRequestError,
    SnapshotLimitExceeded,
    SnapshotLimits,
    SourceContractError,
    SourceIntegrityError,
)
from jarviscore.execution.workspace import BlobSnapshotStore, SandboxBinding, SourceRef
from jarviscore.storage import LocalBlobStorage


class GitHubFixture:
    def __init__(self, tree=None):
        self.tree = tree or [
            {"path": "README.md", "type": "blob", "sha": "blob-1", "size": 6, "mode": "100644"},
            {"path": "bin/run", "type": "blob", "sha": "blob-2", "size": 4, "mode": "100755"},
        ]
        self.calls = []

    async def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/repos/acme/project"):
            payload = {"default_branch": "main"}
        elif url.endswith("/commits/main"):
            payload = {"sha": "commit-1"}
        elif "/git/trees/commit-1" in url:
            payload = {"truncated": False, "tree": self.tree}
        elif url.endswith("/git/blobs/blob-1"):
            encoded = base64.b64encode(b"hello\n").decode()
            payload = {"encoding": "base64", "content": f"{encoded[:4]}\n{encoded[4:]}"}
        elif url.endswith("/git/blobs/blob-2"):
            payload = {"encoding": "base64", "content": base64.b64encode(b"run\n").decode()}
        else:
            return {"ok": False, "status_code": 404, "body": "not found"}
        return {"ok": True, "status_code": 200, "json": payload, "body": ""}


@pytest.mark.asyncio
async def test_github_source_resolves_commit_and_materializes_snapshot(tmp_path):
    github = GitHubFixture()
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    source = GitHubRepositorySource(github, store)

    snapshot = await source.capture(SourceRef("github", "acme/project", ""))

    assert snapshot.resolved_revision == "commit-1"
    assert snapshot.source.locator == "acme/project"
    async with SandboxBinding(store, snapshot) as binding:
        assert (binding.workspace / "README.md").read_text() == "hello\n"
        assert (binding.workspace / "bin/run").read_text() == "run\n"
        assert (binding.workspace / "bin/run").stat().st_mode & 0o100


@pytest.mark.asyncio
async def test_github_source_refuses_repository_over_configured_limits(tmp_path):
    tree = [
        {"path": "one", "type": "blob", "sha": "blob-1", "size": 6, "mode": "100644"},
        {"path": "two", "type": "blob", "sha": "blob-2", "size": 4, "mode": "100644"},
    ]
    source = GitHubRepositorySource(
        GitHubFixture(tree),
        BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs"))),
        limits=SnapshotLimits(max_files=1),
    )

    with pytest.raises(SnapshotLimitExceeded, match="2 files"):
        await source.capture(SourceRef("github", "acme/project", "main"))


@pytest.mark.asyncio
async def test_github_source_preserves_provider_failure(tmp_path):
    async def failed(method, url, **kwargs):
        return {"ok": False, "status_code": 403, "body": "rate limited"}

    source = GitHubRepositorySource(
        failed,
        BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs"))),
    )

    with pytest.raises(GitHubSourceRequestError, match="403.*rate limited") as error:
        await source.capture(SourceRef("github", "acme/project", "main"))

    assert error.value.status_code == 403
    assert error.value.detail == "rate limited"


@pytest.mark.asyncio
async def test_github_source_reuses_cached_snapshot_without_refetching_blobs(tmp_path):
    github = GitHubFixture()
    store = BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs")))
    source = GitHubRepositorySource(github, store)

    first = await source.capture(SourceRef("github", "acme/project", "main"))
    first_blob_calls = len([url for _, url, _ in github.calls if "/git/blobs/" in url])
    second = await source.capture(SourceRef("github", "acme/project", "main"))
    total_blob_calls = len([url for _, url, _ in github.calls if "/git/blobs/" in url])

    assert second == first
    assert total_blob_calls == first_blob_calls


@pytest.mark.asyncio
async def test_github_source_rejects_corrupted_cached_snapshot(tmp_path):
    github = GitHubFixture()
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    source = GitHubRepositorySource(github, store)
    snapshot = await source.capture(SourceRef("github", "acme/project", "main"))
    await blobs.save(snapshot.entries[0].blob_path, b"tampered")

    with pytest.raises(SourceIntegrityError, match="Cached GitHub snapshot"):
        await source.capture(SourceRef("github", "acme/project", "main"))


@pytest.mark.asyncio
async def test_github_source_rejects_cached_snapshot_for_another_source(tmp_path):
    github = GitHubFixture()
    blobs = LocalBlobStorage(str(tmp_path / "blobs"))
    store = BlobSnapshotStore(blobs)
    source = GitHubRepositorySource(github, store)
    requested = SourceRef("github", "acme/project", "main")
    await source.capture(requested)
    foreign = await store.capture(
        SourceRef("github", "other/project", "main"),
        "other-commit",
        {"README.md": "foreign\n"},
    )
    reference_path = store._reference_path(requested, "commit-1")
    await blobs.save(
        reference_path,
        __import__("json").dumps({"manifest_blob_path": foreign.manifest_blob_path}),
    )

    with pytest.raises(SourceIntegrityError, match="identity"):
        await source.capture(requested)


@pytest.mark.asyncio
async def test_github_source_requires_nonnegative_integer_tree_sizes(tmp_path):
    for invalid in (None, "6", -1, True):
        tree = [{
            "path": "README.md", "type": "blob", "sha": "blob-1",
            "size": invalid, "mode": "100644",
        }]
        source = GitHubRepositorySource(
            GitHubFixture(tree),
            BlobSnapshotStore(LocalBlobStorage(str(tmp_path / str(invalid)))),
        )

        with pytest.raises(SourceIntegrityError, match="invalid size"):
            await source.capture(SourceRef("github", "acme/project", "main"))


@pytest.mark.asyncio
async def test_github_source_enforces_limit_against_decoded_blob_size(tmp_path):
    tree = [{
        "path": "README.md", "type": "blob", "sha": "blob-1",
        "size": 4, "mode": "100644",
    }]
    source = GitHubRepositorySource(
        GitHubFixture(tree),
        BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs"))),
        limits=SnapshotLimits(max_file_bytes=5),
    )

    with pytest.raises(SnapshotLimitExceeded, match="per-file"):
        await source.capture(SourceRef("github", "acme/project", "main"))


@pytest.mark.asyncio
async def test_github_source_rejects_invalid_locator(tmp_path):
    source = GitHubRepositorySource(
        GitHubFixture(),
        BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs"))),
    )

    with pytest.raises(SourceContractError, match="unsupported characters"):
        await source.capture(SourceRef("github", "../project", "main"))


@pytest.mark.asyncio
async def test_github_source_rejects_malformed_success_response(tmp_path):
    async def malformed(method, url, **kwargs):
        return {"ok": True, "status_code": 200, "json": None}

    source = GitHubRepositorySource(
        malformed,
        BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs"))),
    )

    with pytest.raises(SourceContractError, match="JSON object"):
        await source.capture(SourceRef("github", "acme/project", "main"))


@pytest.mark.asyncio
async def test_github_source_rejects_blob_size_mismatch(tmp_path):
    tree = [
        {"path": "README.md", "type": "blob", "sha": "blob-1", "size": 99},
    ]
    source = GitHubRepositorySource(
        GitHubFixture(tree),
        BlobSnapshotStore(LocalBlobStorage(str(tmp_path / "blobs"))),
    )

    with pytest.raises(SourceIntegrityError, match="size mismatch"):
        await source.capture(SourceRef("github", "acme/project", "main"))