"""
JarvisCore - P2P Distributed Agent Framework

A production-grade framework for building autonomous agent systems with:
- P2P coordination via SWIM protocol
- Workflow orchestration with dependencies
- Three agent profiles: AutoAgent, CustomAgent, and ListenerAgent

Profiles:
    AutoAgent     - LLM generates and executes code from prompts (autonomous mode)
    CustomAgent   - You provide execute_task() or run() (p2p/distributed modes)
    ListenerAgent - API-first agents with background P2P (just implement handlers)

Modes:
    autonomous  - Workflow engine only (AutoAgent)
    p2p         - P2P coordinator only (CustomAgent/ListenerAgent with run() loops)
    distributed - Both workflow + P2P (CustomAgent with execute_task())

Quick Start (AutoAgent - autonomous mode):
    from jarviscore import Mesh
    from jarviscore.profiles import AutoAgent

    class CalcAgent(AutoAgent):
        role = "calculator"
        capabilities = ["math"]
        system_prompt = "You are a math expert. Store result in 'result'."

    mesh = Mesh(mode="autonomous")
    mesh.add(CalcAgent)
    await mesh.start()
    results = await mesh.workflow("calc", [{"agent": "calculator", "task": "Calculate 10!"}])

Quick Start (ListenerAgent + FastAPI):
    from fastapi import FastAPI
    from jarviscore.profiles import ListenerAgent
    from jarviscore.integrations.fastapi import JarvisLifespan

    class MyAgent(ListenerAgent):
        role = "processor"
        capabilities = ["processing"]

        async def on_peer_request(self, msg):
            return {"result": msg.data.get("task", "").upper()}

    app = FastAPI(lifespan=JarvisLifespan(MyAgent(), mode="p2p"))

Quick Start (CustomAgent - distributed mode):
    from jarviscore import Mesh
    from jarviscore.profiles import CustomAgent

    class MyAgent(CustomAgent):
        role = "processor"
        capabilities = ["processing"]

        async def execute_task(self, task):
            return {"status": "success", "output": task.get("task").upper()}

    mesh = Mesh(mode="distributed", config={'bind_port': 7950})
    mesh.add(MyAgent)
    await mesh.start()
    results = await mesh.workflow("demo", [{"agent": "processor", "task": "hello"}])
"""

__version__ = "0.3.0"
__author__ = "JarvisCore Contributors"
__license__ = "MIT"

# Core classes
from jarviscore.core.agent import Agent
from jarviscore.core.profile import Profile
from jarviscore.core.mesh import Mesh, MeshMode

# Execution profiles
from jarviscore.profiles.autoagent import AutoAgent
from jarviscore.profiles.customagent import CustomAgent
from jarviscore.profiles.listeneragent import ListenerAgent

# Custom Profile: Decorator, Wrapper, and Context
from jarviscore.adapter import jarvis_agent, wrap
from jarviscore.context import JarvisContext, MemoryAccessor, DependencyAccessor

# P2P Direct Communication
from jarviscore.p2p import PeerClient, PeerTool, PeerInfo, IncomingMessage

# Alias for p2p mode agents
JarvisAgent = Agent  # Use this for agents with run() loops

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
    "CustomAgent",
    "ListenerAgent",

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
]
