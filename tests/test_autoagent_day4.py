"""
Tests for Day 4: AutoAgent with Code Generation

Tests the complete execution pipeline:
- LLM client initialization
- Code generation
- Sandbox execution
- Autonomous repair
"""
import pytest
import asyncio
from jarviscore.profiles import AutoAgent
from jarviscore.execution import (
    create_llm_client,
    create_search_client,
    create_code_generator,
    create_sandbox_executor,
    create_autonomous_repair
)


class SimpleAgent(AutoAgent):
    """Test agent for unit tests."""
    role = "test_agent"
    capabilities = ["testing"]
    system_prompt = "You are a test agent."


def test_autoagent_initialization():
    """Test AutoAgent can be instantiated."""
    agent = SimpleAgent()
    assert agent.role == "test_agent"
    assert agent.capabilities == ["testing"]
    assert agent.system_prompt == "You are a test agent."


@pytest.mark.asyncio
async def test_execution_components_creation():
    """Test all execution components can be created."""
    # LLM client (no config, just instantiation test)
    llm = create_llm_client({})
    assert llm is not None

    # Search client
    search = create_search_client()
    assert search is not None

    # Code generator
    codegen = create_code_generator(llm, search)
    assert codegen is not None

    # Sandbox executor
    sandbox = create_sandbox_executor(timeout=60, search_client=search)
    assert sandbox is not None

    # Autonomous repair
    repair = create_autonomous_repair(codegen)
    assert repair is not None


@pytest.mark.asyncio
async def test_sandbox_simple_execution():
    """Test sandbox can execute simple code."""
    from jarviscore.execution import SandboxExecutor

    sandbox = SandboxExecutor(timeout=10)

    code = """
# Simple calculation
result = 2 + 2
"""

    result = await sandbox.execute(code)

    assert result['status'] == 'success'
    assert result['output'] == 4


@pytest.mark.asyncio
async def test_sandbox_async_execution():
    """Test sandbox can execute async code."""
    from jarviscore.execution import SandboxExecutor

    sandbox = SandboxExecutor(timeout=10)

    code = """
import asyncio

async def main():
    await asyncio.sleep(0.01)
    return 42

# The result will be extracted by sandbox's _execute_async
"""

    result = await sandbox.execute(code)

    assert result['status'] == 'success'
    assert result['output'] == 42


@pytest.mark.asyncio
async def test_sandbox_error_handling():
    """Test sandbox properly handles errors."""
    from jarviscore.execution import SandboxExecutor

    sandbox = SandboxExecutor(timeout=10)

    code = """
# This will raise an error
result = 1 / 0
"""

    result = await sandbox.execute(code)

    assert result['status'] == 'failure'
    assert 'ZeroDivisionError' in result.get('error_type', '')


@pytest.mark.asyncio
async def test_code_generator_validation():
    """Test code generator validates syntax."""
    from jarviscore.execution import CodeGenerator, UnifiedLLMClient

    llm = UnifiedLLMClient({})
    codegen = CodeGenerator(llm, None)

    # Test syntax validation
    valid_code = "result = 42"
    codegen._validate_code(valid_code)  # Should not raise

    invalid_code = "result = if 42"
    with pytest.raises(ValueError):
        codegen._validate_code(invalid_code)


@pytest.mark.asyncio
async def test_code_generator_cleaning():
    """Test code generator cleans markdown blocks."""
    from jarviscore.execution import CodeGenerator, UnifiedLLMClient

    llm = UnifiedLLMClient({})
    codegen = CodeGenerator(llm, None)

    # Test cleaning markdown blocks
    markdown_code = """
```python
result = 42
```
"""

    cleaned = codegen._clean_code(markdown_code)
    assert cleaned == "result = 42"


def test_autoagent_requires_system_prompt():
    """Test AutoAgent requires system_prompt."""
    with pytest.raises(ValueError) as exc_info:
        class BadAgent(AutoAgent):
            role = "bad"
            capabilities = ["test"]
            # Missing system_prompt

        BadAgent()

    assert "system_prompt" in str(exc_info.value)


@pytest.mark.asyncio
async def test_search_client_initialization():
    """Test search client can be created and initialized."""
    from jarviscore.execution import InternetSearch

    search = InternetSearch()
    await search.initialize()

    assert search.session is not None
    assert not search.session.closed

    await search.close()
    assert search.session is None


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
