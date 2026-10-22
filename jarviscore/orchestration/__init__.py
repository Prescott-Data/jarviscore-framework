"""
Orchestration module for JarvisCore Framework

Workflow execution engine with dependency management.
Includes WorkflowBuilder (agent-facing DAG composition API
for building multi-step, dependency-aware agent workflows).
"""

from importlib import import_module
from typing import TYPE_CHECKING

# Resolved on first access (PEP 562) so `orchestration.budget` stays cheap.
_LAZY = {
    "WorkflowEngine": "engine",
    "StepClaimer": "claimer",
    "DependencyManager": "dependency",
    "StatusManager": "status",
    "StepStatus": "status",
    "WorkflowState": "state",
    "WorkflowBuilder": "workflow_builder",
    "Workflow": "workflow_builder",
    "WorkflowStep": "workflow_builder",
    **dict.fromkeys([
        "CapabilityMandate", "ClaimRecord", "DependencyAuthorization", "ExecutionBudget",
        "EffectIntentDecision", "FulfillmentRecord", "WorkflowEnvelope", "WorkflowEvidence",
        "neutral_context",
    ], "envelopes"),
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
    from .engine import WorkflowEngine
    from .claimer import StepClaimer
    from .dependency import DependencyManager
    from .status import StatusManager, StepStatus
    from .state import WorkflowState
    from .workflow_builder import WorkflowBuilder, Workflow, WorkflowStep
    from .envelopes import (
        CapabilityMandate,
        ClaimRecord,
        DependencyAuthorization,
        ExecutionBudget,
        EffectIntentDecision,
        FulfillmentRecord,
        WorkflowEnvelope,
        WorkflowEvidence,
        neutral_context,
    )

__all__ = [
    'WorkflowEngine',
    'StepClaimer',
    'DependencyManager',
    'StatusManager',
    'StepStatus',
    'WorkflowState',
    # Layer 2: Agent-facing workflow API
    'WorkflowBuilder',
    'Workflow',
    'WorkflowStep',
    'CapabilityMandate',
    'ClaimRecord',
    'DependencyAuthorization',
    'ExecutionBudget',
    'EffectIntentDecision',
    'FulfillmentRecord',
    'WorkflowEnvelope',
    'WorkflowEvidence',
    'neutral_context',
]
