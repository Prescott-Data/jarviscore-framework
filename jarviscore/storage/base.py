"""
Abstract BlobStorage interface for JarvisCore.

All storage backends (local filesystem, Azure, S3, etc.) implement this ABC.
Convenience methods are built on the 4 abstract primitives.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Union


class BlobStorage(ABC):
    """Abstract blob storage interface."""

    @abstractmethod
    async def save(self, path: str, content: Union[str, bytes]) -> str:
        """
        Save content to a path.

        Args:
            path: Relative path (e.g., "workflows/wf-1/output.json")
            content: String or bytes to store

        Returns:
            The path where content was saved
        """

    @abstractmethod
    async def read(self, path: str) -> Optional[Union[str, bytes]]:
        """
        Read content from a path.

        Args:
            path: Relative path

        Returns:
            Content as string/bytes, or None if not found
        """

    @abstractmethod
    async def list(self, prefix: str) -> List[str]:
        """
        List paths under a prefix.

        Args:
            prefix: Path prefix (e.g., "workflows/wf-1/")

        Returns:
            List of matching paths
        """

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """
        Delete content at a path.

        Args:
            path: Relative path

        Returns:
            True if deleted, False if not found
        """

    # --- Convenience methods (built on primitives) ---

    async def save_scratchpad(self, workflow_id: str, step_id: str,
                              content: str) -> str:
        """Save a working scratchpad for a step."""
        path = f"workflows/{workflow_id}/scratchpads/{step_id}.md"
        return await self.save(path, content)

    async def read_scratchpad(self, workflow_id: str,
                              step_id: str) -> Optional[str]:
        """Read a working scratchpad."""
        path = f"workflows/{workflow_id}/scratchpads/{step_id}.md"
        result = await self.read(path)
        return result if isinstance(result, str) else None

    async def save_artifact(self, workflow_id: str, step_id: str,
                            filename: str, content: Union[str, bytes]) -> str:
        """Save a step artifact (code, output, etc.)."""
        path = f"workflows/{workflow_id}/artifacts/{step_id}/{filename}"
        return await self.save(path, content)

    async def read_artifact(self, workflow_id: str, step_id: str,
                            filename: str) -> Optional[Union[str, bytes]]:
        """Read a step artifact."""
        path = f"workflows/{workflow_id}/artifacts/{step_id}/{filename}"
        return await self.read(path)

    async def exists(self, path: str) -> bool:
        """Check if a path exists."""
        return await self.read(path) is not None
