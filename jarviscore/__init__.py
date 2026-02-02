"""
JarvisCore - P2P Distributed Agent Framework

A production-grade framework for building autonomous agent systems with:
- P2P coordination via SWIM protocol
- Workflow orchestration with dependencies
- Two agent profiles: AutoAgent and CustomAgent

Profiles:
    AutoAgent   - LLM generates and executes code from prompts (autonomous mode)
    CustomAgent - You provide handlers or execute_task() (p2p/distributed modes)

Modes:
    autonomous  - Workflow engine only (AutoAgent)
    p2p         - P2P coordinator only (CustomAgent with run() loop)
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

Quick Start (CustomAgent + FastAPI):
    from fastapi import FastAPI
    from jarviscore.profiles import CustomAgent
    from jarviscore.integrations.fastapi import JarvisLifespan

    class MyAgent(CustomAgent):
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

__version__ = "0.3.1"
__author__ = "JarvisCore Contributors"
__license__ = "MIT"

# Core classes
from jarviscore.core.agent import Agent
from jarviscore.core.profile import Profile
from jarviscore.core.mesh import Mesh, MeshMode

# Execution profiles
from jarviscore.profiles.autoagent import AutoAgent
from jarviscore.profiles.customagent import CustomAgent

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
