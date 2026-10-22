"""
BlobStorage in Redis: one Redis is all a team needs across machines.

Workspaces and rooms keep file contents in BlobStorage. Local storage is per
machine, so people and agents on different machines otherwise need a cloud
store. With ``STORAGE_BACKEND=redis`` the contents live in the Redis the mesh
already uses (``REDIS_URL``). Workspace blobs are content-addressed, so a file
is stored once however many versions or steps include it.

Redis keeps data in memory: suited to documents, plans, code and modest data,
not large media or datasets. Writes over ``max_blob_bytes`` are refused.
"""

from __future__ import annotations

from typing import List, Optional, Union

from jarviscore.storage.base import BlobStorage

DEFAULT_MAX_BLOB_BYTES = 32 * 1024 * 1024


class RedisBlobStorage(BlobStorage):
    def __init__(self, url: str, *, prefix: str = "blob:",
                 max_blob_bytes: int = DEFAULT_MAX_BLOB_BYTES, client=None):
        if client is None:
            import redis

            # Bytes in, bytes out: blobs are not always text.
            client = redis.Redis.from_url(url, decode_responses=False)
        self._redis = client
        self._prefix = prefix
        self.max_blob_bytes = max_blob_bytes

    def _key(self, path: str) -> str:
        parts = path.replace("\\", "/").split("/")
        if not path or path.startswith("/") or any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"Unsafe blob path: {path!r}")
        return self._prefix + path

    async def save(self, path: str, content: Union[str, bytes]) -> str:
        payload = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        if len(payload) > self.max_blob_bytes:
            raise ValueError(
                f"{path} is {len(payload)} bytes; Redis blob storage takes at most "
                f"{self.max_blob_bytes}. Use STORAGE_BACKEND=azure for large files."
            )
        self._redis.set(self._key(path), payload)
        return path

    async def read(self, path: str) -> Optional[Union[str, bytes]]:
        payload = self._redis.get(self._key(path))
        if payload is None:
            return None
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload

    async def list(self, prefix: str) -> List[str]:
        pattern = (self._prefix + prefix).replace("*", r"\*").replace("?", r"\?") + "*"
        found = [
            key.decode("utf-8") if isinstance(key, bytes) else key
            for key in self._redis.scan_iter(match=pattern, count=500)
        ]
        return sorted(key[len(self._prefix):] for key in found)

    async def delete(self, path: str) -> bool:
        return bool(self._redis.delete(self._key(path)))

    async def exists(self, path: str) -> bool:
        return bool(self._redis.exists(self._key(path)))

    def has_local_path(self, path: str) -> bool:
        """Every node with the Redis can read every blob."""
        return bool(self._redis.exists(self._key(path)))
