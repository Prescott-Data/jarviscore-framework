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

__version__ = "1.1.0"
__author__ = "JarvisCore Contributors"
__license__ = "Apache-2.0"

# Core classes
from jarviscore.core.agent import Agent
from jarviscore.core.profile import Profile
from jarviscore.core.mesh import Mesh, MeshMode

# Execution profiles
from jarviscore.profiles.autoagent import AutoAgent
from jarviscore.profiles.customagent import CustomAgent
from jarviscore.profiles.reasoningagent import ReasoningAgent

# Custom Profile: Decorator, Wrapper, and Context
from jarviscore.adapter import jarvis_agent, wrap
from jarviscore.context import JarvisContext, MemoryAccessor, DependencyAccessor

# Long-horizon planning (lazy import — requires no extra dependencies)
try:
    from jarviscore.planning import (
        GoalExecution,
        PlannedStep,
        StepEvaluation,
        CompletedStep,
        Planner,
        PlannerError,
        StepEvaluator,
        EvaluatorError,
    )
except Exception:  # noqa: BLE001
    GoalExecution = None   # type: ignore
    Planner = None         # type: ignore
    StepEvaluator = None   # type: ignore

# P2P Direct Communication (optional — requires `pip install jarviscore-framework[p2p]`)
# These are injected into agents at start() time when available.
try:
    from jarviscore.p2p import PeerClient, PeerTool, PeerInfo, IncomingMessage
except Exception:  # noqa: BLE001  (swim-p2p + pyzmq may not be installed)
    PeerClient = None      # type: ignore
    PeerTool = None        # type: ignore
    PeerInfo = None        # type: ignore
    IncomingMessage = None # type: ignore

# Alias for agents with run() loops (previously called JarvisAgent)
JarvisAgent = Agent

__all__ = [
    # Version
    "__version__",

    # Core
    "Agent",
    "JarvisAgent",  # Alias for p2p mode
    "Profile",
    "Mesh",
    "MeshMode",

    # Profiles
    "AutoAgent",
    "ReasoningAgent",
    "CustomAgent",

    # Custom Profile (decorator and wrapper)
    "jarvis_agent",
    "wrap",
    "JarvisContext",
    "MemoryAccessor",
    "DependencyAccessor",

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
