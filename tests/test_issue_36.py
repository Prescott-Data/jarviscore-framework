import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from jarviscore.core.agent import Agent
from jarviscore.profiles.autoagent import AutoAgent
from jarviscore.profiles.customagent import CustomAgent
from jarviscore.integrations.fastapi import JarvisLifespan

class DummyAutoAgent(AutoAgent):
    role = "test_auto"
    capabilities = ["test"]
    system_prompt = "You are a test agent."

class DummyCustomAgent(CustomAgent):
    role = "test_custom"
    capabilities = ["test"]

class BadResponderAgent(Agent):
    role = "bad_responder"
    capabilities = ["test"]
    p2p_responder = True
    # Inherits the default no-op run() method, which should cause a fast-fail

    async def execute_task(self, task):
        return {"status": "success"}

@pytest.mark.asyncio
async def test_agent_p2p_responder_defaults():
    auto_agent = DummyAutoAgent()
    custom_agent = DummyCustomAgent()

    assert auto_agent.p2p_responder is False, "AutoAgent should not be a P2P responder by default"
    assert custom_agent.p2p_responder is True, "CustomAgent should be a P2P responder by default"

@pytest.mark.asyncio
@patch('jarviscore.integrations.fastapi.Mesh', create=True)
async def test_jarvis_lifespan_background_task_creation(MockMesh):
    auto_agent = DummyAutoAgent()
    custom_agent = DummyCustomAgent()

    # We mock the Mesh so we don't actually bind ports
    mock_mesh_instance = AsyncMock()
    MockMesh.return_value = mock_mesh_instance
    mock_mesh_instance.add.side_effect = lambda a: a

    # Create lifespan with both agents
    lifespan = JarvisLifespan([auto_agent, custom_agent])

    # Mock an ASGI app
    class MockApp:
        class State:
            pass
        state = State()

    app = MockApp()

    async with lifespan(app):
        # JarvisLifespan should have created a background task ONLY for custom_agent
        assert len(lifespan._background_tasks) == 1
        # Check task name
        task_name = lifespan._background_tasks[0].get_name()
        assert task_name == f"jarvis-agent-{custom_agent.agent_id}"

@pytest.mark.asyncio
@patch('jarviscore.integrations.fastapi.Mesh', create=True)
async def test_jarvis_lifespan_fast_fails_on_bad_responder(MockMesh):
    bad_agent = BadResponderAgent()

    mock_mesh_instance = AsyncMock()
    MockMesh.return_value = mock_mesh_instance
    mock_mesh_instance.add.return_value = bad_agent

    lifespan = JarvisLifespan(bad_agent)

    class MockApp:
        class State:
            pass
        state = State()

    app = MockApp()

    # Should raise RuntimeError because it claims to be a responder but has no real run() loop
    with pytest.raises(RuntimeError, match="claims to be a p2p_responder but inherits the base no-op"):
        async with lifespan(app):
            pass
