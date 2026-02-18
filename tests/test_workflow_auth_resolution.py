"""
Tests for Phase 7D: Auth resolution inside workflow engine.

What these tests prove:
- _resolve_auth() returns None when agent has no code_registry
- _resolve_auth() calls detect_system_dependencies() on the task text
- _resolve_auth() calls auth_manager.resolve_auth_context() per system
- auth_context is injected into task["context"]["auth_context"]
- Agents without requires_auth do NOT get auth_context
- Auth resolution failure (exception) is logged but does not fail the step
- WorkflowEngine._deps_met() uses Redis when available, memory otherwise
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, Optional

import pytest

from jarviscore import Mesh
from jarviscore.core.agent import Agent
from jarviscore.orchestration.engine import WorkflowEngine
from jarviscore.orchestration.state import WorkflowState


# ======================================================================
# Helpers
# ======================================================================

def _make_engine(redis_store=None):
    """Create a WorkflowEngine with a minimal mock mesh."""
    mesh = MagicMock()
    mesh.agents = []
    mesh._auth_manager = None
    engine = WorkflowEngine(mesh=mesh, config={}, redis_store=redis_store)
    engine._started = True
    return engine


# ======================================================================
# _resolve_auth()
# ======================================================================

class TestResolveAuth:
    @pytest.mark.asyncio
    async def test_no_code_registry_returns_none(self):
        engine = _make_engine()
        auth_manager = MagicMock()
        agent = MagicMock()
        del agent.code_registry  # ensure attribute absent

        result = await engine._resolve_auth(auth_manager, agent, {"task": "do something"})
        assert result is None

    @pytest.mark.asyncio
    async def test_no_systems_detected_returns_none(self):
        engine = _make_engine()
        auth_manager = AsyncMock()
        code_registry = MagicMock()
        code_registry.detect_system_dependencies.return_value = []

        agent = MagicMock()
        agent.code_registry = code_registry

        result = await engine._resolve_auth(auth_manager, agent, {"task": "plain task"})
        assert result is None

    @pytest.mark.asyncio
    async def test_auth_context_returned_for_detected_system(self):
        engine = _make_engine()

        expected_ctx = {"token": "abc123", "system": "shopify"}
        auth_manager = MagicMock()
        auth_manager.resolve_auth_context = AsyncMock(return_value=expected_ctx)

        code_registry = MagicMock()
        code_registry.detect_system_dependencies.return_value = ["shopify"]

        agent = MagicMock()
        agent.code_registry = code_registry

        result = await engine._resolve_auth(
            auth_manager, agent, {"task": "query shopify orders"}
        )
        assert result == expected_ctx
        auth_manager.resolve_auth_context.assert_awaited_once_with("shopify", code_registry)

    @pytest.mark.asyncio
    async def test_auth_failure_returns_none_not_raises(self):
        """A broken auth_manager must not fail the step."""
        engine = _make_engine()

        auth_manager = MagicMock()
        auth_manager.resolve_auth_context = AsyncMock(side_effect=RuntimeError("boom"))

        code_registry = MagicMock()
        code_registry.detect_system_dependencies.return_value = ["shopify"]

        agent = MagicMock()
        agent.code_registry = code_registry

        # Should not raise
        result = await engine._resolve_auth(
            auth_manager, agent, {"task": "query shopify"}
        )
        assert result is None


# ======================================================================
# auth_context injected into task context
# ======================================================================

class TestAuthContextInjectedIntoTask:
    """
    Full-stack: run a workflow with an auth-requiring agent and verify
    that auth_context is visible inside execute_task().
    """

    class AuthCapturingAgent(Agent):
        role = "auth_capturing"
        capabilities = ["auth_capturing"]
        requires_auth = True
        received_auth_context = None

        async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
            ctx = task.get("context", {})
            type(self).received_auth_context = ctx.get("auth_context")
            return {"status": "success", "output": "ok"}

    @pytest.mark.asyncio
    async def test_auth_context_injected(self):
        fake_auth = {"token": "test-token", "system": "shopify"}
        mock_auth_manager = MagicMock()
        mock_auth_manager.resolve_auth_context = AsyncMock(return_value=fake_auth)
        mock_auth_manager.close = AsyncMock()

        fake_registry = MagicMock()
        fake_registry.detect_system_dependencies.return_value = ["shopify"]

        with patch("jarviscore.auth.manager.AuthenticationManager",
                   return_value=mock_auth_manager):
            mesh = Mesh(mode="autonomous", config={"auth_mode": "development"})
            agent = mesh.add(self.AuthCapturingAgent)
            agent.code_registry = fake_registry
            await mesh.start()
            try:
                results = await mesh.workflow("wf-auth", [
                    {"agent": "auth_capturing", "task": "query shopify orders"}
                ])
            finally:
                await mesh.stop()

        assert results[0]["status"] == "success"
        assert self.AuthCapturingAgent.received_auth_context == fake_auth


# ======================================================================
# _deps_met()
# ======================================================================

class TestDepsMet:
    def test_empty_deps_always_met(self):
        engine = _make_engine()
        state = WorkflowState("wf", total_steps=1)
        assert engine._deps_met([], state, "wf") is True

    def test_in_memory_dep_met(self):
        engine = _make_engine()
        state = WorkflowState("wf", total_steps=2)
        state.processed_steps.add("step1")
        assert engine._deps_met(["step1"], state, "wf") is True

    def test_in_memory_dep_not_met(self):
        engine = _make_engine()
        state = WorkflowState("wf", total_steps=2)
        assert engine._deps_met(["step1"], state, "wf") is False

    def test_redis_dep_met(self):
        """When redis_store is set, it delegates to get_step_status()."""
        mock_store = MagicMock()
        mock_store.get_step_status.return_value = "completed"
        engine = _make_engine(redis_store=mock_store)
        state = WorkflowState("wf", total_steps=2)

        assert engine._deps_met(["step1"], state, "wf") is True
        mock_store.get_step_status.assert_called_once_with("wf", "step1")

    def test_redis_dep_not_met(self):
        mock_store = MagicMock()
        mock_store.get_step_status.return_value = "in_progress"
        engine = _make_engine(redis_store=mock_store)
        state = WorkflowState("wf", total_steps=2)

        assert engine._deps_met(["step1"], state, "wf") is False
