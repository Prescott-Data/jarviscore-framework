"""
Authentication — Dual-mode auth resolution for kernel execution pipeline.

Production: NexusClient → Dromos Gateway → DynamicStrategy
Development: Read tokens from env vars / config (no external deps)
"""

from .manager import AuthenticationManager

__all__ = ["AuthenticationManager"]
