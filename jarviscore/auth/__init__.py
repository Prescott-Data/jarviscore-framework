"""
Authentication — Dual-mode auth resolution for kernel execution pipeline.

Production: NexusClient → Dromos Gateway → DynamicStrategy
Development: Read tokens from env vars / config (no external deps)

OAuth flow: CLIFlowHandler opens browser + polls for completion.
Custom handlers can be plugged in (Slack, web UI, etc).
"""

from .manager import AuthenticationManager
from .oauth_flow import OAuthFlowHandler, CLIFlowHandler, LocalCallbackServer

__all__ = [
    "AuthenticationManager",
    "OAuthFlowHandler",
    "CLIFlowHandler",
    "LocalCallbackServer",
]
