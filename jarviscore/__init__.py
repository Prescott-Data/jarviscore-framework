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

# Single-sourced from package metadata (pyproject version), so releases
# cannot drift the way the hardcoded 1.2.0 string did.
from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("jarviscore-framework")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0.dev0"
__author__ = "JarvisCore Contributors"
__license__ = "Apache-2.0"

import importlib as _importlib
from typing import TYPE_CHECKING as _TYPE_CHECKING

# Public names load on first use (PEP 562): ``import jarviscore`` used to import
# the mesh, every LLM SDK and the planner, about 3 s, before a line of user code;
# and every sandboxed code run paid it again in its child process.
_EXPORTS = {
    "jarviscore.core.agent": ("Agent",),
    "jarviscore.core.profile": ("Profile",),
    "jarviscore.core.mesh": ("Mesh", "MeshMode"),
    "jarviscore.core.pool": ("Pool",),
    "jarviscore.profiles.autoagent": ("AutoAgent",),
    "jarviscore.profiles.customagent": ("CustomAgent",),
    "jarviscore.human": ("HumanAgent",),
    "jarviscore.execution.workspace": (
        "BlobSnapshotStore", "SandboxBinding", "SnapshotEntry", "SourceRef",
        "SourceSnapshot", "WorkspaceAccess", "WorkspaceDelta", "WorkspaceDeltaConflict",
    ),
    "jarviscore.room": ("Proposal", "Room", "RoomConflict"),
    "jarviscore.execution.sources": (
        "SourceAdapter", "SourceAdapterError", "SourceContractError", "SourceIntegrityError",
    ),
    "jarviscore.adapter": ("jarvis_agent", "wrap"),
    "jarviscore.context": ("JarvisContext", "MemoryAccessor", "DependencyAccessor"),
    "jarviscore.execution.decisions": (
        "DecisionClientError", "DecisionClient", "DecisionResult", "JevDecisionClient",
    ),
    "jarviscore.kernel.state": (
        "ArtifactReference", "ArtifactReferenceError", "CommandObservation",
        "WorkspaceMutation", "hydrate_artifact_references", "hydrate_receipt_evidence",
    ),
    # Long-horizon planning
    "jarviscore.planning": (
        "GoalExecution", "PlannedStep", "StepEvaluation", "CompletedStep", "Planner",
        "PlannerError", "StepEvaluator", "EvaluatorError",
    ),
    # P2P direct communication (optional: `pip install jarviscore-framework[p2p]`);
    # injected into agents at start() time when available.
    "jarviscore.p2p": ("PeerClient", "PeerTool", "PeerInfo", "IncomingMessage"),
}
_SOURCE = {name: module for module, names in _EXPORTS.items() for name in names}
#: Modules whose names are None when they cannot be imported, as before.
_OPTIONAL = frozenset({"jarviscore.planning", "jarviscore.p2p"})
#: Agents with run() loops (previously called JarvisAgent).
_ALIASES = {"JarvisAgent": "Agent"}


def __getattr__(name):
    if name in _ALIASES:
        value = __getattr__(_ALIASES[name])
    elif name in _SOURCE:
        module = _SOURCE[name]
        try:
            value = getattr(_importlib.import_module(module), name)
        except Exception:  # noqa: BLE001
            if module not in _OPTIONAL:
                raise
            value = None
    else:
        # ``import jarviscore`` used to import its subpackages too; reaching one as an
        # attribute (``jarviscore.core.mesh``) still works.
        try:
            value = _importlib.import_module(f"{__name__}.{name}")
        except ModuleNotFoundError as exc:
            if exc.name != f"{__name__}.{name}":
                raise
            raise AttributeError(f"module 'jarviscore' has no attribute {name!r}") from None
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


if _TYPE_CHECKING:  # pragma: no cover - for type checkers and IDEs
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
