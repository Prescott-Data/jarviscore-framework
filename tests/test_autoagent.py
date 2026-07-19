"""
Tests for AutoAgent profile.
"""
import json
from typing import Any, cast

import pytest
from jarviscore.profiles.autoagent import AutoAgent


class ValidAutoAgent(AutoAgent):
    """Valid AutoAgent for testing."""
    role = "test_auto"
    capabilities = ["testing"]
    system_prompt = "You are a test agent that performs testing tasks."


class NoPromptAutoAgent(AutoAgent):
    """AutoAgent without system_prompt (should fail)."""
    role = "no_prompt"
    capabilities = ["testing"]


class ProfiledAutoAgent(AutoAgent):
    """AutoAgent whose runtime routing comes from AgentProfile."""
    role = "profiled"
    capabilities = ["testing"]
    system_prompt = "You are a profiled test agent."


class ExplicitKernelRoleAutoAgent(AutoAgent):
    """AutoAgent whose class-level routing must not be overwritten."""
    role = "profiled"
    capabilities = ["testing"]
    default_kernel_role = "coder"
    system_prompt = "You are an explicitly routed test agent."


class GoalDirectAutoAgent(AutoAgent):
    """Goal-oriented agent that can still accept bounded single-turn work."""
    role = "goal_direct"
    capabilities = ["testing"]
    goal_oriented = True
    system_prompt = "You are a goal direct test agent."


class TestAutoAgentInitialization:
    """Test AutoAgent initialization."""

    def test_valid_autoagent_creation(self):
        """Test creating a valid AutoAgent."""
        agent = ValidAutoAgent()

        assert agent.role == "test_auto"
        assert agent.capabilities == ["testing"]
        assert agent.system_prompt == "You are a test agent that performs testing tasks."

    def test_autoagent_without_system_prompt_fails(self):
        """Test that AutoAgent without system_prompt raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            NoPromptAutoAgent()

        assert "must define 'system_prompt'" in str(exc_info.value)

    def test_autoagent_execution_components_initially_none(self):
        """Test that execution components are initially None."""
        agent = ValidAutoAgent()

        assert agent.llm is None
        assert agent.codegen is None
        assert agent.sandbox is None
        assert agent.repair is None

    def test_agent_profile_hydrates_default_kernel_role(self, tmp_path, monkeypatch):
        """Profile default_kernel_role should affect runtime routing."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "profiled.yaml").write_text(
            "\n".join([
                'role: "Profiled Test Agent"',
                "default_kernel_role: researcher",
                "expertise:",
                "  - profile-driven routing",
                "owns:",
                "  - routing behavior",
                "sops:",
                "  - Use profile defaults when class defaults are absent.",
                "domain_facts: {}",
                "escalates_to: []",
            ]),
            encoding="utf-8",
        )
        monkeypatch.setenv("JARVISCORE_PROFILES_DIR", str(profiles_dir))

        agent = ProfiledAutoAgent()
        agent._load_agent_profile()

        assert agent.default_kernel_role == "researcher"
        assert "ROLE INTELLIGENCE" in agent._profile_block

    def test_agent_profile_does_not_override_explicit_kernel_role(self, tmp_path, monkeypatch):
        """Class-level default_kernel_role remains authoritative."""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "profiled.yaml").write_text(
            "\n".join([
                'role: "Profiled Test Agent"',
                "default_kernel_role: researcher",
                "expertise:",
                "  - profile-driven routing",
                "owns:",
                "  - routing behavior",
                "sops:",
                "  - Use profile defaults when class defaults are absent.",
                "domain_facts: {}",
                "escalates_to: []",
            ]),
            encoding="utf-8",
        )
        monkeypatch.setenv("JARVISCORE_PROFILES_DIR", str(profiles_dir))

        agent = ExplicitKernelRoleAutoAgent()
        agent._load_agent_profile()

        assert agent.default_kernel_role == "coder"

    def test_agent_profile_directory_is_resolved_at_load_time(self, tmp_path, monkeypatch):
        """Late application bootstrap should still control profile lookup."""
        from jarviscore.profiles.agent_profile import AgentProfile

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "profiled.yaml").write_text(
            "\n".join([
                'role: "Late Bound Profile"',
                "default_kernel_role: communicator",
                "expertise:",
                "  - late env resolution",
                "owns:",
                "  - profile loading",
                "sops:",
                "  - Resolve profile directories at load time.",
                "domain_facts: {}",
                "escalates_to: []",
            ]),
            encoding="utf-8",
        )

        monkeypatch.setenv("JARVISCORE_PROFILES_DIR", str(profiles_dir))

        profile = AgentProfile.load("profiled")
        assert profile is not None
        assert profile.role == "Late Bound Profile"

    def test_agent_profile_without_kernel_role_does_not_invent_default(self, tmp_path, monkeypatch):
        """Missing profile routing config should not silently force communicator."""
        from jarviscore.profiles.agent_profile import AgentProfile

        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()
        (profiles_dir / "profiled.yaml").write_text(
            "\n".join([
                'role: "No Route Profile"',
                "expertise:",
                "  - profile loading",
                "owns: []",
                "sops: []",
                "domain_facts: {}",
                "escalates_to: []",
            ]),
            encoding="utf-8",
        )

        monkeypatch.setenv("JARVISCORE_PROFILES_DIR", str(profiles_dir))

        profile = AgentProfile.load("profiled")
        assert profile is not None
        assert profile.default_kernel_role is None

    def test_hitl_category_is_derived_from_kernel_yield_metadata(self):
        """AutoAgent must satisfy the strict HITL category contract."""
        from types import SimpleNamespace

        agent = ValidAutoAgent()

        assert agent._hitl_category_from_output(
            SimpleNamespace(metadata={"typed_outcome": "YIELD_AUTH_REQUIRED"})
        ) == "auth_required"
        assert agent._hitl_category_from_output(
            SimpleNamespace(metadata={"escalation_reason": "critical approval needed"})
        ) == "critical_action"
        assert agent._hitl_category_from_output(SimpleNamespace(metadata={})) == "data_required"


class TestAutoAgentSetup:
    """Test AutoAgent setup."""

    @pytest.mark.asyncio
    async def test_autoagent_setup(self):
        """Test AutoAgent setup hook."""
        agent = ValidAutoAgent()
        await agent.setup()

        # Day 1: Just verify it runs without error
        # Day 4: Will test actual LLM initialization

    @pytest.mark.asyncio
    async def test_autoagent_teardown_closes_search_client(self):
        """AutoAgent-owned aiohttp search clients must be closed on teardown."""
        class SearchClient:
            closed = False

            async def close(self):
                self.closed = True

        agent = ValidAutoAgent()
        search = SearchClient()
        setattr(agent, "search", search)

        await agent.teardown()

        assert search.closed is True


class TestAutoAgentExecution:
    """Test AutoAgent task execution."""

    @pytest.mark.asyncio
    async def test_execute_task_without_setup_fails(self):
        """Pre-start use raises a descriptive error (issue #63/JC-002).

        Previously this died deep in codegen with a NoneType AttributeError
        wrapped in a generic 'Fatal error' envelope; the loud, actionable
        RuntimeError is the fix.
        """
        agent = ValidAutoAgent()

        task = {"task": "Test task description"}
        with pytest.raises(RuntimeError, match="before mesh.start"):
            await agent.execute_task(task)

    @pytest.mark.asyncio
    async def test_execute_task_with_mock_components(self):
        """Test AutoAgent with mocked execution components."""
        from unittest.mock import Mock, AsyncMock

        agent = ValidAutoAgent()

        # Mock the execution components
        agent.codegen = Mock()
        agent.codegen.generate = AsyncMock(return_value="result = 42")

        agent.sandbox = Mock()
        agent.sandbox.execute = AsyncMock(return_value={
            "status": "success",
            "output": 42
        })

        agent.repair = Mock()  # Not called if execution succeeds

        # Mock result handler (Phase 1)
        agent.result_handler = Mock()
        agent.result_handler.process_result = Mock(return_value={
            'result_id': 'test-result-id',
            'status': 'success'
        })

        # Mock code registry (Phase 3)
        agent.code_registry = Mock()
        agent.code_registry.register = Mock(return_value='test-function-id')

        task = {"task": "Calculate 21 * 2"}
        result = await agent.execute_task(task)

        # Should succeed with mocked components
        assert result["status"] == "success"
        assert result["output"] == 42
        assert result["code"] == "result = 42"

    @pytest.mark.asyncio
    async def test_kernel_exception_does_not_fall_back_to_legacy_pipeline(self):
        """Kernel failures must be visible instead of silently using legacy codegen."""
        from unittest.mock import Mock, AsyncMock

        class BrokenKernel:
            auth_manager = None

            async def execute(self, **kwargs):
                raise RuntimeError("router exploded")

        agent = ValidAutoAgent()
        cast(Any, agent)._kernel = BrokenKernel()
        agent.codegen = Mock()
        agent.codegen.generate = AsyncMock(return_value="result = 42")
        agent.sandbox = Mock()
        agent.sandbox.execute = AsyncMock(return_value={"status": "success", "output": 42})
        agent.repair = Mock()

        result = await agent.execute_task({"task": "Calculate 21 * 2"})

        assert result["status"] == "failure"
        assert "Kernel exception" in result["error"]
        agent.codegen.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_goal_oriented_agent_uses_kernel_for_non_complex_work(self):
        """Goal-oriented agents use the Kernel directly when classifier says non-complex."""
        from types import SimpleNamespace

        class FakeLLM:
            async def generate(self, **kwargs):
                return {
                    "content": json.dumps({
                        "level": "moderate",
                        "reason": "Single-turn deliverable, not a long-running goal.",
                    })
                }

        class FakeKernel:
            def __init__(self):
                self.auth_manager = None
                self.calls = []

            async def execute(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    status="success",
                    payload={"ok": True},
                    summary="done",
                    metadata={"tokens": {"input": 0, "output": 0, "total": 0}, "elapsed_ms": 1},
                )

        agent = GoalDirectAutoAgent()
        setattr(agent, "llm", FakeLLM())
        kernel = FakeKernel()
        setattr(agent, "_kernel", kernel)

        result = await agent.execute_task({
            "task": "Return a single-turn operating contribution.",
            "context": {},
        })

        assert result["status"] == "success"
        assert result["payload"] == {"ok": True}
        assert result["goal_execution"]["planner_mode"] == "direct_kernel"
        assert result["goal_execution"]["complexity"] == "moderate"
        assert len(kernel.calls) == 1
        assert kernel.calls[0]["agent_default_role"] is None
        assert kernel.calls[0]["use_default_role_as_fallback"] is True

    @pytest.mark.asyncio
    async def test_goal_oriented_agent_honors_single_response_execution_contract(self):
        """A single-response contract is ONE completion against the system
        prompt — no classifier, no planner, no kernel routing (issue #63).

        The previous contract semantics routed into a direct Kernel turn,
        which still landed analysis prompts in the Coder sub-agent
        (TOOL/DONE protocol violations — JC-003).
        """
        class FakeLLM:
            def __init__(self):
                self.calls = []

            async def generate(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "content": "The founder-grade peer brief.",
                    "tokens": {"input": 5, "output": 5, "total": 10},
                    "cost_usd": 0.0,
                }

        class FakeKernel:
            def __init__(self):
                self.auth_manager = None
                self.calls = []

            async def execute(self, **kwargs):
                self.calls.append(kwargs)
                raise AssertionError("single_response must not route into the Kernel")

        agent = GoalDirectAutoAgent()
        llm = FakeLLM()
        setattr(agent, "llm", llm)
        kernel = FakeKernel()
        setattr(agent, "_kernel", kernel)

        result = await agent.execute_task({
            "task": "Return a founder-grade peer brief from supplied context.",
            "context": {"execution_contract": {"execution_shape": "single_response"}},
        })

        assert result["status"] == "success"
        assert result["output"] == "The founder-grade peer brief."
        assert result["execution_shape"] == "single_response"
        assert len(llm.calls) == 1          # exactly one completion
        assert len(kernel.calls) == 0       # kernel untouched
        # The completion ran against the agent's system prompt
        assert llm.calls[0]["messages"][0]["content"].endswith(
            GoalDirectAutoAgent.system_prompt
        )

    @pytest.mark.asyncio
    async def test_kernel_routes_access_requests_before_default_coder_role(self):
        from jarviscore.kernel.kernel import Kernel
        from jarviscore.testing import MockLLMClient

        llm = MockLLMClient(responses=[{
            "content": json.dumps({
                "role": "communicator",
                "confidence": 0.95,
                "reason": "The task is a request for access coordination.",
                "evidence_required": False,
            })
        }])
        kernel = Kernel(llm_client=llm)
        decision = await kernel._route_task(
            "Secure read-only access or PDFs for all bank accounts and confirm completeness.",
            context={},
            agent_default_role="coder",
            use_default_role_as_fallback=True,
        )

        assert decision.role == "communicator"


class TestAutoAgentInheritance:
    """Test AutoAgent inheritance from Profile and Agent."""

    def test_autoagent_inherits_agent_methods(self):
        """Test that AutoAgent inherits Agent methods."""
        agent = ValidAutoAgent()

        # Should have Agent methods
        assert hasattr(agent, "can_handle")
        assert hasattr(agent, "execute_task")
        assert hasattr(agent, "setup")
        assert hasattr(agent, "teardown")

    def test_autoagent_can_handle_tasks(self):
        """Test that AutoAgent can check task compatibility."""
        agent = ValidAutoAgent()

        task1 = {"role": "test_auto", "task": "Do something"}
        assert agent.can_handle(task1) is True

        task2 = {"capability": "testing", "task": "Run tests"}
        assert agent.can_handle(task2) is True

        task3 = {"role": "different", "task": "Won't handle"}
        assert agent.can_handle(task3) is False


class TestPlannerCompatibility:
    """Planner compatibility with JSON-object model behavior."""

    def test_planner_accepts_single_strict_step_object(self):
        from jarviscore.planning.planner import Planner

        planner = Planner(llm_client=None)
        steps = planner._parse_plan(
            """
            {
              "step_id": "step_01_read_calendar",
              "task": "Read the content calendar and list today's due items.",
              "success_criterion": "Today's due content items are listed.",
              "expected_findings": ["today_due_items"],
              "subagent_hint": "researcher"
            }
            """,
            goal="Run content pipeline",
        )

        assert len(steps) == 1
        assert steps[0].step_id == "step_01_read_calendar"
        assert steps[0].subagent_hint == "researcher"

    def test_planner_accepts_single_named_step_object(self):
        from jarviscore.planning.planner import Planner

        planner = Planner(llm_client=None)
        steps = planner._parse_plan(
            """
            {
              "step_02d_value_fit_mapping_matrix": {
                "step_id": "step_02d_value_fit_mapping_matrix",
                "task": "Map each validated expectation to product constraints.",
                "success_criterion": "Every expectation has at least one fit classification.",
                "expected_findings": ["fit_matrix"],
                "subagent_hint": "researcher"
              }
            }
            """,
            goal="Recover from a partially nested replan response",
        )

        assert len(steps) == 1
        assert steps[0].step_id == "step_02d_value_fit_mapping_matrix"
        assert steps[0].task == "Map each validated expectation to product constraints."
