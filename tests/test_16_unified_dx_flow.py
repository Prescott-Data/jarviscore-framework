"""
Test 16: Unified DX Flow - Autonomous Agents with Mesh as Tool

Tests the COMPLETE real-world flow combining all DX improvements:
1. FastAPI Integration (JarvisLifespan)
2. ListenerAgent Profile
3. Cognitive Discovery (get_cognitive_context)
4. LLM Autonomous Delegation - Each agent has mesh as a TOOL
5. Peer-to-Peer Communication - No coordinator, any agent can talk to any agent

Key Pattern Tested:
    Each agent has the MESH as a TOOL
    Agent A (LLM) → discovers peers via get_cognitive_context()
    Agent A → delegates to Agent B via ask_peer tool
    Agent B responds → Agent A synthesizes response

Run with: pytest tests/test_16_unified_dx_flow.py -v -s
"""
import asyncio
import os
import sys
import pytest
import logging
from unittest.mock import MagicMock

sys.path.insert(0, '.')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM CLIENT HELPER
# ═══════════════════════════════════════════════════════════════════════════════

def get_llm_client():
    """Get configured LLM client from settings."""
    try:
        from jarviscore.config import settings
        from anthropic import Anthropic

        api_key = settings.claude_api_key or os.environ.get("CLAUDE_API_KEY")
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


def has_valid_llm():
    """Check if LLM is available."""
    try:
        client, model, error = get_llm_client()
        if error:
            return False
        client.messages.create(model=model, max_tokens=10, messages=[{"role": "user", "content": "Hi"}])
        return True
    except:
        return False


_llm_available = None
def llm_is_available():
    global _llm_available
    if _llm_available is None:
        _llm_available = has_valid_llm()
    return _llm_available


requires_llm = pytest.mark.skipif(not llm_is_available(), reason="No valid LLM API key")


# ═══════════════════════════════════════════════════════════════════════════════
# AUTONOMOUS AGENT BASE - Each agent has mesh as a tool
# ═══════════════════════════════════════════════════════════════════════════════

def create_llm_agent_class():
    """Create the LLMAgent base class."""
    from jarviscore.profiles import ListenerAgent

    class LLMAgent(ListenerAgent):
        """
        Base for LLM-powered agents that can discover and delegate to peers.

        KEY PATTERN: The mesh is a TOOL for the LLM.
        - get_cognitive_context() tells LLM who's available
        - ask_peer tool lets LLM delegate to specialists
        - Each agent is autonomous - no central coordinator needed
        """
        listen_timeout = 0.1
        system_prompt = "You are a helpful agent."

        async def setup(self):
            await super().setup()
            self.llm_client, self.llm_model, _ = get_llm_client()

        def _get_tools(self):
            """Get tools for LLM - includes ask_peer for mesh communication."""
            return [{
                "name": "ask_peer",
                "description": "Ask another agent in the mesh for help. Use this to delegate tasks to specialists.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string", "description": "Role of the agent to ask (e.g., 'analyst', 'researcher')"},
                        "question": {"type": "string", "description": "The question or task for that agent"}
                    },
                    "required": ["role", "question"]
                }
            }]

        async def _ask_peer(self, role: str, question: str) -> dict:
            """Execute ask_peer tool - send request to another agent."""
            response = await self.peers.request(role, {"question": question}, timeout=30)
            return response

        async def chat(self, message: str) -> dict:
            """
            Process a message with LLM that can discover and delegate to peers.

            This is the CORE PATTERN:
            1. Build system prompt with WHO I AM + WHO ELSE IS AVAILABLE
            2. LLM sees available peers as potential helpers
            3. LLM decides whether to handle directly or delegate
            """
            if not self.llm_client:
                return await self._chat_mock(message)

            # DYNAMIC DISCOVERY: Tell LLM who it is and who else is available
            peer_context = self.peers.get_cognitive_context() if self.peers else ""

            system = f"""{self.system_prompt}

{peer_context}"""

            response = self.llm_client.messages.create(
                model=self.llm_model,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": message}],
                tools=self._get_tools()
            )

            # Handle tool use - check for tool_use FIRST (prioritize over text)
            tool_use_block = None
            text_content = None

            for block in response.content:
                if block.type == "tool_use" and block.name == "ask_peer":
                    tool_use_block = block
                elif hasattr(block, 'text'):
                    text_content = block.text

            if tool_use_block:
                role = tool_use_block.input.get("role")
                question = tool_use_block.input.get("question")

                peer_response = await self._ask_peer(role, question)

                # Continue with tool result
                messages = [{"role": "user", "content": message}]
                messages.append({"role": "assistant", "content": response.content})
                messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_use_block.id, "content": str(peer_response)}]
                })

                final = self.llm_client.messages.create(
                    model=self.llm_model,
                    max_tokens=1024,
                    system=system,
                    messages=messages
                )

                for block in final.content:
                    if hasattr(block, 'text'):
                        return {"response": block.text, "delegated_to": role, "peer_response": peer_response}

            return {"response": text_content or "Processed.", "delegated_to": None}

        async def _chat_mock(self, message: str) -> dict:
            """Mock when LLM unavailable - for testing basic flow."""
            # Determine if we should delegate based on keywords
            msg_lower = message.lower()
            if any(w in msg_lower for w in ["analyze", "analysis", "data", "statistics", "insights"]):
                response = await self._ask_peer("analyst", message)
                return {"response": "Analysis complete", "delegated_to": "analyst", "peer_response": response}
            if any(w in msg_lower for w in ["research", "search", "find", "investigate"]):
                response = await self._ask_peer("researcher", message)
                return {"response": "Research complete", "delegated_to": "researcher", "peer_response": response}
            return {"response": f"[{self.role}] Processed: {message}", "delegated_to": None}

        async def on_peer_request(self, msg):
            """Handle requests from other agents."""
            return await self.chat(msg.data.get("question", ""))

    return LLMAgent


def create_autonomous_agents():
    """Create autonomous agents where each has the mesh as a tool."""
    LLMAgent = create_llm_agent_class()

    class AssistantAgent(LLMAgent):
        """General assistant that can delegate to specialists."""
        role = "assistant"
        capabilities = ["chat", "general_help", "delegation"]
        description = "General assistant that delegates specialized tasks to experts"

        system_prompt = """You are a helpful assistant. You can answer general questions directly.

For specialized tasks, you have access to other agents via the ask_peer tool:
- For data analysis, statistics, or insights → ask the "analyst" agent
- For research or information gathering → ask the "researcher" agent

Use ask_peer when the task requires specialized expertise. Be helpful and concise."""

    class AnalystAgent(LLMAgent):
        """Data analysis specialist with LLM."""
        role = "analyst"
        capabilities = ["data_analysis", "statistics", "insights", "reporting"]
        description = "Expert data analyst for statistics and insights"

        system_prompt = """You are an expert data analyst. You specialize in:
- Statistical analysis
- Data insights and trends
- Business metrics and KPIs
- Data visualization recommendations

Provide clear, actionable insights. If you need research data, you can ask the "researcher" agent."""

        async def on_peer_request(self, msg):
            """Handle analysis requests - return structured analysis."""
            question = msg.data.get("question", "")

            if self.llm_client:
                response = self.llm_client.messages.create(
                    model=self.llm_model,
                    max_tokens=512,
                    system=self.system_prompt,
                    messages=[{"role": "user", "content": f"Analyze this request: {question}"}]
                )
                for block in response.content:
                    if hasattr(block, 'text'):
                        return {"analysis": block.text, "confidence": 0.9}

            # Mock response for testing
            return {
                "analysis": f"Analysis of: {question}",
                "findings": ["Revenue up 15%", "Costs down 8%", "Growth trend positive"],
                "confidence": 0.85
            }

    class ResearcherAgent(LLMAgent):
        """Research specialist with LLM."""
        role = "researcher"
        capabilities = ["research", "web_search", "fact_checking", "information_gathering"]
        description = "Research specialist for gathering and verifying information"

        system_prompt = """You are an expert researcher. You specialize in:
- Information gathering
- Fact checking
- Market research
- Competitive analysis

Provide well-sourced, accurate information. If you need data analysis, you can ask the "analyst" agent."""

        async def on_peer_request(self, msg):
            """Handle research requests - return structured research."""
            question = msg.data.get("question", "")

            if self.llm_client:
                response = self.llm_client.messages.create(
                    model=self.llm_model,
                    max_tokens=512,
                    system=self.system_prompt,
                    messages=[{"role": "user", "content": f"Research this topic: {question}"}]
                )
                for block in response.content:
                    if hasattr(block, 'text'):
                        return {"research": block.text, "sources": ["Internal analysis"]}

            # Mock response for testing
            return {
                "research": f"Research on: {question}",
                "sources": ["Industry Report 2024", "Market Analysis"],
                "summary": "Research findings compiled"
            }

    return AssistantAgent, AnalystAgent, ResearcherAgent


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: AUTONOMOUS DISCOVERY - Each agent discovers peers
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomousDiscovery:
    """Test that each agent autonomously discovers peers."""

    @pytest.mark.asyncio
    async def test_assistant_discovers_all_specialists(self):
        """Test assistant agent sees all specialist peers."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7990})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        try:
            # Assistant should see both specialists
            peers = assistant.peers.list_peers()
            roles = [p['role'] for p in peers]

            assert "analyst" in roles, "Assistant should see analyst"
            assert "researcher" in roles, "Assistant should see researcher"

            # Cognitive context should include both
            context = assistant.peers.get_cognitive_context()
            assert "analyst" in context
            assert "researcher" in context
            assert "data_analysis" in context
            assert "research" in context

        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_analyst_can_see_other_agents(self):
        """Test analyst agent can see assistant and researcher."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7991})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        try:
            # Analyst should see both other agents
            peers = analyst.peers.list_peers()
            roles = [p['role'] for p in peers]

            assert "assistant" in roles, "Analyst should see assistant"
            assert "researcher" in roles, "Analyst should see researcher"

        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_all_agents_have_bidirectional_visibility(self):
        """Test all agents can see all other agents (true peer-to-peer)."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7992})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        try:
            # Each agent should see the other two
            for agent in [assistant, analyst, researcher]:
                peers = agent.peers.list_peers()
                other_roles = [p['role'] for p in peers]

                # Should see exactly 2 other agents
                assert len(other_roles) == 2, f"{agent.role} should see 2 peers, got {len(other_roles)}"

        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: AUTONOMOUS DELEGATION - Any agent can delegate to any other
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomousDelegation:
    """Test autonomous delegation between agents."""

    @requires_llm
    @pytest.mark.asyncio
    async def test_assistant_delegates_to_analyst(self):
        """Test assistant autonomously delegates analysis to analyst."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7993})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        # Start listeners
        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())

        try:
            await asyncio.sleep(0.3)

            # Query that should be delegated to analyst - be explicit
            result = await assistant.chat(
                "Please analyze the Q4 2024 sales data and provide statistical insights on revenue trends"
            )

            assert result["delegated_to"] == "analyst", f"Expected delegation to analyst, got {result.get('delegated_to')}"
            assert "peer_response" in result
            assert "findings" in result["peer_response"] or "analysis" in result["peer_response"]

        finally:
            analyst.request_shutdown()
            researcher.request_shutdown()
            analyst_task.cancel()
            researcher_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass
            try:
                await researcher_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()

    @requires_llm
    @pytest.mark.asyncio
    async def test_assistant_delegates_to_researcher(self):
        """Test assistant autonomously delegates research to researcher."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7994})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())

        try:
            await asyncio.sleep(0.3)

            # Query that should be delegated to researcher - be explicit
            result = await assistant.chat(
                "Research our main competitors and gather information about their market positioning"
            )

            assert result["delegated_to"] == "researcher", f"Expected delegation to researcher, got {result.get('delegated_to')}"
            assert "peer_response" in result
            assert "sources" in result["peer_response"] or "research" in result["peer_response"]

        finally:
            analyst.request_shutdown()
            researcher.request_shutdown()
            analyst_task.cancel()
            researcher_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass
            try:
                await researcher_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: FASTAPI INTEGRATION - JarvisLifespan with autonomous agents
# ═══════════════════════════════════════════════════════════════════════════════

class TestFastAPIIntegration:
    """Test FastAPI + JarvisLifespan with autonomous agents."""

    @pytest.mark.asyncio
    async def test_jarvis_lifespan_starts_all_agents(self):
        """Test JarvisLifespan correctly initializes all agents."""
        from jarviscore.integrations import JarvisLifespan

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        agents = [AssistantAgent(), AnalystAgent(), ResearcherAgent()]
        lifespan = JarvisLifespan(agents, mode="p2p", bind_port=7995)

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        async with lifespan(mock_app):
            # All agents should be registered
            assert "assistant" in mock_app.state.jarvis_agents
            assert "analyst" in mock_app.state.jarvis_agents
            assert "researcher" in mock_app.state.jarvis_agents

            # Mesh should be started
            assert lifespan.mesh is not None
            assert lifespan.mesh._started is True

            # Each agent should see others
            assistant = mock_app.state.jarvis_agents["assistant"]
            peers = assistant.peers.list_peers()
            roles = [p['role'] for p in peers]

            assert "analyst" in roles
            assert "researcher" in roles

    @requires_llm
    @pytest.mark.asyncio
    async def test_fastapi_flow_assistant_to_analyst(self):
        """Test complete HTTP → Assistant → Analyst → Response flow."""
        from jarviscore.integrations import JarvisLifespan

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        agents = [AssistantAgent(), AnalystAgent(), ResearcherAgent()]
        lifespan = JarvisLifespan(agents, mode="p2p", bind_port=7996)

        mock_app = MagicMock()
        mock_app.state = MagicMock()

        async with lifespan(mock_app):
            assistant = mock_app.state.jarvis_agents["assistant"]
            analyst = mock_app.state.jarvis_agents["analyst"]
            researcher = mock_app.state.jarvis_agents["researcher"]

            # Start listeners
            analyst_task = asyncio.create_task(analyst.run())
            researcher_task = asyncio.create_task(researcher.run())

            try:
                await asyncio.sleep(0.3)

                # Simulate HTTP request → assistant processing - be explicit
                result = await assistant.chat(
                    "Please analyze the Q4 2024 revenue data and provide detailed statistical insights on trends"
                )

                # Should have delegated to analyst
                assert result["delegated_to"] == "analyst"
                assert result["peer_response"] is not None

            finally:
                analyst.request_shutdown()
                researcher.request_shutdown()
                analyst_task.cancel()
                researcher_task.cancel()
                try:
                    await analyst_task
                except asyncio.CancelledError:
                    pass
                try:
                    await researcher_task
                except asyncio.CancelledError:
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: REAL LLM INTEGRATION - Autonomous delegation with actual LLM
# ═══════════════════════════════════════════════════════════════════════════════

class TestRealLLMAutonomousDelegation:
    """Test the complete flow with real LLM integration."""

    @requires_llm
    @pytest.mark.asyncio
    async def test_llm_autonomously_delegates_to_analyst(self):
        """Test LLM-powered assistant autonomously delegates to analyst."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7997})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())

        try:
            await asyncio.sleep(0.3)

            # Verify LLM is available
            assert assistant.llm_client is not None, "LLM client should be available"

            # Verify assistant sees peers
            context = assistant.peers.get_cognitive_context()
            assert "analyst" in context, "Assistant should see analyst in context"

            # Query that should trigger delegation
            result = await assistant.chat(
                "Please analyze the Q4 2024 sales data and provide key insights"
            )

            # LLM should have delegated to analyst
            assert result["delegated_to"] == "analyst", \
                f"LLM should delegate to analyst, got: {result.get('delegated_to')}"
            assert result["peer_response"] is not None

        finally:
            analyst.request_shutdown()
            researcher.request_shutdown()
            analyst_task.cancel()
            researcher_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass
            try:
                await researcher_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()

    @requires_llm
    @pytest.mark.asyncio
    async def test_llm_autonomously_delegates_to_researcher(self):
        """Test LLM-powered assistant autonomously delegates to researcher."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7998})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        analyst_task = asyncio.create_task(analyst.run())
        researcher_task = asyncio.create_task(researcher.run())

        try:
            await asyncio.sleep(0.3)

            # Query that should trigger research delegation
            result = await assistant.chat(
                "Research our main competitors and their market positioning"
            )

            # LLM should have delegated to researcher
            assert result["delegated_to"] == "researcher", \
                f"LLM should delegate to researcher, got: {result.get('delegated_to')}"
            assert result["peer_response"] is not None

        finally:
            analyst.request_shutdown()
            researcher.request_shutdown()
            analyst_task.cancel()
            researcher_task.cancel()
            try:
                await analyst_task
            except asyncio.CancelledError:
                pass
            try:
                await researcher_task
            except asyncio.CancelledError:
                pass
            await mesh.stop()

    @requires_llm
    @pytest.mark.asyncio
    async def test_llm_responds_directly_without_delegation(self):
        """Test LLM responds directly for general questions without delegation."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 7999})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        try:
            await asyncio.sleep(0.3)

            # General question that doesn't need delegation
            result = await assistant.chat("What is 2 + 2?")

            # Should NOT delegate
            assert result["delegated_to"] is None, \
                f"LLM should not delegate for simple questions, got: {result.get('delegated_to')}"
            assert "response" in result

        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: COGNITIVE CONTEXT ACCURACY
# ═══════════════════════════════════════════════════════════════════════════════

class TestCognitiveContextAccuracy:
    """Test that cognitive context accurately represents the mesh."""

    @pytest.mark.asyncio
    async def test_cognitive_context_includes_all_peer_details(self):
        """Test cognitive context includes roles, capabilities, descriptions."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 8000})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        researcher = mesh.add(ResearcherAgent())

        await mesh.start()

        try:
            context = assistant.peers.get_cognitive_context(format="markdown")

            # Should include roles
            assert "analyst" in context
            assert "researcher" in context

            # Should include capabilities
            assert "data_analysis" in context or "statistics" in context
            assert "research" in context or "web_search" in context

            # Should include delegation instructions
            assert "ask_peer" in context

        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_build_system_prompt_combines_base_and_context(self):
        """Test build_system_prompt properly combines base prompt with peer context."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()

        mesh = Mesh(mode="p2p", config={"bind_port": 8001})
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())

        await mesh.start()

        try:
            base_prompt = "You are a helpful assistant."
            full_prompt = assistant.peers.build_system_prompt(base_prompt)

            # Should include base prompt
            assert "You are a helpful assistant" in full_prompt

            # Should include peer context
            assert "AVAILABLE MESH PEERS" in full_prompt
            assert "analyst" in full_prompt

        finally:
            await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST: CLOUD DEPLOYMENT - Standalone agent joining mesh (Day 2)
# ═══════════════════════════════════════════════════════════════════════════════

def create_standalone_scout_agent():
    """Create a standalone scout agent for cloud deployment testing."""
    LLMAgent = create_llm_agent_class()

    class ScoutAgent(LLMAgent):
        """Standalone agent that joins an existing mesh."""
        role = "scout"
        capabilities = ["scouting", "reconnaissance", "market_intel"]
        description = "Scout agent for market intelligence"

        system_prompt = """You are a scout agent. You gather market intelligence."""

        async def on_peer_request(self, msg):
            question = msg.data.get("question", "")
            return {
                "intel": f"Scouting report on: {question}",
                "signals": ["Emerging trend detected"],
                "confidence": 0.8
            }

    return ScoutAgent


class TestCloudDeployment:
    """Test Day 2 cloud deployment patterns - standalone agents joining mesh."""

    @pytest.mark.asyncio
    async def test_agent_has_join_mesh_method(self):
        """Test that agents have join_mesh method."""
        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()
        agent = AssistantAgent()

        assert hasattr(agent, 'join_mesh'), "Agent should have join_mesh method"
        assert hasattr(agent, 'leave_mesh'), "Agent should have leave_mesh method"
        assert hasattr(agent, 'is_mesh_connected'), "Agent should have is_mesh_connected property"

    @pytest.mark.asyncio
    async def test_agent_is_mesh_connected_initially_false(self):
        """Test that agent is not connected before join_mesh."""
        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()
        agent = AssistantAgent()

        assert agent.is_mesh_connected is False, "Agent should not be connected initially"

    @pytest.mark.asyncio
    async def test_standalone_agent_visibility_after_mesh_add(self):
        """Test that all agents added before mesh.start() are visible to each other."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()
        ScoutAgent = create_standalone_scout_agent()

        mesh = Mesh(mode="p2p", config={"bind_port": 8002})

        # Add ALL agents before mesh.start() - this is the standard pattern
        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        scout = mesh.add(ScoutAgent())

        await mesh.start()

        try:
            # Assistant should see analyst and scout
            assistant_peers = assistant.peers.list_peers()
            assistant_roles = [p['role'] for p in assistant_peers]
            assert "analyst" in assistant_roles
            assert "scout" in assistant_roles, "Assistant should see scout"

            # Scout should see assistant and analyst
            scout_peers = scout.peers.list_peers()
            scout_roles = [p['role'] for p in scout_peers]
            assert "assistant" in scout_roles
            assert "analyst" in scout_roles

            # Analyst should see assistant and scout
            analyst_peers = analyst.peers.list_peers()
            analyst_roles = [p['role'] for p in analyst_peers]
            assert "assistant" in analyst_roles
            assert "scout" in analyst_roles

        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_cognitive_context_updates_with_new_agent(self):
        """Test that cognitive context reflects newly joined agents."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()
        ScoutAgent = create_standalone_scout_agent()

        mesh = Mesh(mode="p2p", config={"bind_port": 8003})

        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())

        await mesh.start()

        try:
            # Get context before adding scout
            context_before = assistant.peers.get_cognitive_context()
            assert "scout" not in context_before

            # Add scout
            scout = mesh.add(ScoutAgent())

            # Context should now include scout
            context_after = assistant.peers.get_cognitive_context()
            assert "scout" in context_after, "Cognitive context should include scout"
            assert "scouting" in context_after or "reconnaissance" in context_after

        finally:
            await mesh.stop()

    @pytest.mark.asyncio
    async def test_existing_agents_can_communicate_with_new_agent(self):
        """Test that existing agents can send requests to newly added agents."""
        from jarviscore import Mesh

        AssistantAgent, AnalystAgent, ResearcherAgent = create_autonomous_agents()
        ScoutAgent = create_standalone_scout_agent()

        mesh = Mesh(mode="p2p", config={"bind_port": 8004})

        assistant = mesh.add(AssistantAgent())
        analyst = mesh.add(AnalystAgent())
        scout = mesh.add(ScoutAgent())

        await mesh.start()

        # Start scout listener
        scout_task = asyncio.create_task(scout.run())

        try:
            await asyncio.sleep(0.2)

            # Assistant sends request to scout
            response = await assistant.peers.request(
                "scout",
                {"question": "What are the market trends?"},
                timeout=5
            )

            assert response is not None
            assert "intel" in response or "signals" in response

        finally:
            scout.request_shutdown()
            scout_task.cancel()
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
