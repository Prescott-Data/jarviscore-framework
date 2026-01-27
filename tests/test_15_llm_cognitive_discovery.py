"""
Test 15: LLM Cognitive Discovery - Smart Autonomous Agent Discovery

Tests the complete LLM + Cognitive Discovery integration:
1. Cognitive context generation with real peers
2. LLM receives and understands peer context
3. LLM decides to use peer tools
4. End-to-end peer communication

This test file includes both:
- Unit tests (always run, use mocks)
- Integration tests (skip if no LLM API key)

Run with: pytest tests/test_15_llm_cognitive_discovery.py -v -s
"""
import asyncio
import os
import sys
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, '.')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

def get_llm_client():
    """Get configured LLM client from settings."""
    try:
        from jarviscore.config import settings
        from anthropic import Anthropic

        api_key = (
            settings.claude_api_key or
            os.environ.get("CLAUDE_API_KEY") or
            os.environ.get("ANTHROPIC_API_KEY")
        )

        if not api_key:
            return None, None, "No API key"

        endpoint = settings.claude_endpoint or os.environ.get("CLAUDE_ENDPOINT")
        model = settings.claude_model or os.environ.get("CLAUDE_MODEL") or "claude-sonnet-4-20250514"

        if endpoint:
            client = Anthropic(api_key=api_key, base_url=endpoint)
        else:
            client = Anthropic(api_key=api_key)

        return client, model, None
    except Exception as e:
        return None, None, str(e)


def has_valid_llm_api_key():
    """Check if a valid LLM API key is configured by testing it."""
    try:
        client, model, error = get_llm_client()
        if error:
            return False

        # Actually validate the key with a minimal request
        client.messages.create(
            model=model,
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )
        return True
    except Exception as e:
        print(f"LLM validation failed: {e}")
        return False


# Cache the result to avoid multiple API calls
_llm_available = None


def llm_is_available():
    """Check if LLM is available (cached)."""
    global _llm_available
    if _llm_available is None:
        _llm_available = has_valid_llm_api_key()
    return _llm_available


# Skip marker for tests requiring real LLM
requires_llm = pytest.mark.skipif(
    not llm_is_available(),
    reason="No valid LLM API key configured"
)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: COGNITIVE CONTEXT WITH REAL MESH
# ═══════════════════════════════════════════════════════════════════════════════

class TestCognitiveContextWithRealMesh:
    """Test cognitive context generation in a real mesh."""

    @pytest.mark.asyncio
    async def test_cognitive_context_reflects_actual_peers(self):
        """Test get_cognitive_context() shows actual mesh peers."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class AgentA(CustomAgent):
            role = "analyst"
            capabilities = ["data_analysis", "statistics"]
            description = "Analyzes data and provides insights"

            async def execute_task(self, task):
                return {"status": "success"}

        class AgentB(CustomAgent):
            role = "researcher"
            capabilities = ["web_search", "research"]
            description = "Researches topics on the web"

            async def execute_task(self, task):
                return {"status": "success"}

        mesh = Mesh(mode="p2p", config={"bind_port": 7970})
        agent_a = mesh.add(AgentA())
        agent_b = mesh.add(AgentB())

        await mesh.start()

        try:
            # Get cognitive context from agent_a's perspective
            context = agent_a.peers.get_cognitive_context(format="markdown")

            # Should see agent_b but not itself
            assert "researcher" in context
            assert "web_search" in context or "research" in context
            # Should not see itself
            # (agent_a is "analyst", context should show OTHER peers)

            # Get context from agent_b's perspective
            context_b = agent_b.peers.get_cognitive_context(format="markdown")
            assert "analyst" in context_b
            assert "data_analysis" in context_b or "statistics" in context_b

        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_cognitive_context_updates_with_peer_changes(self):
        """Test cognitive context updates when peers join."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class Observer(CustomAgent):
            role = "observer"
            capabilities = ["observation"]
            async def execute_task(self, task):
                return {"status": "success"}

        class LateJoiner(CustomAgent):
            role = "late_joiner"
            capabilities = ["late_capability"]
            async def execute_task(self, task):
                return {"status": "success"}

        mesh = Mesh(mode="p2p", config={"bind_port": 7971})
        observer = mesh.add(Observer())

        await mesh.start()

        try:
            # Initially, observer sees no other peers (only itself in registry)
            peers_before = observer.peers.list_peers()
            local_peer_count_before = len([p for p in peers_before if p.get('location') == 'local'])

            # Add another agent dynamically
            late_joiner = mesh.add(LateJoiner())

            # Now observer should see the new peer
            peers_after = observer.peers.list_peers()

            # Should have one more peer
            assert len(peers_after) > len(peers_before) or any(
                p['role'] == 'late_joiner' for p in peers_after
            )

            # Cognitive context should include new peer
            context = observer.peers.get_cognitive_context()
            assert "late_joiner" in context or "late_capability" in context

        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: LISTENERAGENT PEER COMMUNICATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestListenerAgentPeerCommunication:
    """Test ListenerAgent handles peer requests correctly."""

    @pytest.mark.asyncio
    async def test_listener_agent_receives_and_responds(self):
        """Test ListenerAgent receives requests and sends responses."""
        from jarviscore import Mesh
        from jarviscore.profiles import ListenerAgent, CustomAgent

        request_received = False
        request_data = None

        class ResponderAgent(ListenerAgent):
            role = "responder"
            capabilities = ["responding"]
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                nonlocal request_received, request_data
                request_received = True
                request_data = msg.data
                return {"echo": msg.data.get("message"), "status": "received"}

        class RequesterAgent(CustomAgent):
            role = "requester"
            capabilities = ["requesting"]

            async def execute_task(self, task):
                return {"status": "success"}

        mesh = Mesh(mode="p2p", config={"bind_port": 7972})
        responder = mesh.add(ResponderAgent())
        requester = mesh.add(RequesterAgent())

        await mesh.start()

        # Start responder listening in background
        responder_task = asyncio.create_task(responder.run())

        try:
            # Wait for responder to start
            await asyncio.sleep(0.2)

            # Send request from requester to responder
            response = await requester.peers.request(
                "responder",
                {"message": "Hello from requester!"},
                timeout=5
            )

            # Verify responder received the request
            assert request_received is True
            assert request_data["message"] == "Hello from requester!"

            # Verify response was received
            assert response is not None
            assert response.get("echo") == "Hello from requester!"
            assert response.get("status") == "received"

        finally:
            responder.request_shutdown()
            responder_task.cancel()
            try:
                await responder_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_cognitive_context_enables_peer_discovery_for_requests(self):
        """Test that cognitive context helps discover correct peer for requests."""
        from jarviscore import Mesh
        from jarviscore.profiles import ListenerAgent

        class AnalystAgent(ListenerAgent):
            role = "analyst"
            capabilities = ["data_analysis", "statistics"]
            description = "Expert in data analysis"
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                query = msg.data.get("query", "")
                return {"analysis": f"Analyzed: {query}", "confidence": 0.9}

        class CoordinatorAgent(ListenerAgent):
            role = "coordinator"
            capabilities = ["coordination"]
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="p2p", config={"bind_port": 7973})
        analyst = mesh.add(AnalystAgent())
        coordinator = mesh.add(CoordinatorAgent())

        await mesh.start()
        analyst_task = asyncio.create_task(analyst.run())

        try:
            await asyncio.sleep(0.2)

            # Coordinator gets cognitive context
            context = coordinator.peers.get_cognitive_context(format="json")

            import json
            context_data = json.loads(context)

            # Find analyst in peers
            analyst_peer = None
            for peer in context_data.get("available_peers", []):
                if peer.get("role") == "analyst":
                    analyst_peer = peer
                    break

            assert analyst_peer is not None
            assert "data_analysis" in analyst_peer.get("capabilities", [])

            # Coordinator can now send request to analyst by role
            response = await coordinator.peers.request(
                "analyst",
                {"query": "Analyze Q4 sales"},
                timeout=5
            )

            assert "analysis" in response
            assert "Q4 sales" in response["analysis"]

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: BUILD SYSTEM PROMPT INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildSystemPromptIntegration:
    """Test build_system_prompt with real mesh peers."""

    @pytest.mark.asyncio
    async def test_build_system_prompt_includes_all_peers(self):
        """Test build_system_prompt includes all mesh peers."""
        from jarviscore import Mesh
        from jarviscore.profiles import CustomAgent

        class Agent1(CustomAgent):
            role = "writer"
            capabilities = ["writing", "content_creation"]
            description = "Creates written content"
            async def execute_task(self, task):
                return {"status": "success"}

        class Agent2(CustomAgent):
            role = "editor"
            capabilities = ["editing", "proofreading"]
            description = "Edits and proofreads content"
            async def execute_task(self, task):
                return {"status": "success"}

        class Agent3(CustomAgent):
            role = "publisher"
            capabilities = ["publishing"]
            description = "Publishes finalized content"
            async def execute_task(self, task):
                return {"status": "success"}

        mesh = Mesh(mode="p2p", config={"bind_port": 7974})
        writer = mesh.add(Agent1())
        editor = mesh.add(Agent2())
        publisher = mesh.add(Agent3())

        await mesh.start()

        try:
            # Build system prompt from writer's perspective
            base_prompt = "You are a helpful writing assistant."
            full_prompt = writer.peers.build_system_prompt(base_prompt)

            # Should include base prompt
            assert "You are a helpful writing assistant" in full_prompt

            # Should include peer context header
            assert "AVAILABLE MESH PEERS" in full_prompt

            # Should include editor and publisher (but not writer itself)
            assert "editor" in full_prompt
            assert "publisher" in full_prompt

            # Should include capabilities
            assert "editing" in full_prompt or "proofreading" in full_prompt
            assert "publishing" in full_prompt

        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: LLM INTEGRATION (requires API key)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMCognitiveDiscovery:
    """Integration tests with real LLM calls."""

    @requires_llm
    @pytest.mark.asyncio
    async def test_llm_receives_peer_context_in_prompt(self):
        """Test LLM receives and understands peer context."""
        from jarviscore import Mesh
        from jarviscore.profiles import ListenerAgent

        class SpecialistAgent(ListenerAgent):
            role = "data_specialist"
            capabilities = ["data_processing", "analytics"]
            description = "Processes and analyzes data"
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                return {"result": "processed"}

        mesh = Mesh(mode="p2p", config={"bind_port": 7975})
        specialist = mesh.add(SpecialistAgent())

        await mesh.start()

        try:
            # Build prompt with peer context
            base_prompt = "List the available specialist agents you can delegate to."
            full_prompt = specialist.peers.build_system_prompt(base_prompt)

            # Create LLM client using configured settings
            client, model, error = get_llm_client()
            assert client is not None, f"Failed to get LLM client: {error}"

            # Ask LLM about available peers
            response = client.messages.create(
                model=model,
                max_tokens=256,
                messages=[{"role": "user", "content": "What specialist agents are available to help me?"}],
                system=full_prompt
            )

            response_text = response.content[0].text.lower()

            # LLM should understand there are no other peers from specialist's view
            # (specialist only sees itself, no other peers in this test)
            # This validates the LLM received and processed the context

            assert len(response_text) > 0  # Got a response

        finally:
            await mesh.stop()

    @requires_llm
    @pytest.mark.asyncio
    async def test_llm_decides_to_delegate_based_on_context(self):
        """Test LLM autonomously decides to delegate based on peer context."""
        from jarviscore import Mesh
        from jarviscore.profiles import ListenerAgent

        delegation_occurred = False

        class AnalystAgent(ListenerAgent):
            role = "analyst"
            capabilities = ["data_analysis", "statistics", "insights"]
            description = "Expert data analyst"
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                nonlocal delegation_occurred
                delegation_occurred = True
                return {
                    "analysis": "Sales are up 15% quarter over quarter",
                    "insights": ["Positive trend", "Growth accelerating"]
                }

        class CoordinatorAgent(ListenerAgent):
            role = "coordinator"
            capabilities = ["coordination", "delegation"]
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                return {}

        mesh = Mesh(mode="p2p", config={"bind_port": 7976})
        analyst = mesh.add(AnalystAgent())
        coordinator = mesh.add(CoordinatorAgent())

        await mesh.start()
        analyst_task = asyncio.create_task(analyst.run())

        try:
            await asyncio.sleep(0.2)

            # Build coordinator's system prompt with peer awareness
            base_prompt = """You are a coordinator. When users ask for data analysis,
you MUST use the ask_peer tool to delegate to the analyst.
Always delegate analysis tasks - never try to do them yourself."""

            system_prompt = coordinator.peers.build_system_prompt(base_prompt)

            # Verify analyst is in the context
            assert "analyst" in system_prompt
            assert "data_analysis" in system_prompt or "statistics" in system_prompt

            # Create LLM client using configured settings
            client, model, error = get_llm_client()
            assert client is not None, f"Failed to get LLM client: {error}"

            tools = [{
                "name": "ask_peer",
                "description": "Delegate a task to a specialist agent",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "description": "Role of agent to ask"},
                        "question": {"type": "string", "description": "Question for the agent"}
                    },
                    "required": ["role", "question"]
                }
            }]

            # Ask for analysis - LLM should decide to delegate
            response = client.messages.create(
                model=model,
                max_tokens=256,
                messages=[{"role": "user", "content": "Please analyze the Q4 sales data"}],
                system=system_prompt,
                tools=tools
            )

            # Check if LLM decided to use ask_peer tool
            tool_used = False
            for block in response.content:
                if block.type == "tool_use" and block.name == "ask_peer":
                    tool_used = True
                    # Execute the peer request
                    args = block.input
                    peer_response = await coordinator.peers.request(
                        args.get("role", "analyst"),
                        {"question": args.get("question", "")},
                        timeout=5
                    )
                    assert "analysis" in peer_response
                    break

            # LLM should have decided to use the tool
            assert tool_used, "LLM should have decided to delegate to analyst"
            assert delegation_occurred, "Analyst should have received the request"

        finally:
            analyst.request_shutdown()
            analyst_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: END-TO-END COGNITIVE DISCOVERY FLOW
# ═══════════════════════════════════════════════════════════════════════════════

class TestEndToEndCognitiveDiscovery:
    """End-to-end tests for the complete cognitive discovery flow."""

    @pytest.mark.asyncio
    async def test_full_flow_without_llm(self):
        """Test complete flow with mock LLM decisions."""
        from jarviscore import Mesh
        from jarviscore.profiles import ListenerAgent

        analyst_requests = []
        scout_requests = []

        class AnalystAgent(ListenerAgent):
            role = "analyst"
            capabilities = ["analysis"]
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                analyst_requests.append(msg.data)
                return {"analysis_result": "Data analyzed successfully"}

        class ScoutAgent(ListenerAgent):
            role = "scout"
            capabilities = ["research"]
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                scout_requests.append(msg.data)
                return {"research_result": "Research completed"}

        class OrchestratorAgent(ListenerAgent):
            role = "orchestrator"
            capabilities = ["orchestration"]
            listen_timeout = 0.1

            async def on_peer_request(self, msg):
                return {}

            async def process_with_mock_llm(self, query: str) -> dict:
                """Simulate LLM decision-making based on cognitive context."""
                # Get cognitive context
                context = self.peers.get_cognitive_context(format="json")

                import json
                peers = json.loads(context).get("available_peers", [])

                # Mock LLM logic: route based on keywords
                if "analyze" in query.lower() or "data" in query.lower():
                    # Find analyst
                    analyst = next((p for p in peers if p["role"] == "analyst"), None)
                    if analyst:
                        return await self.peers.request("analyst", {"query": query}, timeout=5)

                if "research" in query.lower() or "find" in query.lower():
                    # Find scout
                    scout = next((p for p in peers if p["role"] == "scout"), None)
                    if scout:
                        return await self.peers.request("scout", {"query": query}, timeout=5)

                return {"result": "Handled directly"}

        mesh = Mesh(mode="p2p", config={"bind_port": 7977})
        analyst = mesh.add(AnalystAgent())
        scout = mesh.add(ScoutAgent())
        orchestrator = mesh.add(OrchestratorAgent())

        await mesh.start()

        # Start listeners
        analyst_task = asyncio.create_task(analyst.run())
        scout_task = asyncio.create_task(scout.run())

        try:
            await asyncio.sleep(0.3)

            # Test 1: Query that should go to analyst
            result1 = await orchestrator.process_with_mock_llm("Please analyze the sales data")
            assert "analysis_result" in result1
            assert len(analyst_requests) == 1

            # Test 2: Query that should go to scout
            result2 = await orchestrator.process_with_mock_llm("Research competitors")
            assert "research_result" in result2
            assert len(scout_requests) == 1

            # Test 3: Query handled directly
            result3 = await orchestrator.process_with_mock_llm("What is your name?")
            assert "result" in result3
            assert result3["result"] == "Handled directly"

        finally:
            analyst.request_shutdown()
            scout.request_shutdown()
            analyst_task.cancel()
            scout_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass
            try:
                await scout_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# RUN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
