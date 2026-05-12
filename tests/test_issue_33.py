import pytest
from jarviscore.kernel.defaults.coder import CoderSubAgent
from jarviscore.execution.sandbox import create_sandbox_executor
from jarviscore.execution.coder_sandbox import create_coder_sandbox

@pytest.mark.asyncio
async def test_coder_system_prompt_manifest_injection_standard_sandbox():
    sandbox = create_sandbox_executor()

    # We create a dummy LLM client
    class DummyLLM:
        pass

    agent = CoderSubAgent(agent_id="test_agent", llm_client=DummyLLM(), sandbox=sandbox)

    prompt = agent.get_system_prompt()

    # Check that the manifest header is present
    assert "## SANDBOX ENVIRONMENT" in prompt
    assert "The following modules and globals are pre-loaded" in prompt

    # Standard sandbox should have 'math' (module) and 'json'
    assert "- math (module)" in prompt
    assert "- json (module)" in prompt
    assert "- result (NoneType)" in prompt

@pytest.mark.asyncio
async def test_coder_system_prompt_manifest_injection_coder_sandbox():
    sandbox = create_coder_sandbox()

    class DummyLLM:
        pass

    agent = CoderSubAgent(agent_id="test_agent", llm_client=DummyLLM(), sandbox=sandbox)

    prompt = agent.get_system_prompt()

    # Check that the manifest header is present
    assert "## SANDBOX ENVIRONMENT" in prompt

    # Coder sandbox specifically has nexus_call, git, bash, Path
    assert "- bash() (function/callable)" in prompt
    assert "- git (GitHelper)" in prompt
    assert "- Path (class)" in prompt
    assert "- nexus_call() (function/callable)" in prompt
