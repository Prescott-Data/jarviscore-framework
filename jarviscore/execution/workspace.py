"""Blob-backed source snapshots projected into ephemeral execution workspaces."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from collections.abc import AsyncIterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from jarviscore.storage import BlobStorage


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Workspace paths must be safe relative paths: {value!r}")
    return path


def _bytes(content: str | bytes) -> bytes:
    return content.encode("utf-8") if isinstance(content, str) else content


@dataclass(frozen=True)
class SourceRef:
    """Identity of source material before it is projected into a workspace."""

    provider: str
    locator: str
    revision: str


@dataclass(frozen=True)
class SnapshotEntry:
    """One immutable file in a source snapshot."""

    path: str
    blob_path: str
    sha256: str
    size: int
    executable: bool = False


@dataclass(frozen=True)
class SourceSnapshot:
    """An immutable path manifest whose file bytes live in BlobStorage."""

    snapshot_id: str
    source: SourceRef
    resolved_revision: str
    entries: tuple[SnapshotEntry, ...]
    manifest_blob_path: str


@dataclass(frozen=True)
class WorkspaceDelta:
    """The durable copy-on-write difference from one source snapshot."""

    snapshot_id: str
    added: tuple[SnapshotEntry, ...]
    modified: tuple[SnapshotEntry, ...]
    deleted: tuple[str, ...]
    manifest_blob_path: str
    delta_id: str = ""


class WorkspaceDeltaConflict(RuntimeError):
    """Independent workspace branches changed the same path incompatibly."""


class BlobSnapshotStore:
    """Persist source manifests and content-addressed file bytes in BlobStorage."""

    def __init__(self, blob_storage: BlobStorage, prefix: str = "source_snapshots"):
        self.blob_storage = blob_storage
        self.prefix = prefix.strip("/")

    def _reference_path(self, source: SourceRef, resolved_revision: str) -> str:
        identity = json.dumps(
            {"source": asdict(source), "resolved_revision": resolved_revision},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return f"{self.prefix}/references/{digest}.json"

    @staticmethod
    def _delta_id(delta: WorkspaceDelta) -> str:
        identity = json.dumps({
            "snapshot_id": delta.snapshot_id,
            "added": [asdict(entry) for entry in delta.added],
            "modified": [asdict(entry) for entry in delta.modified],
            "deleted": list(delta.deleted),
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    async def find(
        self, source: SourceRef, resolved_revision: str
    ) -> SourceSnapshot | None:
        raw = await self.blob_storage.read(
            self._reference_path(source, resolved_revision)
        )
        if raw is None:
            return None
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return await self.load(data["manifest_blob_path"])

    async def capture(
        self,
        source: SourceRef,
        resolved_revision: str,
        files: Mapping[str, str | bytes],
        *,
        executable_paths: set[str] | None = None,
    ) -> SourceSnapshot:
        executable_paths = executable_paths or set()
        async def entries():
            for path, content in files.items():
                yield path, content, path in executable_paths

        return await self.capture_entries(source, resolved_revision, entries())

    async def capture_entries(
        self,
        source: SourceRef,
        resolved_revision: str,
        files: AsyncIterable[tuple[str, str | bytes, bool]],
    ) -> SourceSnapshot:
        entries = []
        seen_paths: set[str] = set()
        async for raw_path, content, executable in files:
            path = _safe_relative_path(raw_path).as_posix()
            if path in seen_paths:
                raise ValueError(f"Duplicate workspace path: {path!r}")
            parents = set(PurePosixPath(path).parents) - {PurePosixPath(".")}
            if any(parent.as_posix() in seen_paths for parent in parents):
                raise ValueError(f"Workspace path conflicts with a file parent: {path!r}")
            if any(existing.startswith(f"{path}/") for existing in seen_paths):
                raise ValueError(f"Workspace file conflicts with an existing directory: {path!r}")
            seen_paths.add(path)
            payload = _bytes(content)
            digest = hashlib.sha256(payload).hexdigest()
            blob_path = f"{self.prefix}/objects/{digest}"
            existing = await self.blob_storage.read(blob_path)
            if existing is None or _bytes(existing) != payload:
                await self.blob_storage.save(blob_path, payload)
            entries.append(SnapshotEntry(
                path=path,
                blob_path=blob_path,
                sha256=digest,
                size=len(payload),
                executable=executable,
            ))

            entries.sort(key=lambda entry: entry.path)

        identity = json.dumps({
            "source": asdict(source),
            "resolved_revision": resolved_revision,
            "entries": [asdict(entry) for entry in entries],
        }, sort_keys=True, separators=(",", ":"))
        snapshot_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        manifest_path = f"{self.prefix}/manifests/{snapshot_id}.json"
        snapshot = SourceSnapshot(
            snapshot_id=snapshot_id,
            source=source,
            resolved_revision=resolved_revision,
            entries=tuple(entries),
            manifest_blob_path=manifest_path,
        )
        await self.blob_storage.save(manifest_path, json.dumps(
            {
                **asdict(snapshot),
                "entries": [asdict(entry) for entry in snapshot.entries],
            },
            sort_keys=True,
        ))
        await self.blob_storage.save(
            self._reference_path(source, resolved_revision),
            json.dumps({"manifest_blob_path": manifest_path}, sort_keys=True),
        )
        return snapshot

    async def load(self, manifest_blob_path: str) -> SourceSnapshot:
        raw = await self.blob_storage.read(manifest_blob_path)
        if raw is None:
            raise FileNotFoundError(manifest_blob_path)
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        return SourceSnapshot(
            snapshot_id=data["snapshot_id"],
            source=SourceRef(**data["source"]),
            resolved_revision=data["resolved_revision"],
            entries=tuple(SnapshotEntry(**entry) for entry in data["entries"]),
            manifest_blob_path=data["manifest_blob_path"],
        )

    async def load_delta(self, manifest_blob_path: str) -> WorkspaceDelta:
        raw = await self.blob_storage.read(manifest_blob_path)
        if raw is None:
            raise FileNotFoundError(manifest_blob_path)
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        delta = WorkspaceDelta(
            snapshot_id=data["snapshot_id"],
            added=tuple(SnapshotEntry(**entry) for entry in data["added"]),
            modified=tuple(SnapshotEntry(**entry) for entry in data["modified"]),
            deleted=tuple(data["deleted"]),
            manifest_blob_path=data["manifest_blob_path"],
            delta_id=data.get("delta_id", ""),
        )
        self.validate_delta(delta, requested_manifest_path=manifest_blob_path)
        return delta

    def validate_delta(
        self,
        delta: WorkspaceDelta,
        *,
        requested_manifest_path: str | None = None,
    ) -> None:
        """Verify a delta's canonical identity is bound to its manifest path."""
        expected_id = self._delta_id(delta)
        if delta.delta_id != expected_id:
            raise ValueError("Workspace delta identity does not match its manifest")
        expected_suffix = f"/manifests/{expected_id}.json"
        if not delta.manifest_blob_path.endswith(expected_suffix):
            raise ValueError("Workspace delta manifest path does not match its identity")
        if (
            requested_manifest_path is not None
            and delta.manifest_blob_path != requested_manifest_path
        ):
            raise ValueError("Workspace delta manifest redirected to another path")
        seen_paths: set[str] = set()
        for entry in (*delta.added, *delta.modified):
            path = _safe_relative_path(entry.path).as_posix()
            if path in seen_paths:
                raise ValueError(f"Duplicate workspace delta path: {path!r}")
            seen_paths.add(path)
        for raw_path in delta.deleted:
            path = _safe_relative_path(raw_path).as_posix()
            if path in seen_paths:
                raise ValueError(f"Conflicting workspace delta path: {path!r}")
            seen_paths.add(path)

    async def validate(self, snapshot: SourceSnapshot) -> None:
        """Verify every persisted blob against the immutable manifest."""
        identity = json.dumps({
            "source": asdict(snapshot.source),
            "resolved_revision": snapshot.resolved_revision,
            "entries": [asdict(entry) for entry in snapshot.entries],
        }, sort_keys=True, separators=(",", ":"))
        expected_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if snapshot.snapshot_id != expected_id:
            raise ValueError("Snapshot identity does not match its canonical manifest")
        expected_manifest = f"{self.prefix}/manifests/{expected_id}.json"
        if snapshot.manifest_blob_path != expected_manifest:
            raise ValueError("Snapshot manifest path does not match its identity")
        seen_paths: set[str] = set()
        for entry in snapshot.entries:
            path = _safe_relative_path(entry.path).as_posix()
            if path in seen_paths:
                raise ValueError(f"Duplicate workspace path: {path!r}")
            seen_paths.add(path)
            payload = await self.blob_storage.read(entry.blob_path)
            if payload is None:
                raise FileNotFoundError(entry.blob_path)
            payload = _bytes(payload)
            if len(payload) != entry.size:
                raise ValueError(
                    f"Snapshot blob failed integrity validation (size): {entry.path}"
                )
            if hashlib.sha256(payload).hexdigest() != entry.sha256:
                raise ValueError(
                    f"Snapshot blob failed integrity validation (hash): {entry.path}"
                )

    async def materialize(self, snapshot: SourceSnapshot, destination: Path) -> None:
        await self.validate(snapshot)
        destination.mkdir(parents=True, exist_ok=False)
        for entry in snapshot.entries:
            relative = _safe_relative_path(entry.path)
            target = destination.joinpath(*relative.parts)
            payload = await self.blob_storage.read(entry.blob_path)
            if payload is None:
                raise FileNotFoundError(entry.blob_path)
            payload = _bytes(payload)
            if len(payload) != entry.size or hashlib.sha256(payload).hexdigest() != entry.sha256:
                raise ValueError(f"Snapshot blob failed integrity validation: {entry.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            if entry.executable:
                target.chmod(target.stat().st_mode | 0o100)


class SandboxBinding:
    """Ephemeral filesystem projection of a durable source snapshot."""

    def __init__(
        self,
        store: BlobSnapshotStore,
        snapshot: SourceSnapshot,
        *,
        temporary_root: Path | None = None,
        cleanup: bool = True,
    ):
        self.store = store
        self.snapshot = snapshot
        self._requested_root = temporary_root
        self.cleanup = cleanup
        self.root: Path | None = None
        self.workspace: Path | None = None

    async def __aenter__(self) -> "SandboxBinding":
        if self._requested_root is not None and (
            self._requested_root.exists() or self._requested_root.is_symlink()
        ):
            raise FileExistsError(
                f"Workspace binding root must not already exist: {self._requested_root}"
            )
        if self._requested_root is not None:
            requested = self._requested_root.expanduser().absolute()
            if any(parent.is_symlink() for parent in requested.parents):
                raise ValueError(
                    f"Workspace binding root has a symlinked parent: {self._requested_root}"
                )
        self.root = self._requested_root or Path(
            tempfile.mkdtemp(prefix="jarviscore-workspace-")
        )
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".jarviscore-binding.json").write_text(json.dumps({
            "pid": __import__("os").getpid(),
            "created_at": time.time(),
            "snapshot_id": self.snapshot.snapshot_id,
        }, sort_keys=True))
        self.workspace = self.root / "workspace"
        try:
            await self.store.materialize(self.snapshot, self.workspace)
        except BaseException:
            if self.cleanup and self.root is not None:
                shutil.rmtree(self.root, ignore_errors=True)
            raise
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self.cleanup and self.root is not None:
            shutil.rmtree(self.root, ignore_errors=True)

    def create_sandbox(self, **kwargs):
        if self.workspace is None:
            raise RuntimeError("Enter the SandboxBinding before creating a sandbox")
        from jarviscore.execution.coder_sandbox import create_coder_sandbox

        return create_coder_sandbox(workspace_dir=self.workspace, **kwargs)

    async def apply_delta(self, delta: WorkspaceDelta) -> None:
        if self.workspace is None:
            raise RuntimeError("Enter the SandboxBinding before applying a delta")
        self.store.validate_delta(delta)
        if delta.snapshot_id != self.snapshot.snapshot_id:
            raise ValueError("Workspace delta belongs to a different source snapshot")
        for path in delta.deleted:
            target = self.workspace.joinpath(*_safe_relative_path(path).parts)
            if target.exists():
                target.unlink()
        for entry in (*delta.added, *delta.modified):
            target = self.workspace.joinpath(*_safe_relative_path(entry.path).parts)
            payload = await self.store.blob_storage.read(entry.blob_path)
            if payload is None:
                raise FileNotFoundError(entry.blob_path)
            payload = _bytes(payload)
            if len(payload) != entry.size or hashlib.sha256(payload).hexdigest() != entry.sha256:
                raise ValueError(f"Workspace delta failed integrity validation: {entry.path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            if entry.executable:
                target.chmod(target.stat().st_mode | 0o100)

    async def apply_deltas(self, deltas: list[WorkspaceDelta]) -> None:
        """Apply compatible dependency deltas and reject ambiguous merges."""
        decisions: dict[str, tuple[str, str | None]] = {}
        for delta in deltas:
            if delta.snapshot_id != self.snapshot.snapshot_id:
                raise ValueError("Workspace delta belongs to a different source snapshot")
            for path in delta.deleted:
                decision = ("deleted", None)
                if path in decisions and decisions[path] != decision:
                    raise WorkspaceDeltaConflict(f"Conflicting workspace deltas for {path!r}")
                decisions[path] = decision
            for entry in (*delta.added, *delta.modified):
                decision = ("content", entry.sha256)
                if entry.path in decisions and decisions[entry.path] != decision:
                    raise WorkspaceDeltaConflict(
                        f"Conflicting workspace deltas for {entry.path!r}"
                    )
                decisions[entry.path] = decision
        for delta in deltas:
            await self.apply_delta(delta)

    async def export_delta(
        self,
        prefix: str,
        *,
        ignored_names: tuple[str, ...] = (
            ".git",
            ".tmp",
            ".venv",
            "__pycache__",
            "node_modules",
            "output",
            "target",
        ),
    ) -> WorkspaceDelta:
        if self.workspace is None:
            raise RuntimeError("Enter the SandboxBinding before exporting a delta")
        baseline = {entry.path: entry for entry in self.snapshot.entries}
        ignored = set(ignored_names)

        def is_ignored(path: str) -> bool:
            return bool(set(PurePosixPath(path).parts).intersection(ignored))

        current = {}
        for candidate in sorted(self.workspace.rglob("*")):
            if candidate.is_symlink():
                raise ValueError(f"Workspace deltas cannot contain symlinks: {candidate}")
            if not candidate.is_file():
                continue
            path = candidate.relative_to(self.workspace).as_posix()
            if is_ignored(path):
                continue
            payload = candidate.read_bytes()
            digest = hashlib.sha256(payload).hexdigest()
            current[path] = (candidate, payload, digest)

        delta_prefix = prefix.strip("/")
        added = []
        modified = []
        for path, (candidate, payload, digest) in current.items():
            previous = baseline.get(path)
            if previous is not None and previous.sha256 == digest:
                continue
            blob_path = f"{delta_prefix}/files/{path}"
            await self.store.blob_storage.save(blob_path, payload)
            entry = SnapshotEntry(
                path=path,
                blob_path=blob_path,
                sha256=digest,
                size=len(payload),
                executable=bool(candidate.stat().st_mode & 0o100),
            )
            (modified if previous is not None else added).append(entry)

        deleted = tuple(sorted(
            path for path in set(baseline) - set(current) if not is_ignored(path)
        ))
        has_changes = bool(added or modified or deleted)
        provisional = WorkspaceDelta(
            snapshot_id=self.snapshot.snapshot_id,
            added=tuple(added),
            modified=tuple(modified),
            deleted=deleted,
            manifest_blob_path="",
        )
        delta_id = self.store._delta_id(provisional) if has_changes else ""
        manifest_path = (
            f"{delta_prefix}/manifests/{delta_id}.json" if has_changes else ""
        )
        delta = WorkspaceDelta(
            snapshot_id=provisional.snapshot_id,
            added=provisional.added,
            modified=provisional.modified,
            deleted=provisional.deleted,
            manifest_blob_path=manifest_path,
            delta_id=delta_id,
        )
        if has_changes:
            await self.store.blob_storage.save(manifest_path, json.dumps(
                {
                    **asdict(delta),
                    "added": [asdict(entry) for entry in delta.added],
                    "modified": [asdict(entry) for entry in delta.modified],
                },
                sort_keys=True,
            ))
        return delta


def cleanup_stale_bindings(
    base_directory: Path | None = None,
    *,
    minimum_age_seconds: float = 60.0,
) -> list[Path]:
    """Remove marked workspace roots whose owning process no longer exists."""
    import os

    base = base_directory or Path(tempfile.gettempdir())
    removed = []
    now = time.time()
    for root in base.glob("jarviscore-workspace-*"):
        marker = root / ".jarviscore-binding.json"
        if not root.is_dir() or not marker.is_file():
            continue
        try:
            data = json.loads(marker.read_text())
            pid = int(data["pid"])
            created_at = float(data["created_at"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        if now - created_at < minimum_age_seconds:
            continue
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            shutil.rmtree(root, ignore_errors=True)
            if not root.exists():
                removed.append(root)
        except PermissionError:
            continue
    return removed