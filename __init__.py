"""
JarvisCore - P2P Distributed Agent Framework

A production-grade framework for building autonomous agent systems with:
- Event-sourced state management (crash recovery, HITL support)
- P2P coordination via SWIM protocol
- Two execution profiles:
  * AutoAgent: LLM code generation (3 lines of user code)
  * CustomAgent: Framework-agnostic (LangChain, MCP, raw Python)

Quick Start:
    from jarviscore import Mesh, AutoAgent

    class ScraperAgent(AutoAgent):
        role = "scraper"
        capabilities = ["web_scraping"]
        system_prompt = "You are an expert web scraper..."

    mesh = Mesh(mode="autonomous")
    mesh.add(ScraperAgent)
    await mesh.start()

    results = await mesh.workflow("my-workflow", [
        {"agent": "scraper", "task": "Scrape example.com"}
    ])
"""

__version__ = "0.1.0"
__author__ = "JarvisCore Contributors"
__license__ = "MIT"

# Core classes
from jarviscore.core.agent import Agent
from jarviscore.core.profile import Profile
from jarviscore.core.mesh import Mesh, MeshMode

# Execution profiles
from jarviscore.profiles.autoagent import AutoAgent
from jarviscore.profiles.customagent import CustomAgent

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
]
