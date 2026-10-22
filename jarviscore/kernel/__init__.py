"""
Kernel Package — Internal execution engine for AutoAgent.

The kernel replaces AutoAgent's linear pipeline with a supervised OODA loop
that dispatches to specialized subagents (coder, researcher, communicator).

User-facing API stays identical — this is purely internal.
"""

from importlib import import_module
from typing import TYPE_CHECKING

# Resolved on first access (PEP 562): `jarviscore.kernel.state` must not drag in
# the subagents and the LLM client.
_LAZY = {
    "ExecutionLease": "lease",
    "ROLE_LEASE_PROFILES": "lease",
    "AgentCognitionManager": "cognition",
    "AgentPhase": "cognition",
    "THINKING_TOOLS": "cognition",
    "ACTION_TOOLS": "cognition",
    "KernelState": "state",
    "HumanTask": "hitl",
    "AdaptiveHITLPolicy": "hitl",
    "BaseSubAgent": "subagent",
    "ToolDefinition": "subagent",
    "CoderSubAgent": "defaults",
    "ResearcherSubAgent": "defaults",
    "CommunicatorSubAgent": "defaults",
    "Kernel": "kernel",
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
    from .lease import ExecutionLease, ROLE_LEASE_PROFILES
    from .cognition import AgentCognitionManager, AgentPhase, THINKING_TOOLS, ACTION_TOOLS
    from .state import KernelState
    from .hitl import HumanTask, AdaptiveHITLPolicy
    from .subagent import BaseSubAgent, ToolDefinition
    from .defaults import CoderSubAgent, ResearcherSubAgent, CommunicatorSubAgent
    from .kernel import Kernel

__all__ = [
    "ExecutionLease",
    "ROLE_LEASE_PROFILES",
    "AgentCognitionManager",
    "AgentPhase",
    "THINKING_TOOLS",
    "ACTION_TOOLS",
    "KernelState",
    "HumanTask",
    "AdaptiveHITLPolicy",
    "BaseSubAgent",
    "ToolDefinition",
    "CoderSubAgent",
    "ResearcherSubAgent",
    "CommunicatorSubAgent",
    "Kernel",
]
