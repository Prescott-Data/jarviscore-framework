"""
Execution profiles for agents.

Profiles define HOW agents execute tasks:
- AutoAgent: LLM-powered code generation + sandboxed execution
- CustomAgent: User-defined logic with P2P message handling
- HumanAgent: A person on the mesh, answering through a channel
"""

from .autoagent import AutoAgent
from .customagent import CustomAgent
from .humanagent import HumanAgent

__all__ = ["AutoAgent", "CustomAgent", "HumanAgent"]
