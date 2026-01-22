"""
Test 10: Distributed Mode - CustomAgent Profile with Real LLM

Tests the CustomAgent profile in distributed execution mode:
- CustomAgent with user-controlled LLM integration
- CustomAgent with peer tools for agent communication
- Workflow execution with CustomAgents
- Multi-agent collaboration via peer tools

This file uses REAL LLM API calls (not mocks).

Run with: pytest tests/test_10_distributed_customagent.py -v -s
"""
import asyncio
import sys
import pytest
import logging

sys.path.insert(0, '.')

from jarviscore import Mesh
from jarviscore.profiles.customagent import CustomAgent
from jarviscore.p2p.peer_client import PeerClient

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Skip all tests if no API key is configured
try:
    from jarviscore.config import settings
    HAS_API_KEY = bool(
        settings.claude_api_key or
        settings.azure_api_key or
        settings.gemini_api_key
    )
except Exception:
    HAS_API_KEY = False

pytestmark = pytest.mark.skipif(
    not HAS_API_KEY,
    reason="No LLM API key configured in .env"
)


# ═══════════════════════════════════════════════════════════════════════════════
# REAL LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class RealLLMClient:
    """Real LLM client with tool calling support."""

    def __init__(self):
        from anthropic import Anthropic
        from jarviscore.config import settings

        api_key = settings.claude_api_key
        endpoint = settings.claude_endpoint

        if not api_key:
            raise RuntimeError("No Claude API key found")

        if endpoint:
            self.client = Anthropic(api_key=api_key, base_url=endpoint)
        else:
            self.client = Anthropic(api_key=api_key)

        self.model = settings.claude_model or "claude-sonnet-4-20250514"

    def chat(self, messages: list, system: str = None, max_tokens: int = 1024) -> str:
        """Simple chat without tools."""
        request_kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            request_kwargs["system"] = system

        response = self.client.messages.create(**request_kwargs)
        return response.content[0].text

    def chat_with_tools(
        self,
        messages: list,
        tools: list,
        system: str = None,
        max_tokens: int = 1024
    ) -> dict:
        """Chat with tool support."""
        request_kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            request_kwargs["system"] = system
        if tools:
            request_kwargs["tools"] = tools

        response = self.client.messages.create(**request_kwargs)

        result = {"stop_reason": response.stop_reason}
        for block in response.content:
            if block.type == "text":
                result["type"] = "text"
                result["content"] = block.text
            elif block.type == "tool_use":
                result["type"] = "tool_use"
                result["tool_name"] = block.name
                result["tool_args"] = block.input
                result["tool_use_id"] = block.id

        return result

    def continue_with_tool_result(
        self,
        messages: list,
        tool_use_id: str,
        tool_result: str,
        tools: list = None,
        system: str = None,
        max_tokens: int = 1024
    ) -> dict:
        """Continue with tool result."""
        messages = messages + [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": tool_result
                    }
                ]
            }
        ]
        return self.chat_with_tools(messages, tools or [], system, max_tokens)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CUSTOMAGENTS WITH LLM
# ═══════════════════════════════════════════════════════════════════════════════

class LLMResearchAgent(CustomAgent):
    """CustomAgent that uses LLM for research and reasoning."""
    role = "researcher"
    capabilities = ["research", "analysis", "summarization"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None
        self.requests_received = []

    async def setup(self):
        await super().setup()
        self.llm = RealLLMClient()
        self._logger.info(f"[{self.role}] LLM initialized")

    def get_tools(self) -> list:
        """Return tools including peer tools if available."""
        tools = [
            {
                "name": "search_knowledge",
                "description": "Search internal knowledge base for information",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            }
        ]
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool."""
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)
        if tool_name == "search_knowledge":
            return f"Knowledge base results for '{args.get('query')}': Found relevant information on the topic."
        return f"Unknown tool: {tool_name}"

    async def execute_task(self, task):
        """Execute research task using LLM."""
        task_desc = task.get("task", "")
        self._logger.info(f"[{self.role}] Executing: {task_desc[:50]}...")

        system_prompt = (
            "You are an expert researcher. Analyze the given topic and provide "
            "a concise but thorough response. Be factual and precise."
        )

        messages = [{"role": "user", "content": task_desc}]
        tools = self.get_tools()
        # Remove peer tools to avoid complexity in basic tests
        tools = [t for t in tools if t["name"] not in ["ask_peer", "broadcast_update", "list_peers"]]

        response = self.llm.chat_with_tools(messages, tools, system_prompt)

        # Handle tool use if needed
        if response.get("type") == "tool_use":
            tool_name = response["tool_name"]
            tool_args = response["tool_args"]
            tool_use_id = response["tool_use_id"]

            tool_result = await self.execute_tool(tool_name, tool_args)

            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tool_use_id, "name": tool_name, "input": tool_args}]
            })
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": tool_result}]
            })

            response = self.llm.chat_with_tools(messages, [], system_prompt)

        output = response.get("content", "Research complete.")

        return {
            "status": "success",
            "output": output,
            "agent_id": self.agent_id,
            "role": self.role
        }


class LLMWriterAgent(CustomAgent):
    """CustomAgent that uses LLM for writing tasks."""
    role = "writer"
    capabilities = ["writing", "editing", "formatting"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None

    async def setup(self):
        await super().setup()
        self.llm = RealLLMClient()
        self._logger.info(f"[{self.role}] LLM initialized")

    async def execute_task(self, task):
        """Execute writing task using LLM."""
        task_desc = task.get("task", "")
        context = task.get("context", {})

        self._logger.info(f"[{self.role}] Writing: {task_desc[:50]}...")

        system_prompt = (
            "You are an expert writer. Create clear, engaging content. "
            "Be concise but thorough. Format appropriately for the request."
        )

        # Include context from previous steps if available
        full_prompt = task_desc
        if context:
            full_prompt = f"Context from previous steps: {context}\n\nTask: {task_desc}"

        messages = [{"role": "user", "content": full_prompt}]
        output = self.llm.chat(messages, system_prompt)

        return {
            "status": "success",
            "output": output,
            "agent_id": self.agent_id,
            "role": self.role
        }


class LLMReviewerAgent(CustomAgent):
    """CustomAgent that reviews and provides feedback using LLM."""
    role = "reviewer"
    capabilities = ["review", "feedback", "quality_check"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None

    async def setup(self):
        await super().setup()
        self.llm = RealLLMClient()
        self._logger.info(f"[{self.role}] LLM initialized")

    async def execute_task(self, task):
        """Execute review task using LLM."""
        task_desc = task.get("task", "")
        context = task.get("context", {})

        self._logger.info(f"[{self.role}] Reviewing: {task_desc[:50]}...")

        system_prompt = (
            "You are an expert reviewer. Provide constructive feedback. "
            "Be specific about what works well and what could be improved. "
            "Keep feedback concise and actionable."
        )

        full_prompt = task_desc
        if context:
            full_prompt = f"Content to review: {context}\n\nReview task: {task_desc}"

        messages = [{"role": "user", "content": full_prompt}]
        output = self.llm.chat(messages, system_prompt)

        return {
            "status": "success",
            "output": output,
            "agent_id": self.agent_id,
            "role": self.role
        }


class PeerAwareAgent(CustomAgent):
    """CustomAgent that can communicate with peers via peer tools."""
    role = "coordinator"
    capabilities = ["coordination", "delegation"]

    def __init__(self, agent_id=None):
        super().__init__(agent_id)
        self.llm = None
        self.tool_calls = []

    async def setup(self):
        await super().setup()
        self.llm = RealLLMClient()
        self._logger.info(f"[{self.role}] LLM initialized with peer awareness")

    def get_tools(self) -> list:
        """Return tools including peer tools."""
        tools = []
        if self.peers:
            tools.extend(self.peers.as_tool().schema)
        return tools

    async def execute_tool(self, tool_name: str, args: dict) -> str:
        """Execute tool including peer tools."""
        self.tool_calls.append({"tool": tool_name, "args": args})
        if self.peers and tool_name in self.peers.as_tool().tool_names:
            return await self.peers.as_tool().execute(tool_name, args)
        return f"Unknown tool: {tool_name}"

    async def execute_task(self, task):
        """Execute task, potentially delegating to peers."""
        task_desc = task.get("task", "")
        self._logger.info(f"[{self.role}] Coordinating: {task_desc[:50]}...")

        system_prompt = (
            "You are a coordinator agent. You can delegate tasks to specialist peers. "
            "Use the ask_peer tool to get help from other agents when needed. "
            "Available peers include: researcher (for research tasks), writer (for writing), "
            "and reviewer (for reviews). Coordinate effectively."
        )

        tools = self.get_tools()
        if not tools:
            # No peers, just respond directly
            output = self.llm.chat([{"role": "user", "content": task_desc}], system_prompt)
            return {"status": "success", "output": output}

        messages = [{"role": "user", "content": task_desc}]
        response = self.llm.chat_with_tools(messages, tools, system_prompt)

        # Handle tool use loop
        iterations = 0
        while response.get("type") == "tool_use" and iterations < 3:
            iterations += 1

            tool_name = response["tool_name"]
            tool_args = response["tool_args"]
            tool_use_id = response["tool_use_id"]

            self._logger.info(f"[{self.role}] Using tool: {tool_name}")

            tool_result = await self.execute_tool(tool_name, tool_args)

            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tool_use_id, "name": tool_name, "input": tool_args}]
            })

            response = self.llm.continue_with_tool_result(
                messages, tool_use_id, tool_result, tools, system_prompt
            )

        output = response.get("content", "Coordination complete.")

        return {
            "status": "success",
            "output": output,
            "tool_calls": self.tool_calls,
            "agent_id": self.agent_id,
            "role": self.role
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def distributed_mesh_single():
    """Create distributed mesh with single CustomAgent."""
    mesh = Mesh(mode="distributed", config={'bind_port': 7990})
    agent = mesh.add(LLMResearchAgent)

    await mesh.start()

    yield mesh, agent

    await mesh.stop()


@pytest.fixture
async def distributed_mesh_pipeline():
    """Create distributed mesh with multiple CustomAgents for pipeline."""
    mesh = Mesh(mode="distributed", config={'bind_port': 7991})

    researcher = mesh.add(LLMResearchAgent)
    writer = mesh.add(LLMWriterAgent)
    reviewer = mesh.add(LLMReviewerAgent)

    await mesh.start()

    yield mesh, researcher, writer, reviewer

    await mesh.stop()


@pytest.fixture
async def distributed_mesh_with_peers():
    """Create distributed mesh with peer-aware agents."""
    mesh = Mesh(mode="distributed", config={'bind_port': 7992})

    coordinator = mesh.add(PeerAwareAgent)
    researcher = mesh.add(LLMResearchAgent)
    writer = mesh.add(LLMWriterAgent)

    await mesh.start()

    # Wire up peer clients for peer communication
    for agent in mesh.agents:
        agent.peers = PeerClient(
            coordinator=mesh._p2p_coordinator,
            agent_id=agent.agent_id,
            agent_role=agent.role,
            agent_registry=mesh._agent_registry,
            node_id="local"
        )

    yield mesh, coordinator, researcher, writer

    await mesh.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: CustomAgent Setup in Distributed Mode
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomAgentDistributedSetup:
    """Tests for CustomAgent initialization in distributed mode."""

    @pytest.mark.asyncio
    async def test_customagent_inherits_from_profile(self, distributed_mesh_single):
        """CustomAgent should inherit from Profile."""
        mesh, agent = distributed_mesh_single

        from jarviscore.core.profile import Profile
        from jarviscore.core.agent import Agent

        assert isinstance(agent, Profile)
        assert isinstance(agent, Agent)
        assert isinstance(agent, CustomAgent)

    @pytest.mark.asyncio
    async def test_customagent_has_required_attributes(self, distributed_mesh_single):
        """CustomAgent should have role and capabilities."""
        mesh, agent = distributed_mesh_single

        assert agent.role == "researcher"
        assert "research" in agent.capabilities
        assert "analysis" in agent.capabilities

    @pytest.mark.asyncio
    async def test_customagent_setup_initializes_llm(self, distributed_mesh_single):
        """CustomAgent setup should initialize LLM client."""
        mesh, agent = distributed_mesh_single

        assert agent.llm is not None, "LLM should be initialized"
        assert isinstance(agent.llm, RealLLMClient)

    @pytest.mark.asyncio
    async def test_customagent_joins_distributed_mesh(self, distributed_mesh_single):
        """CustomAgent should be registered in distributed mesh."""
        mesh, agent = distributed_mesh_single

        assert mesh.get_agent("researcher") == agent
        assert mesh._p2p_coordinator is not None
        assert mesh._workflow_engine is not None


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: CustomAgent Workflow Execution
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomAgentWorkflowExecution:
    """Tests for CustomAgent executing workflow steps with real LLM."""

    @pytest.mark.asyncio
    async def test_customagent_executes_single_step(self, distributed_mesh_single):
        """CustomAgent should execute a single workflow step."""
        mesh, agent = distributed_mesh_single

        print("\n" + "="*60)
        print("TEST: CustomAgent executes single step")
        print("="*60)

        results = await mesh.workflow("single-step", [
            {"agent": "researcher", "task": "What are the three laws of thermodynamics? Summarize briefly."}
        ])

        print(f"\nResults: {results}")

        assert len(results) == 1
        result = results[0]

        assert result["status"] == "success", f"Task failed: {result.get('error')}"
        assert "output" in result
        assert len(result["output"]) > 0

        print(f"\nOutput: {result['output'][:300]}...")

    @pytest.mark.asyncio
    async def test_customagent_uses_llm_for_reasoning(self, distributed_mesh_single):
        """CustomAgent should use LLM for complex reasoning."""
        mesh, agent = distributed_mesh_single

        print("\n" + "="*60)
        print("TEST: CustomAgent uses LLM for reasoning")
        print("="*60)

        results = await mesh.workflow("reasoning-test", [
            {
                "agent": "researcher",
                "task": "Compare and contrast renewable vs non-renewable energy sources. List 3 pros and cons of each."
            }
        ])

        result = results[0]
        assert result["status"] == "success"

        output = result["output"]
        print(f"\nOutput: {output[:500]}...")

        # Should contain substantive content
        assert len(output) > 100, "Should have detailed response"

    @pytest.mark.asyncio
    async def test_customagent_result_includes_metadata(self, distributed_mesh_single):
        """CustomAgent result should include agent metadata."""
        mesh, agent = distributed_mesh_single

        results = await mesh.workflow("metadata-test", [
            {"agent": "researcher", "task": "Define photosynthesis in one sentence."}
        ])

        result = results[0]
        assert result["status"] == "success"
        assert "agent_id" in result
        assert "role" in result
        assert result["role"] == "researcher"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: Multi-Step Pipeline with CustomAgents
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomAgentMultiStepWorkflow:
    """Tests for multi-step workflows with multiple CustomAgents."""

    @pytest.mark.asyncio
    async def test_two_customagents_sequential(self, distributed_mesh_pipeline):
        """Two CustomAgents should execute in sequence."""
        mesh, researcher, writer, reviewer = distributed_mesh_pipeline

        print("\n" + "="*60)
        print("TEST: Two CustomAgents in sequence")
        print("="*60)

        results = await mesh.workflow("two-agent-test", [
            {
                "agent": "researcher",
                "task": "List 3 key facts about the Python programming language."
            },
            {
                "agent": "writer",
                "task": "Write a short promotional paragraph about Python using these facts: Python is versatile, has a large community, and is easy to learn."
            }
        ])

        print(f"\nResults count: {len(results)}")
        for i, r in enumerate(results):
            print(f"Step {i+1}: {r['status']} - {str(r.get('output', ''))[:100]}...")

        assert len(results) == 2
        assert results[0]["status"] == "success"
        assert results[1]["status"] == "success"

    @pytest.mark.asyncio
    async def test_three_agent_pipeline(self, distributed_mesh_pipeline):
        """Three CustomAgents should work in a pipeline."""
        mesh, researcher, writer, reviewer = distributed_mesh_pipeline

        print("\n" + "="*60)
        print("TEST: Three agent content pipeline")
        print("="*60)

        results = await mesh.workflow("content-pipeline", [
            {
                "agent": "researcher",
                "task": "Provide 3 interesting facts about machine learning."
            },
            {
                "agent": "writer",
                "task": "Write a brief blog introduction about machine learning mentioning these facts: ML learns from data, it improves over time, and it powers many modern applications."
            },
            {
                "agent": "reviewer",
                "task": "Review this blog intro and suggest one improvement: 'Machine learning is transforming how we interact with technology every day.'"
            }
        ])

        print(f"\nPipeline results:")
        for i, r in enumerate(results):
            print(f"  Step {i+1} [{r['status']}]: {str(r.get('output', ''))[:80]}...")

        assert len(results) == 3
        successes = sum(1 for r in results if r["status"] == "success")
        assert successes >= 2, "At least 2 steps should succeed"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST CLASS: CustomAgent with Peer Tools
# ═══════════════════════════════════════════════════════════════════════════════

class TestCustomAgentWithPeerTools:
    """Tests for CustomAgent using peer tools in distributed mode."""

    @pytest.mark.asyncio
    async def test_customagent_has_peer_tools(self, distributed_mesh_with_peers):
        """CustomAgent should have access to peer tools."""
        mesh, coordinator, researcher, writer = distributed_mesh_with_peers

        tools = coordinator.get_tools()
        tool_names = [t["name"] for t in tools]

        print(f"\nCoordinator tools: {tool_names}")

        assert "ask_peer" in tool_names
        assert "list_peers" in tool_names
        assert "broadcast_update" in tool_names

    @pytest.mark.asyncio
    async def test_customagent_can_list_peers(self, distributed_mesh_with_peers):
        """CustomAgent should be able to list available peers."""
        mesh, coordinator, researcher, writer = distributed_mesh_with_peers

        peers = coordinator.peers.list_peers()
        roles = [p["role"] for p in peers]

        print(f"\nAvailable peers: {roles}")

        assert "researcher" in roles
        assert "writer" in roles

    @pytest.mark.asyncio
    async def test_customagent_peer_communication(self, distributed_mesh_with_peers):
        """CustomAgent should communicate with peers via peer tools."""
        mesh, coordinator, researcher, writer = distributed_mesh_with_peers

        print("\n" + "="*60)
        print("TEST: Peer communication")
        print("="*60)

        # Start researcher listening
        async def researcher_listener():
            while not researcher.shutdown_requested:
                if researcher.peers:
                    msg = await researcher.peers.receive(timeout=0.5)
                    if msg and msg.is_request:
                        query = msg.data.get("query", "")
                        researcher.requests_received.append(query)
                        # Respond using LLM
                        result = await researcher.execute_task({"task": query})
                        await researcher.peers.respond(msg, {"response": result["output"]})
                else:
                    await asyncio.sleep(0.1)

        listener_task = asyncio.create_task(researcher_listener())
        await asyncio.sleep(0.3)

        try:
            # Coordinator asks researcher for help
            result = await coordinator.peers.as_tool().execute(
                "ask_peer",
                {"role": "researcher", "question": "What is the speed of light?"}
            )

            print(f"\nPeer response: {result[:200]}...")

            assert len(result) > 0
            assert len(researcher.requests_received) > 0

            print("\nPASSED: Peer communication works!")

        finally:
            researcher.request_shutdown()
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# MANUAL DEMONSTRATION
# ═══════════════════════════════════════════════════════════════════════════════

async def run_customagent_demo():
    """Demonstrate CustomAgent in distributed mode with real LLM."""
    print("\n" + "="*70)
    print("CUSTOMAGENT DISTRIBUTED MODE DEMONSTRATION")
    print("="*70)

    mesh = Mesh(mode="distributed", config={'bind_port': 7995})

    mesh.add(LLMResearchAgent)
    mesh.add(LLMWriterAgent)
    mesh.add(LLMReviewerAgent)

    print("\n[SETUP] Created distributed mesh with CustomAgents:")
    for agent in mesh.agents:
        print(f"  - {agent.role}: {agent.capabilities}")

    await mesh.start()
    print("\n[STARTED] Mesh running in distributed mode")

    try:
        # Demo: Content creation pipeline
        print("\n" + "-"*60)
        print("DEMO: Content Creation Pipeline")
        print("-"*60)

        results = await mesh.workflow("demo-pipeline", [
            {
                "agent": "researcher",
                "task": "Provide 3 key benefits of remote work."
            },
            {
                "agent": "writer",
                "task": "Write a short paragraph promoting remote work using these benefits: flexibility, no commute, work-life balance."
            },
            {
                "agent": "reviewer",
                "task": "Review this paragraph and rate it 1-5: 'Remote work offers unprecedented flexibility, eliminates stressful commutes, and enables better work-life balance.'"
            }
        ])

        for i, r in enumerate(results):
            print(f"\nStep {i+1} - {r['role'] if 'role' in r else 'unknown'}:")
            print(f"  Status: {r['status']}")
            output = str(r.get('output', ''))[:200]
            print(f"  Output: {output}...")

    finally:
        await mesh.stop()

    print("\n" + "="*70)
    print("DEMONSTRATION COMPLETE")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(run_customagent_demo())
