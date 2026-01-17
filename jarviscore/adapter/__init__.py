"""
Adapter module for JarvisCore Custom Profile.

Provides utilities to wrap existing agents for use with JarvisCore:
- @jarvis_agent: Decorator to convert any class into a JarvisCore agent
- wrap(): Function to wrap an existing instance as a JarvisCore agent

Example (decorator):
    from jarviscore import jarvis_agent, Mesh, JarvisContext

    @jarvis_agent(role="processor", capabilities=["processing"])
    class DataProcessor:
        def run(self, data):
            return {"processed": data * 2}

    mesh = Mesh(mode="autonomous")
    mesh.add(DataProcessor)
    await mesh.start()

Example (wrap function):
    from jarviscore import wrap, Mesh

    # Wrap an existing instance
    my_agent = MyLangChainAgent(llm=my_llm)
    wrapped = wrap(my_agent, role="assistant", capabilities=["chat"])

    mesh = Mesh(mode="autonomous")
    mesh.add(wrapped)
    await mesh.start()
"""

from .decorator import jarvis_agent, detect_execute_method, EXECUTE_METHODS
from .wrapper import wrap

__all__ = [
    'jarvis_agent',
    'wrap',
    'detect_execute_method',
    'EXECUTE_METHODS',
]
