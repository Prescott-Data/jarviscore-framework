"""
Adapter module for JarvisCore Custom Profile.

Provides utilities to wrap existing agents for use with JarvisCore:
- @jarvis_agent: Decorator to convert any class into a JarvisCore agent

Example:
    from jarviscore import jarvis_agent, Mesh, JarvisContext

    @jarvis_agent(role="processor", capabilities=["processing"])
    class DataProcessor:
        def run(self, data):
            return {"processed": data * 2}

    # With context access
    @jarvis_agent(role="aggregator", capabilities=["aggregation"])
    class Aggregator:
        def run(self, task, ctx: JarvisContext):
            prev = ctx.previous("step1")
            return {"aggregated": prev}

    mesh = Mesh(mode="autonomous")
    mesh.add(DataProcessor)
    mesh.add(Aggregator)
    await mesh.start()
"""

from .decorator import jarvis_agent, detect_execute_method, EXECUTE_METHODS

__all__ = [
    'jarvis_agent',
    'detect_execute_method',
    'EXECUTE_METHODS',
]
