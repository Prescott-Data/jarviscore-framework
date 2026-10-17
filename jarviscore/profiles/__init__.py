"""
Execution profiles for agents.

Profiles define HOW agents execute tasks:
- AutoAgent: LLM-powered code generation + sandboxed execution
- CustomAgent: User-defined logic with P2P message handling
"""

from .autoagent import AutoAgent
from .customagent import CustomAgent

__all__ = ["AutoAgent", "CustomAgent"]
