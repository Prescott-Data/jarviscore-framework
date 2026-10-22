"""
Nexus Protocol — Client-side integration with the Nexus Gateway.

The Nexus Framework is a provider-agnostic OAuth 2.0 / OIDC integration layer.
JarvisCore communicates exclusively with the Nexus Gateway — never with
the Broker or providers directly.

Components:
- NexusClient: HTTP client for the Nexus Gateway REST API
- LifecycleMonitor: Background connection health monitoring
- Models: Pydantic models for connection/strategy data
"""

from importlib import import_module
from typing import TYPE_CHECKING

# Resolved on first access (PEP 562) so importing one nexus submodule stays cheap.
_LAZY = {
    "ConnectionRequest": "models",
    "DynamicStrategy": "models",
    "ConnectionStatus": "models",
    "NexusClient": "client",
    "LifecycleMonitor": "lifecycle",
    "NexusCallProxy": "call_proxy",
    "NexusLocalStore": "store",
    "get_store": "store",
    **dict.fromkeys(
        ["PROVIDER_CATALOG", "get_provider", "get_scopes", "get_auth_type", "list_providers"],
        "providers"),
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{_LAZY[name]}", __name__), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))


if TYPE_CHECKING:
    from .models import ConnectionRequest, DynamicStrategy, ConnectionStatus
    from .client import NexusClient
    from .lifecycle import LifecycleMonitor
    from .call_proxy import NexusCallProxy
    from .store import NexusLocalStore, get_store
    from .providers import (
        PROVIDER_CATALOG,
        get_provider,
        get_scopes,
        get_auth_type,
        list_providers,
    )

__all__ = [
    "ConnectionRequest",
    "DynamicStrategy",
    "ConnectionStatus",
    "NexusClient",
    "LifecycleMonitor",
    "NexusCallProxy",
    "NexusLocalStore",
    "get_store",
    "PROVIDER_CATALOG",
    "get_provider",
    "get_scopes",
    "get_auth_type",
    "list_providers",
]
