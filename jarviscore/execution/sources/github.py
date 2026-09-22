"""GitHub repository snapshots fetched through the Nexus credential boundary."""

from __future__ import annotations

import asyncio
import base64
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import quote

from jarviscore.execution.sources.base import (
    SourceAdapterError,
    SourceContractError,
    SourceIntegrityError,
)
from jarviscore.execution.workspace import BlobSnapshotStore, SourceRef, SourceSnapshot

NexusCall = Callable[..., Awaitable[dict[str, Any]]]


class SnapshotLimitExceeded(SourceAdapterError):
    """A provider snapshot exceeded explicitly configured materialization limits."""


class GitHubSourceRequestError(SourceAdapterError):
    """A GitHub source request failed without inferring cause from HTTP status."""

    def __init__(self, status_code: int | None, detail: str):
        self.status_code = status_code
        self.detail = detail[:500]
        super().__init__(
            f"GitHub source request failed ({status_code}): {self.detail}"
        )


@dataclass(frozen=True)
class SnapshotLimits:
    max_files: int = 5_000
    max_total_bytes: int = 100 * 1024 * 1024
    max_file_bytes: int = 10 * 1024 * 1024
    concurrency: int = 8


class GitHubRepositorySource:
    """Resolve a GitHub ref and persist its file tree as a generic snapshot."""

    api_base = "https://api.github.com"

    def __init__(
        self,
        nexus_call: NexusCall,
        snapshot_store: BlobSnapshotStore,
        *,
        limits: SnapshotLimits | None = None,
    ):
        self.nexus_call = nexus_call
        self.snapshot_store = snapshot_store
        self.limits = limits or SnapshotLimits()

    async def capture(self, source: SourceRef) -> SourceSnapshot:
        if source.provider != "github":
            raise SourceContractError(
                f"GitHubRepositorySource cannot capture {source.provider!r}"
            )
        try:
            owner, repo = source.locator.split("/", 1)
        except ValueError as exc:
            raise SourceContractError(
                "GitHub source locator must be 'owner/repository'"
            ) from exc
        component = re.compile(r"^[A-Za-z0-9_.-]+$")
        if (
            owner in {".", ".."}
            or repo in {".", ".."}
            or not component.fullmatch(owner)
            or not component.fullmatch(repo)
        ):
            raise SourceContractError(
                "GitHub owner and repository contain unsupported characters"
            )
        repository = await self._get(f"/repos/{quote(owner)}/{quote(repo)}")
        default_branch = repository.get("default_branch")
        if not source.revision and not isinstance(default_branch, str):
            raise SourceContractError("GitHub repository response omitted default_branch")
        requested_ref = source.revision or default_branch
        commit = await self._get(
            f"/repos/{quote(owner)}/{quote(repo)}/commits/{quote(requested_ref, safe='')}"
        )
        resolved_revision = commit.get("sha")
        if not isinstance(resolved_revision, str) or not resolved_revision:
            raise SourceContractError("GitHub commit response omitted sha")
        snapshot_source = SourceRef(
            provider="github",
            locator=f"{owner}/{repo}",
            revision=requested_ref,
        )
        cached = await self.snapshot_store.find(snapshot_source, resolved_revision)
        if cached is not None:
            self._check_limits(cached.entries)
            try:
                await self.snapshot_store.validate(cached)
            except Exception as exc:
                raise SourceIntegrityError(
                    f"Cached GitHub snapshot failed integrity validation: {exc}"
                ) from exc
            return cached
        tree = await self._get(
            f"/repos/{quote(owner)}/{quote(repo)}/git/trees/{resolved_revision}",
            params={"recursive": "1"},
        )
        if tree.get("truncated"):
            raise SnapshotLimitExceeded(
                "GitHub truncated the recursive tree; use a sparse or paginated source adapter"
            )
        blobs = [entry for entry in tree.get("tree", []) if entry.get("type") == "blob"]
        self._check_limits(blobs)

        semaphore = asyncio.Semaphore(self.limits.concurrency)

        async def fetch(entry):
            async with semaphore:
                blob = await self._get(
                    f"/repos/{quote(owner)}/{quote(repo)}/git/blobs/{entry['sha']}"
                )
            if blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
                raise SourceIntegrityError(
                    f"GitHub returned unsupported blob encoding for {entry['path']}"
                )
            encoded = "".join(blob["content"].split())
            try:
                payload = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise SourceIntegrityError(
                    f"GitHub returned invalid base64 for {entry['path']}"
                ) from exc
            if len(payload) != int(entry.get("size") or len(payload)):
                raise SourceIntegrityError(
                    f"GitHub blob size mismatch for {entry['path']}"
                )
            return entry["path"], payload, entry.get("mode") == "100755"

        async def files():
            for offset in range(0, len(blobs), self.limits.concurrency):
                batch = blobs[offset:offset + self.limits.concurrency]
                for item in await asyncio.gather(*(fetch(entry) for entry in batch)):
                    yield item

        return await self.snapshot_store.capture_entries(
            snapshot_source,
            resolved_revision,
            files(),
        )

    def _check_limits(self, entries) -> None:
        def value(entry, name):
            return getattr(entry, name) if hasattr(entry, name) else entry.get(name)

        total_bytes = sum(int(value(entry, "size") or 0) for entry in entries)
        if len(entries) > self.limits.max_files:
            raise SnapshotLimitExceeded(
                f"Repository has {len(entries)} files; limit is {self.limits.max_files}"
            )
        if total_bytes > self.limits.max_total_bytes:
            raise SnapshotLimitExceeded(
                f"Repository has {total_bytes} bytes; limit is {self.limits.max_total_bytes}"
            )
        oversized = [
            value(entry, "path") for entry in entries
            if int(value(entry, "size") or 0) > self.limits.max_file_bytes
        ]
        if oversized:
            raise SnapshotLimitExceeded(
                f"Repository files exceed the per-file limit: {oversized[:5]}"
            )

    async def _get(self, path: str, **kwargs) -> Any:
        response = await self.nexus_call(
            "GET",
            f"{self.api_base}{path}",
            headers={"Accept": "application/vnd.github+json"},
            **kwargs,
        )
        if not isinstance(response, dict):
            raise SourceContractError("Nexus GitHub call returned a non-object response")
        if not response.get("ok"):
            raise GitHubSourceRequestError(
                response.get("status_code"), str(response.get("body") or "")
            )
        payload = response.get("json")
        if not isinstance(payload, dict):
            raise SourceContractError("GitHub source response omitted a JSON object")
        return payload