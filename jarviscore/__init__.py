"""
JarvisCore — Capability-Based Distributed Agent Framework

A production-grade framework for building autonomous agent systems with:
- Workflow orchestration (always enabled)
- Peer-to-peer communication via PeerClient (always injected)
- Auto-scaling to available infrastructure (Redis, SWIM)
- Two agent profiles: AutoAgent and CustomAgent

Two agent profiles:
    AutoAgent   — LLM generates and executes code from prompts
    CustomAgent — You provide handlers or execute_task()

The Mesh detects infrastructure at start() time:
    No Redis  →  in-process workflow + local peer routing
    Redis up  →  distributed workflow + Redis peer routing
    + SWIM    →  cross-node discovery via SWIM gossip protocol

Quick Start:
    from jarviscore import Mesh
    from jarviscore.profiles import AutoAgent

    class CalcAgent(AutoAgent):
        role = "calculator"
        capabilities = ["math"]
        system_prompt = "You are a math expert. Store result in 'result'."

    mesh = Mesh()             # No mode — auto-detects everything
    mesh.add(CalcAgent)
    await mesh.start()
    results = await mesh.workflow("calc", [{"agent": "calculator", "task": "Calculate 10!"}])

Autonomous agents (with run() loops):
    class MyAgent(AutoAgent):
        role = "my_agent"
        async def run(self):
            while True:
                await self._check_mailbox()
                # ... self-driving logic
                await asyncio.sleep(60)

    mesh = Mesh()
    mesh.add(MyAgent)
    await mesh.start()
    await mesh.run_forever()   # Starts run() loops, blocks until Ctrl+C
"""

from typing import TYPE_CHECKING

__author__ = "JarvisCore Contributors"
__license__ = "Apache-2.0"

# Public names resolve on first access (PEP 562) so `import jarviscore` and the
# CLI do not pay for the mesh, kernel and LLM SDK import graph up front.
_LAZY = {
    "Agent": "jarviscore.core.agent",
    "JarvisAgent": "jarviscore.core.agent:Agent",  # alias for agents with run() loops
    "Profile": "jarviscore.core.profile",
    "Mesh": "jarviscore.core.mesh",
    "MeshMode": "jarviscore.core.mesh",
    "Pool": "jarviscore.core.pool",
    "AutoAgent": "jarviscore.profiles.autoagent",
    "CustomAgent": "jarviscore.profiles.customagent",
    "HumanAgent": "jarviscore.human",
    **dict.fromkeys([
        "BlobSnapshotStore", "SandboxBinding", "SnapshotEntry", "SourceRef",
        "SourceSnapshot", "WorkspaceAccess", "WorkspaceDelta", "WorkspaceDeltaConflict",
    ], "jarviscore.execution.workspace"),
    **dict.fromkeys(["Proposal", "Room", "RoomConflict"], "jarviscore.room"),
    **dict.fromkeys([
        "SourceAdapter", "SourceAdapterError", "SourceContractError", "SourceIntegrityError",
    ], "jarviscore.execution.sources"),
    "jarvis_agent": "jarviscore.adapter",
    "wrap": "jarviscore.adapter",
    **dict.fromkeys(["JarvisContext", "MemoryAccessor", "DependencyAccessor"], "jarviscore.context"),
    **dict.fromkeys(
        ["DecisionClientError", "DecisionClient", "DecisionResult", "JevDecisionClient"],
        "jarviscore.execution.decisions"),
    **dict.fromkeys([
        "ArtifactReference", "ArtifactReferenceError", "CommandObservation", "WorkspaceMutation",
        "hydrate_artifact_references", "hydrate_receipt_evidence",
    ], "jarviscore.kernel.state"),
    # Long-horizon planning (requires no extra dependencies)
    **dict.fromkeys([
        "GoalExecution", "PlannedStep", "StepEvaluation", "CompletedStep",
        "Planner", "PlannerError", "StepEvaluator", "EvaluatorError",
    ], "jarviscore.planning"),
    # P2P (optional — `pip install jarviscore-framework[p2p]`); injected into agents at start()
    **dict.fromkeys(["PeerClient", "PeerTool", "PeerInfo", "IncomingMessage"], "jarviscore.p2p"),
}

# Names that resolve to None when their optional module fails to import.
_NONE_ON_IMPORT_ERROR = {
    "jarviscore.planning": {"GoalExecution", "Planner", "StepEvaluator"},
    "jarviscore.p2p": {"PeerClient", "PeerTool", "PeerInfo", "IncomingMessage"},
}


def __getattr__(name: str):
    if name == "__version__":
        # Single-sourced from package metadata (pyproject version).
        from importlib.metadata import PackageNotFoundError, version

        try:
            value = version("jarviscore-framework")
        except PackageNotFoundError:  # running from a source tree without install
            value = "0.0.0.dev0"
    elif name in _LAZY:
        module_name, _, attr = _LAZY[name].partition(":")
        from importlib import import_module

        try:
            value = getattr(import_module(module_name), attr or name)
        except Exception:  # noqa: BLE001  (swim-p2p + pyzmq may not be installed)
            if name not in _NONE_ON_IMPORT_ERROR.get(module_name, ()):
                raise
            value = None
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY) | {"__version__"})


if TYPE_CHECKING:
    from jarviscore.adapter import jarvis_agent, wrap
    from jarviscore.context import DependencyAccessor, JarvisContext, MemoryAccessor
    from jarviscore.core.agent import Agent
    from jarviscore.core.agent import Agent as JarvisAgent
    from jarviscore.core.mesh import Mesh, MeshMode
    from jarviscore.core.pool import Pool
    from jarviscore.core.profile import Profile
    from jarviscore.execution.decisions import (
        DecisionClient, DecisionClientError, DecisionResult, JevDecisionClient,
    )
    from jarviscore.execution.sources import (
        SourceAdapter, SourceAdapterError, SourceContractError, SourceIntegrityError,
    )
    from jarviscore.execution.workspace import (
        BlobSnapshotStore, SandboxBinding, SnapshotEntry, SourceRef, SourceSnapshot,
        WorkspaceAccess, WorkspaceDelta, WorkspaceDeltaConflict,
    )
    from jarviscore.human import HumanAgent
    from jarviscore.kernel.state import (
        ArtifactReference, ArtifactReferenceError, CommandObservation, WorkspaceMutation,
        hydrate_artifact_references, hydrate_receipt_evidence,
    )
    from jarviscore.p2p import IncomingMessage, PeerClient, PeerInfo, PeerTool
    from jarviscore.planning import (
        CompletedStep, EvaluatorError, GoalExecution, PlannedStep, Planner, PlannerError,
        StepEvaluation, StepEvaluator,
    )
    from jarviscore.profiles.autoagent import AutoAgent
    from jarviscore.profiles.customagent import CustomAgent
    from jarviscore.room import Proposal, Room, RoomConflict

    __version__: str

__all__ = [
    # Version
    "__version__",

    # Core
    "Agent",
    "JarvisAgent",  # Alias for p2p mode
    "Profile",
    "Mesh",
    "MeshMode",
    "Pool",

    # Profiles
    "AutoAgent",
    "CustomAgent",
    "HumanAgent",

    # Durable source snapshots and ephemeral execution bindings
    "SourceRef",
    "SnapshotEntry",
    "SourceSnapshot",
    "WorkspaceDelta",
    "WorkspaceDeltaConflict",
    "BlobSnapshotStore",
    "SandboxBinding",
    "WorkspaceAccess",

    # Rooms: shared workspaces people and agents change together
    "Room",
    "Proposal",
    "RoomConflict",
    "SourceAdapter",
    "SourceAdapterError",
    "SourceContractError",
    "SourceIntegrityError",

    # Custom Profile (decorator and wrapper)
    "jarvis_agent",
    "wrap",
    "JarvisContext",
    "MemoryAccessor",
    "DependencyAccessor",
    "ArtifactReference",
    "ArtifactReferenceError",
    "CommandObservation",
    "WorkspaceMutation",
    "hydrate_artifact_references",
    "hydrate_receipt_evidence",

    # Decision models
    "DecisionClientError",
    "DecisionClient",
    "DecisionResult",
    "JevDecisionClient",

    # P2P Direct Communication
    "PeerClient",
    "PeerTool",
    "PeerInfo",
    "IncomingMessage",

    # Long-horizon planning
    "GoalExecution",
    "PlannedStep",
    "StepEvaluation",
    "CompletedStep",
    "Planner",
    "PlannerError",
    "StepEvaluator",
    "EvaluatorError",
]
