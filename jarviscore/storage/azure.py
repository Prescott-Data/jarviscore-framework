"""
Azure Blob Storage implementation.
"""

import logging
from typing import List, Optional, Union

from azure.storage.blob import BlobServiceClient

from .base import BlobStorage

logger = logging.getLogger(__name__)


class AzureBlobStorage(BlobStorage):
    """Blob storage backed by Azure Blob Storage."""

    def __init__(self, connection_string: str = None,
                 container_name: str = "jarviscore"):
        if not connection_string:
            raise ValueError(
                "AZURE_STORAGE_CONNECTION_STRING is required for Azure storage"
            )

        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._container_name = container_name

        # Ensure container exists
        try:
            self._container = self._client.get_container_client(container_name)
            self._container.get_container_properties()
        except Exception:
            self._container = self._client.create_container(container_name)

        logger.info(f"AzureBlobStorage initialized: container={container_name}")

    async def save(self, path: str, content: Union[str, bytes]) -> str:
        blob_client = self._container.get_blob_client(path)

        data = content.encode("utf-8") if isinstance(content, str) else content
        blob_client.upload_blob(data, overwrite=True)

        logger.debug(f"Saved to Azure: {path} ({len(data)} bytes)")
        return path

    async def read(self, path: str) -> Optional[Union[str, bytes]]:
        blob_client = self._container.get_blob_client(path)

        try:
            download = blob_client.download_blob()
            data = download.readall()
        except Exception:
            return None

        # Try decode as text
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data

    async def list(self, prefix: str) -> List[str]:
        results = []
        blobs = self._container.list_blobs(name_starts_with=prefix)
        for blob in blobs:
            results.append(blob.name)
        return sorted(results)

    async def delete(self, path: str) -> bool:
        blob_client = self._container.get_blob_client(path)

        try:
            blob_client.delete_blob()
            logger.debug(f"Deleted from Azure: {path}")
            return True
        except Exception:
            return False
