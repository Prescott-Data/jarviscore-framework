"""
Authentication — Dual-mode auth resolution for kernel execution pipeline.

Production: NexusClient → Nexus Gateway → DynamicStrategy
Development: Read tokens from env vars / config (no external deps)

OAuth flow: CLIFlowHandler opens browser + polls Gateway for completion.
HostedFlowHandler hands the link to a UI instead, for agents that are not
running next to a terminal. Custom handlers can be plugged in (Slack, etc).
"""

from .manager import AuthenticationManager
from .oauth_flow import (
    CLIFlowHandler,
    HostedFlowHandler,
    LocalCallbackServer,
    OAuthFlowHandler,
)

__all__ = [
    "AuthenticationManager",
    "OAuthFlowHandler",
    "CLIFlowHandler",
    "HostedFlowHandler",
    "LocalCallbackServer",
]
