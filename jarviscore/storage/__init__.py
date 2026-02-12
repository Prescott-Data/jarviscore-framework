"""
Storage layer for JarvisCore v1.0.0.

Provides abstract blob storage and Redis context store.

Usage:
    from jarviscore.storage import get_blob_storage, RedisContextStore

    # Blob storage (auto-detects from settings)
    storage = get_blob_storage(settings)
    await storage.save("path/to/file.json", '{"key": "value"}')
    content = await storage.read("path/to/file.json")

    # Redis context store
    redis_store = RedisContextStore(settings)
    redis_store.save_step_output("wf-1", "step-1", output={"result": 42})
"""

from .base import BlobStorage
from .local import LocalBlobStorage
from .redis_store import RedisContextStore

__all__ = [
    "BlobStorage",
    "LocalBlobStorage",
    "RedisContextStore",
    "get_blob_storage",
]


def get_blob_storage(settings=None) -> BlobStorage:
    """
    Factory: create blob storage from settings.

    Args:
        settings: Settings instance or None (uses global settings)

    Returns:
        BlobStorage implementation (Local or Azure)
    """
    if settings is None:
        from jarviscore.config.settings import settings as default_settings
        settings = default_settings

    backend = getattr(settings, "storage_backend", "local")

    if backend == "azure":
        from .azure import AzureBlobStorage
        return AzureBlobStorage(
            connection_string=settings.azure_storage_connection_string,
            container_name=settings.azure_storage_container,
        )

    return LocalBlobStorage(
        base_path=getattr(settings, "storage_base_path", "./blob_storage"),
    )
