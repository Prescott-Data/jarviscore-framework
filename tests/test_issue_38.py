import asyncio
import builtins
import pytest
from jarviscore.execution.sandbox import SandboxExecutor

@pytest.mark.asyncio
async def test_sandbox_restores_builtins_async():
    executor = SandboxExecutor(config={"sandbox_mode": "local"})

    code = """
async def main():
    raise ValueError("Task failed successfully")
"""

    # Run a failing async execution
    await executor.execute(code)

    # We can't directly check the namespace via execute() because it's a local variable.
    # We test it by calling _execute_async directly with our own tracked namespace.
    namespace = executor._create_namespace()
    original_builtins = namespace['__builtins__']

    assert original_builtins != builtins, "Builtins should be stripped initially"

    try:
        await executor._execute_async(code, namespace, 1)
    except Exception:
        pass

    assert namespace['__builtins__'] == builtins, "Builtins must be restored to the module in finally block!"

@pytest.mark.asyncio
async def test_sandbox_restores_builtins_sync():
    executor = SandboxExecutor(config={"sandbox_mode": "local"})

    code = """
def run():
    raise ValueError("Sync task failed")
run()
"""

    # Run a failing sync execution
    await executor.execute(code)

    # We test it by calling _execute_sync directly with our own tracked namespace.
    namespace = executor._create_namespace()
    original_builtins = namespace['__builtins__']

    assert original_builtins != builtins, "Builtins should be stripped initially"

    try:
        await executor._execute_sync(code, namespace, 1)
    except Exception:
        pass

    assert namespace['__builtins__'] == builtins, "Builtins must be restored to the module in finally block!"
