"""
JarvisCore - P2P Distributed Agent Framework

A production-grade framework for building autonomous agent systems with:
- Event-sourced state management (crash recovery, HITL support)
- P2P coordination via SWIM protocol
- Three execution profiles:
  * AutoAgent: LLM code generation (3 lines of user code)
  * CustomAgent: Framework-agnostic (LangChain, MCP, raw Python)
  * @jarvis_agent: Decorator to wrap existing agents (1 line)

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

    # With context access
    @jarvis_agent(role="aggregator", capabilities=["aggregation"])
    class Aggregator:
        def run(self, task, ctx: JarvisContext):
            prev = ctx.previous("step1")
            return {"result": prev}

    mesh = Mesh(mode="autonomous")
    mesh.add(DataProcessor)
    mesh.add(Aggregator)
    await mesh.start()

    results = await mesh.workflow("pipeline", [
        {"agent": "processor", "task": "Process", "params": {"data": [1,2,3]}},
        {"agent": "aggregator", "task": "Aggregate", "depends_on": [0]}
    ])
"""

__version__ = "0.1.1"
__author__ = "JarvisCore Contributors"
__license__ = "MIT"

# Core classes
from jarviscore.core.agent import Agent
from jarviscore.core.profile import Profile
from jarviscore.core.mesh import Mesh, MeshMode

# Execution profiles
from jarviscore.profiles.autoagent import AutoAgent
from jarviscore.profiles.customagent import CustomAgent

# Custom Profile: Decorator and Context
from jarviscore.adapter import jarvis_agent
from jarviscore.context import JarvisContext, MemoryAccessor, DependencyAccessor

__all__ = [
    # Version
    "__version__",

    # Core
    "Agent",
    "Profile",
    "Mesh",
    "MeshMode",

    # Profiles
    "AutoAgent",
    "CustomAgent",

    # Custom Profile (decorator approach)
    "jarvis_agent",
    "JarvisContext",
    "MemoryAccessor",
    "DependencyAccessor",
]
