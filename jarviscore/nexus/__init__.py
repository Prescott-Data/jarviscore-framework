"""
Nexus Protocol — Client-side integration with Dromos Gateway.

Provides authenticated access to external services via:
- NexusClient: HTTP client for Dromos Gateway REST API
- LifecycleMonitor: Background connection health monitoring
- Models: Pydantic models for connection/strategy data
"""

from .models import ConnectionRequest, DynamicStrategy, ConnectionStatus
from .client import NexusClient
from .lifecycle import LifecycleMonitor

__all__ = [
    "ConnectionRequest",
    "DynamicStrategy",
    "ConnectionStatus",
    "NexusClient",
    "LifecycleMonitor",
]
