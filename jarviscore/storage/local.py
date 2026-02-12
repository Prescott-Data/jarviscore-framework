"""
Local filesystem blob storage implementation.

Stores files under a configurable base path (default: ./blob_storage).
"""

import logging
import os
from typing import List, Optional, Union

from .base import BlobStorage

logger = logging.getLogger(__name__)


class LocalBlobStorage(BlobStorage):
    """Blob storage backed by local filesystem."""

    def __init__(self, base_path: str = "./blob_storage"):
        self.base_path = os.path.abspath(base_path)
        os.makedirs(self.base_path, exist_ok=True)
        logger.info(f"LocalBlobStorage initialized: {self.base_path}")

    def _full_path(self, path: str) -> str:
        """Resolve relative path to absolute, preventing directory traversal."""
        full = os.path.normpath(os.path.join(self.base_path, path))
        if not full.startswith(self.base_path):
            raise ValueError(f"Path traversal detected: {path}")
        return full

    async def save(self, path: str, content: Union[str, bytes]) -> str:
        full_path = self._full_path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        mode = "wb" if isinstance(content, bytes) else "w"
        encoding = None if isinstance(content, bytes) else "utf-8"

        with open(full_path, mode, encoding=encoding) as f:
            f.write(content)

        logger.debug(f"Saved: {path} ({len(content)} {'bytes' if isinstance(content, bytes) else 'chars'})")
        return path

    async def read(self, path: str) -> Optional[Union[str, bytes]]:
        full_path = self._full_path(path)

        if not os.path.exists(full_path):
            return None

        # Try text first, fall back to binary
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(full_path, "rb") as f:
                return f.read()

    async def list(self, prefix: str) -> List[str]:
        full_prefix = self._full_path(prefix)
        results = []

        # If prefix is a directory, list its contents recursively
        search_dir = full_prefix if os.path.isdir(full_prefix) else os.path.dirname(full_prefix)

        if not os.path.exists(search_dir):
            return results

        for root, _dirs, files in os.walk(search_dir):
            for filename in files:
                abs_path = os.path.join(root, filename)
                rel_path = os.path.relpath(abs_path, self.base_path)
                # Normalize to forward slashes
                rel_path = rel_path.replace(os.sep, "/")
                if rel_path.startswith(prefix):
                    results.append(rel_path)

        return sorted(results)

    async def delete(self, path: str) -> bool:
        full_path = self._full_path(path)

        if not os.path.exists(full_path):
            return False

        os.remove(full_path)
        logger.debug(f"Deleted: {path}")

        # Clean up empty parent directories
        parent = os.path.dirname(full_path)
        while parent != self.base_path:
            try:
                os.rmdir(parent)  # Only removes if empty
                parent = os.path.dirname(parent)
            except OSError:
                break

        return True
