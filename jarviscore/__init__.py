"""
JarvisCore - P2P Distributed Agent Framework

A production-grade framework for building autonomous agent systems with:
- Event-sourced state management (crash recovery, HITL support)
- P2P coordination via SWIM protocol
- Three execution profiles:
  * AutoAgent: LLM code generation (3 lines of user code)
  * CustomAgent: Framework-agnostic (LangChain, MCP, raw Python)
  * @jarvis_agent: Decorator to wrap existing agents (1 line)
  * wrap(): Function to wrap existing instances

Quick Start (AutoAgent):
    from jarviscore import Mesh, AutoAgent

    class ScraperAgent(AutoAgent):
        role = "scraper"
        capabilities = ["web_scraping"]
        system_prompt = "You are an expert web scraper..."

    mesh = Mesh(mode="autonomous")
    mesh.add(ScraperAgent)
    await mesh.start()

Quick Start (Custom Profile with decorator):
    from jarviscore import Mesh, jarvis_agent, JarvisContext

    @jarvis_agent(role="processor", capabilities=["processing"])
    class DataProcessor:
        def run(self, data):
            return {"processed": data * 2}

    mesh = Mesh(mode="autonomous")
    mesh.add(DataProcessor)
    await mesh.start()

Quick Start (Custom Profile with wrap):
    from jarviscore import Mesh, wrap

    # Wrap an existing instance (e.g., LangChain agent)
    my_agent = MyExistingAgent()
    wrapped = wrap(my_agent, role="assistant", capabilities=["chat"])

    mesh = Mesh(mode="autonomous")
    mesh.add(wrapped)
    await mesh.start()
"""

__version__ = "0.2.0"
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
