---
icon: material/file-code-outline
title: Execution and Evidence API
description: Public source-workspace, artifact-reference, command, and mutation evidence contracts in JarvisCore.
---

# Execution and Evidence API

JarvisCore 1.13 exposes the contracts used to move immutable source, exact
artifacts, and authoritative execution evidence through a Mesh.

## Source workspace types

Import common contracts from `jarviscore`:

```python
from jarviscore import (
    BlobSnapshotStore,
    SandboxBinding,
    SnapshotEntry,
    SourceAdapter,
    SourceRef,
    SourceSnapshot,
    WorkspaceDelta,
    WorkspaceDeltaConflict,
)
```

| Type | Contract |
|---|---|
| `SourceRef` | Provider, locator, and requested revision supplied to an adapter. |
| `SnapshotEntry` | Immutable path, blob location, hash, size, and executable mode. |
| `SourceSnapshot` | Immutable resolved revision and persisted manifest. |
| `WorkspaceDelta` | Added, modified, and deleted paths relative to the source snapshot. |
| `BlobSnapshotStore` | Captures, loads, validates, materializes, and persists snapshot/delta manifests. |
| `SandboxBinding` | Temporary projection of a snapshot plus compatible deltas into a Coder workspace. |
| `SourceAdapter` | Provider-neutral asynchronous source capture protocol. |

Provider implementations and limits are available from `jarviscore.execution`:

```python
from jarviscore.execution import (
    GitHubRepositorySource,
    GitHubSourceRequestError,
    SnapshotLimitExceeded,
    SnapshotLimits,
    capture_source,
)
```

Source contracts fail closed with `SourceAdapterError`, `SourceContractError`,
`SourceIntegrityError`, `SnapshotLimitExceeded`, or the provider-specific error.

## Artifact references

```python
from jarviscore import ArtifactReference, hydrate_artifact_references
```

`ArtifactReference(step_id, path)` identifies an entire direct-dependency output
or a nested value. `hydrate_artifact_references()` resolves those references
before product schema validation. Unknown steps, invalid paths, or literal values
at a required reference path raise `ArtifactReferenceError`.

## Command and mutation evidence

```python
from jarviscore import CommandObservation, WorkspaceMutation
```

`CommandObservation` is projected only from `workspace_run` and contains the
authoritative command, exit code, stdout, stderr, duration, timestamp, and
`tool_receipt_id`.

`WorkspaceMutation` is projected from `workspace_write` or `workspace_edit` and
contains the authoritative path, final hash, byte size, executable mode,
timestamp, and receipt ID. Final Mesh validation additionally requires the cited
hash to exist in the exported cumulative workspace delta.

Applications normally cite only the receipt ID in model output. The framework
hydrates the remaining fields:

```json
{
  "vulnerable_run": {
    "tool_receipt_id": "tool:workflow-id:reproduce:4"
  }
}
```

`hydrate_receipt_evidence()` is public for custom execution boundaries. Missing,
foreign, or incompatible receipts raise `ToolReceiptError`; model-authored
execution facts never override the receipt.

## Workspace mutation tools

`workspace_write` creates or fully replaces a file and therefore requires the
complete final content. `workspace_edit` replaces an inclusive line range in an
existing UTF-8 file. It requires the `sha256` returned by the latest
`workspace_read`; a stale hash returns `status="conflict"` without changing the
file.

Both mutation tools operate only inside the bound copy-on-write workspace and
produce receipts suitable for `WorkspaceMutation` hydration. Across bounded
execution epochs, JarvisCore persists and reapplies the same-step delta so file
state and receipt provenance remain aligned.

See [Source Workspaces](../guides/source-workspaces.md) for configuration and
[Durable Goal Execution](../guides/goal-execution.md) for lifecycle semantics.