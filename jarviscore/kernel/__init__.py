"""
Kernel Package — Internal execution engine for AutoAgent.

The kernel replaces AutoAgent's linear pipeline with a supervised OODA loop
that dispatches to specialized subagents (coder, researcher, communicator).

User-facing API stays identical — this is purely internal.
"""

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
