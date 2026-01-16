"""
Context module for JarvisCore Custom Profile.

Provides orchestration primitives for wrapped agents:
- JarvisContext: Unified context with workflow info and accessors
- MemoryAccessor: Clean API over workflow memory
- DependencyAccessor: Clean API over dependency management

These are facades over existing JarvisCore components, providing
a developer-friendly interface for Custom Profile agents.

Example:
    from jarviscore.context import JarvisContext

    @jarvis_agent(role="processor", capabilities=["processing"])
    class Processor:
        def run(self, task, ctx: JarvisContext):
            # Access previous step
            data = ctx.previous("step1")

            # Access memory
            all_data = ctx.memory.all()

            # Check dependencies
            if ctx.deps.is_ready("optional"):
                optional = ctx.previous("optional")

            return {"processed": process(data)}
"""

from .jarvis_context import JarvisContext, create_context
from .memory import MemoryAccessor
from .dependency import DependencyAccessor

__all__ = [
    'JarvisContext',
    'create_context',
    'MemoryAccessor',
    'DependencyAccessor',
]
