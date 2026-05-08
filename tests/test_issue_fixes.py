"""
Tests for issues #21, #24, #25, #26 fixes.

#21 — OODA cross-task persistent memory (memory_enabled flag)
#24 — Sandbox pre-loaded stdlib modules
#25 — Auto-discovery of _tool_* methods with non-standard decorators
#26 — SubagentLogAdapter consistent [role][turn=N] prefix
"""

import asyncio
import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_llm(response="DONE: ok\nRESULT: {}"):
    llm = MagicMock()
    llm.generate = AsyncMock(return_value={
        "content": response, "tokens": {"input": 1, "output": 1, "total": 2},
        "provider": "mock", "cost_usd": 0.0,
    })
    return llm


# ─────────────────────────────────────────────────────────────────────────────
# #26 — SubagentLogAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TestSubagentLogAdapter:
    def test_prefix_contains_role_and_turn(self):
        from jarviscore.kernel.subagent import SubagentLogAdapter
        adapter = SubagentLogAdapter(logging.getLogger("test"), role="researcher")
        msg, _ = adapter.process("hello world", {})
        assert "[researcher]" in msg
        assert "[turn=0]" in msg
        assert "hello world" in msg

    def test_set_turn_updates_prefix(self):
        from jarviscore.kernel.subagent import SubagentLogAdapter
        adapter = SubagentLogAdapter(logging.getLogger("test"), role="coder")
        adapter.set_turn(7)
        msg, _ = adapter.process("test", {})
        assert "[turn=7]" in msg

    def test_adapter_is_assigned_to_subagent(self):
        from jarviscore.kernel.subagent import BaseSubAgent, SubagentLogAdapter

        class _Minimal(BaseSubAgent):
            def get_system_prompt(self): return "sys"
            def setup_tools(self): pass

        agent = _Minimal(agent_id="a1", role="tester", llm_client=_make_llm())
        assert isinstance(agent._log, SubagentLogAdapter)
        assert agent._log.extra["role"] == "tester"


# ─────────────────────────────────────────────────────────────────────────────
# #25 — Auto-discovery of _tool_* methods
# ─────────────────────────────────────────────────────────────────────────────

class TestToolAutodiscovery:
    def test_unregistered_tool_method_is_auto_discovered(self):
        from jarviscore.kernel.subagent import BaseSubAgent

        class _Agent(BaseSubAgent):
            def get_system_prompt(self): return "sys"
            def setup_tools(self): pass  # deliberately registers nothing

            def _tool_say_hello(self):
                """Greet the user."""
                return {"status": "success", "output": "hello"}

        agent = _Agent(agent_id="a", role="r", llm_client=_make_llm())
        assert "say_hello" in agent._tools
        assert agent._tools["say_hello"].description == "Greet the user."

    def test_explicit_registration_takes_priority(self):
        from jarviscore.kernel.subagent import BaseSubAgent

        class _Agent(BaseSubAgent):
            def get_system_prompt(self): return "sys"
            def setup_tools(self):
                self.register_tool("say_hello", self._tool_say_hello,
                                   "explicit description")

            def _tool_say_hello(self):
                """Auto description."""
                return {}

        agent = _Agent(agent_id="a", role="r", llm_client=_make_llm())
        assert agent._tools["say_hello"].description == "explicit description"

    def test_decorated_tool_method_is_discovered(self):
        """A _tool_* method wrapped with a simple custom decorator is still found."""
        from jarviscore.kernel.subagent import BaseSubAgent

        def my_decorator(fn):
            def wrapper(*a, **kw):
                return fn(*a, **kw)
            wrapper.__doc__ = fn.__doc__
            wrapper.__name__ = fn.__name__
            return wrapper

        class _Agent(BaseSubAgent):
            def get_system_prompt(self): return "sys"
            def setup_tools(self): pass

            @my_decorator
            def _tool_decorated(self):
                """Decorated tool."""
                return {"status": "success"}

        agent = _Agent(agent_id="a", role="r", llm_client=_make_llm())
        assert "decorated" in agent._tools


# ─────────────────────────────────────────────────────────────────────────────
# #24 — Sandbox pre-loaded stdlib modules
# ─────────────────────────────────────────────────────────────────────────────

class TestSandboxPreloads:
    def test_stdlib_modules_in_namespace(self):
        from jarviscore.execution.sandbox import SandboxExecutor
        executor = SandboxExecutor()
        ns = executor._create_namespace()
        for mod in ("json", "math", "re", "datetime", "collections",
                    "itertools", "functools", "base64", "hashlib", "uuid"):
            assert mod in ns, f"'{mod}' not pre-loaded in sandbox namespace"

    def test_json_usable_without_import(self):
        from jarviscore.execution.sandbox import SandboxExecutor
        executor = SandboxExecutor()
        ns = executor._create_namespace()
        exec("result = json.dumps({'x': 1})", ns)
        assert ns["result"] == '{"x": 1}'

    def test_math_usable_without_import(self):
        from jarviscore.execution.sandbox import SandboxExecutor
        executor = SandboxExecutor()
        ns = executor._create_namespace()
        exec("result = math.sqrt(16)", ns)
        assert ns["result"] == 4.0

    def test_extra_imports_env_var(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_EXTRA_IMPORTS", "os")
        # Force re-evaluation of module-level list by reimporting
        import importlib
        import jarviscore.execution.sandbox as sb_mod
        importlib.reload(sb_mod)
        executor = sb_mod.SandboxExecutor()
        ns = executor._create_namespace()
        assert "os" in ns
        # cleanup
        importlib.reload(sb_mod)


# ─────────────────────────────────────────────────────────────────────────────
# #21 — Cross-task persistent memory
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossTaskMemory:
    @pytest.mark.asyncio
    async def test_memory_not_persisted_when_disabled(self):
        from jarviscore.kernel.subagent import BaseSubAgent
        from jarviscore.kernel.state import KernelState

        class _Agent(BaseSubAgent):
            def get_system_prompt(self): return "sys"
            def setup_tools(self): pass

        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        agent = _Agent(agent_id="a", role="r", llm_client=_make_llm(),
                       redis_store=redis, memory_enabled=False)
        state = KernelState(agent_id="a")
        state.internal_variables["key"] = "value"
        await agent._persist_memory(state)
        redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_persisted_and_restored(self):
        from jarviscore.kernel.subagent import BaseSubAgent
        from jarviscore.kernel.state import KernelState

        class _Agent(BaseSubAgent):
            def get_system_prompt(self): return "sys"
            def setup_tools(self): pass

        stored = {}

        async def _set(key, value):
            stored[key] = value

        async def _get(key):
            return stored.get(key)

        redis = MagicMock()
        redis.set = AsyncMock(side_effect=_set)
        redis.get = AsyncMock(side_effect=_get)

        agent = _Agent(agent_id="agent-42", role="r", llm_client=_make_llm(),
                       redis_store=redis, memory_enabled=True)

        # First run: persist something
        state1 = KernelState(agent_id="agent-42")
        state1.internal_variables["api_schema"] = {"endpoint": "/v1/users"}
        await agent._persist_memory(state1)

        # Second run: restore
        state2 = KernelState(agent_id="agent-42")
        await agent._restore_memory(state2)

        assert state2.internal_variables.get("api_schema") == {"endpoint": "/v1/users"}

    @pytest.mark.asyncio
    async def test_restore_graceful_on_missing_key(self):
        from jarviscore.kernel.subagent import BaseSubAgent
        from jarviscore.kernel.state import KernelState

        class _Agent(BaseSubAgent):
            def get_system_prompt(self): return "sys"
            def setup_tools(self): pass

        redis = MagicMock()
        redis.get = AsyncMock(return_value=None)

        agent = _Agent(agent_id="new", role="r", llm_client=_make_llm(),
                       redis_store=redis, memory_enabled=True)
        state = KernelState(agent_id="new")
        await agent._restore_memory(state)  # should not raise
        assert state.internal_variables == {}
