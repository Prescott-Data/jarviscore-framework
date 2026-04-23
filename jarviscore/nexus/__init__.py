"""
Nexus Protocol — Client-side integration with the Nexus Gateway.

The Nexus Framework (github.com/Prescott-Data/nexus-framework) is Prescott Data's
provider-agnostic OAuth 2.0 / OIDC integration layer. JarvisCore communicates
exclusively with the Nexus Gateway — never with the Broker or providers directly.

Components:
- NexusClient: HTTP client for the Nexus Gateway REST API
- LifecycleMonitor: Background connection health monitoring
- Models: Pydantic models for connection/strategy data
"""

from .models import ConnectionRequest, DynamicStrategy, ConnectionStatus
from .client import NexusClient
from .lifecycle import LifecycleMonitor
from .call_proxy import NexusCallProxy
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
    "PROVIDER_CATALOG",
    "get_provider",
    "get_scopes",
    "get_auth_type",
    "list_providers",
]
