"""Provider-neutral contract for durable workspace source adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarviscore.execution.workspace import BlobSnapshotStore, SourceRef, SourceSnapshot


class SourceAdapterError(RuntimeError):
    """Base failure while resolving or validating a workspace source."""


class SourceContractError(SourceAdapterError):
    """A source request or adapter result violated the snapshot contract."""


class SourceIntegrityError(SourceAdapterError):
    """A persisted source manifest or blob failed integrity validation."""


@runtime_checkable
class SourceAdapter(Protocol):
    """Resolve source identity into a BlobStorage-backed immutable snapshot."""

    async def capture(self, source: SourceRef) -> SourceSnapshot: ...


async def capture_source(
    adapter: SourceAdapter,
    store: BlobSnapshotStore,
    source: SourceRef,
) -> SourceSnapshot:
    """Capture and verify one adapter result before workflow planning."""
    if not source.provider or not source.locator:
        raise SourceContractError("Workspace source requires provider and locator")
    snapshot = await adapter.capture(source)
    if not isinstance(snapshot, SourceSnapshot):
        raise SourceContractError("Source adapter must return SourceSnapshot")
    if snapshot.source.provider != source.provider:
        raise SourceContractError("Source adapter changed the requested provider")
    if snapshot.source.locator != source.locator:
        raise SourceContractError("Source adapter changed the requested locator")
    if source.revision and snapshot.source.revision != source.revision:
        raise SourceContractError("Source adapter changed the requested revision")
    if not snapshot.snapshot_id or not snapshot.resolved_revision:
        raise SourceContractError(
            "Source adapter must return snapshot and resolved revision identities"
        )
    try:
        persisted = await store.load(snapshot.manifest_blob_path)
        if persisted != snapshot:
            raise SourceIntegrityError(
                "Source adapter result does not match its persisted manifest"
            )
        await store.validate(snapshot)
    except SourceIntegrityError:
        raise
    except Exception as exc:
        raise SourceIntegrityError(
            f"Source snapshot failed persisted integrity validation: {exc}"
        ) from exc
    return snapshot