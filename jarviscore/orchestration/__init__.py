"""
Orchestration module for JarvisCore Framework

Workflow execution engine with dependency management.
Includes WorkflowBuilder (agent-facing DAG composition API
for building multi-step, dependency-aware agent workflows).
"""

from .engine import WorkflowEngine
from .claimer import StepClaimer
from .dependency import DependencyManager
from .status import StatusManager, StepStatus
from .state import WorkflowState
from .workflow_builder import WorkflowBuilder, Workflow, WorkflowStep

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
]
