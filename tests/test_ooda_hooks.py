"""
Tests for the three structural OODA loop hooks:

1. State-driven exit   — state.status == "completed" terminates the loop
2. Pre-execute hook    — _pre_execute_hook() enforces boundaries (e.g. approvals)
3. Done-gate           — _can_complete() can reject a malformed DONE

These test at the source/contract level — verifying the hooks exist, are
called in the right order, and have the correct signatures.
"""

import asyncio
import inspect
import json
import pytest
from typing import Any, Dict, Optional, Tuple

from jarviscore.kernel.subagent import BaseSubAgent, _now_fact
from jarviscore.kernel.state import KernelState


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _make_state(**overrides):
    defaults = {
        "workflow_id": "test",
        "step_id": "test",
        "agent_id": "test",
        "task": "test task",
        "status": "active",
        "turn": 0,
    }
    defaults.update(overrides)
    return KernelState(**defaults)


def _done_reply(result: str = '{"a": 1}') -> str:
    return f"THOUGHT: finishing\nDONE: summary\nRESULT: {result}"


class _ReplayLLM:
    def __init__(self, replies):
        self._replies = list(replies)

    async def generate(self, messages=None, **kwargs):
        reply = self._replies.pop(0) if self._replies else _done_reply()
        return {"content": reply, "tokens": {"input": 1, "output": 1, "total": 2}, "cost_usd": 0.0}


class _RunnableAgent(BaseSubAgent):
    """Minimal agent whose done-gate verdict is supplied per test."""

    def __init__(self, replies, gate):
        self._gate = gate
        self.gate_calls = 0
        super().__init__(agent_id="hooks", role="tester", llm_client=_ReplayLLM(replies))

    def get_system_prompt(self, *args, **kwargs) -> str:
        return "system"

    def setup_tools(self) -> None:
        return None

    def _can_complete(self, state, parsed):
        self.gate_calls += 1
        return self._gate()


# ──────────────────────────────────────────────────────────────────
# 1. State-Driven Exit Tests
# ──────────────────────────────────────────────────────────────────

class TestStateDrivenExit:
    """Verify that state.status == 'completed' terminates the loop."""

    def test_state_completed_check_exists_in_run(self):
        """run() must check state.status == 'completed' after tool execution."""
        source = inspect.getsource(BaseSubAgent._run_turns)
        assert 'state.status' in source or "status\", None) == \"completed\"" in source

    def test_state_driven_exit_returns_success(self):
        """When state.status == 'completed', run() returns status='success'."""
        source = inspect.getsource(BaseSubAgent._run_turns)
        # Find the state-driven exit block
        idx = source.index("state_driven")
        block = source[max(0, idx - 500):idx + 500]
        assert "status=\"success\"" in block or 'status="success"' in block

    def test_state_driven_exit_after_tool_execution(self):
        """State-driven exit must appear AFTER _execute_tool, not before."""
        source = inspect.getsource(BaseSubAgent._run_turns)
        exec_pos = source.index("_execute_tool")
        state_exit_pos = source.index("state_driven")
        assert state_exit_pos > exec_pos

    def test_state_driven_exit_uses_tool_result_as_payload(self):
        """The exit payload should be the tool_result, not parsed content."""
        source = inspect.getsource(BaseSubAgent._run_turns)
        idx = source.index("state_driven")
        block = source[max(0, idx - 300):idx + 100]
        assert "payload=tool_result" in block


# ──────────────────────────────────────────────────────────────────
# 2. Pre-Execute Hook Tests
# ──────────────────────────────────────────────────────────────────

class TestPreExecuteHook:
    """Verify the _pre_execute_hook mechanism."""

    def test_hook_exists_on_base(self):
        """BaseSubAgent must define _pre_execute_hook."""
        assert hasattr(BaseSubAgent, "_pre_execute_hook")

    def test_hook_is_async(self):
        """_pre_execute_hook must be async (returns a coroutine)."""
        assert asyncio.iscoroutinefunction(BaseSubAgent._pre_execute_hook)

    def test_hook_default_returns_none(self):
        """Default _pre_execute_hook returns None (allow all)."""
        class ConcreteAgent(BaseSubAgent):
            @property
            def role(self): return "test"
            def _build_system_prompt(self): return ""
            def get_system_prompt(self): return ""
            def setup_tools(self): return []

        agent = ConcreteAgent.__new__(ConcreteAgent)
        state = _make_state()
        result = asyncio.run(agent._pre_execute_hook("some_tool", {}, state))
        assert result is None

    def test_hook_signature(self):
        """_pre_execute_hook must accept (tool_name, params, state)."""
        sig = inspect.signature(BaseSubAgent._pre_execute_hook)
        params = list(sig.parameters.keys())
        # self, tool_name, params, state
        assert len(params) >= 4
        assert "tool_name" in params
        assert "params" in params
        assert "state" in params

    def test_hook_called_before_execute_in_source(self):
        """_pre_execute_hook must be called BEFORE _execute_tool."""
        source = inspect.getsource(BaseSubAgent._run_turns)
        hook_pos = source.index("_pre_execute_hook")
        exec_pos = source.index("_execute_tool")
        assert hook_pos < exec_pos

    def test_hook_block_uses_continue(self):
        """When hook returns a result, the call is skipped (not executed) and the loop moves on."""
        source = inspect.getsource(BaseSubAgent._run_turns)
        hook_idx = source.index("_pre_execute_hook")
        # The block ends this call without executing it: the turn loop's
        # `continue`, or `return None` from the per-call action.
        block = source[hook_idx:hook_idx + 1500]
        assert "pre_execute_block" in block
        assert "continue" in block or "return None" in block


# ──────────────────────────────────────────────────────────────────
# 3. Done-Gate Tests
# ──────────────────────────────────────────────────────────────────

class TestDoneGate:
    """Verify the _can_complete mechanism."""

    def test_can_complete_exists_on_base(self):
        """BaseSubAgent must define _can_complete."""
        assert hasattr(BaseSubAgent, "_can_complete")

    def test_default_allows_completion(self):
        """Default _can_complete returns (True, '')."""
        class ConcreteAgent(BaseSubAgent):
            @property
            def role(self): return "test"
            def _build_system_prompt(self): return ""
            def get_system_prompt(self): return ""
            def setup_tools(self): return []

        agent = ConcreteAgent.__new__(ConcreteAgent)
        state = _make_state()
        ok, reason = agent._can_complete(state, {"type": "done", "summary": "test"})
        assert ok is True
        assert reason == ""

    def test_can_complete_signature(self):
        """_can_complete must accept (state, parsed) and return tuple."""
        sig = inspect.signature(BaseSubAgent._can_complete)
        params = list(sig.parameters.keys())
        assert "state" in params
        assert "parsed" in params

    def test_done_gate_called_before_exit(self):
        """A rejected DONE must not complete the step."""
        agent = _RunnableAgent([_done_reply()], gate=lambda: (False, "not yet"))

        result = asyncio.run(agent.run(task="t", max_turns=1))

        assert agent.gate_calls == 1
        assert result.status != "success"
        assert agent._current_state.status != "completed"

    def test_rejection_injects_thought(self):
        """On rejection, a [DONE_GATE] thought is recorded on the state."""
        agent = _RunnableAgent([_done_reply()], gate=lambda: (False, "not yet"))

        asyncio.run(agent.run(task="t", max_turns=1))

        assert any("[DONE_GATE]" in thought for thought in agent._current_state.thoughts)

    def test_rejection_continues_loop(self):
        """A rejection continues the loop; a later DONE still completes."""
        gates = iter([(False, "not yet"), (True, "")])
        agent = _RunnableAgent([_done_reply(), _done_reply()], gate=lambda: next(gates))

        result = asyncio.run(agent.run(task="t", max_turns=2))

        assert agent.gate_calls == 2
        assert result.status == "success"


# ──────────────────────────────────────────────────────────────────
# 4. Researcher Hook Integration Tests
# ──────────────────────────────────────────────────────────────────

class TestResearcherHookIntegration:
    """Verify the researcher properly overrides the new hooks."""

    def test_researcher_does_not_gate_tools_by_phase(self):
        """Research phases are recorded; the researcher adds no pre-execute gate."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        assert (
            ResearcherSubAgent._pre_execute_hook
            is BaseSubAgent._pre_execute_hook
        )

    def test_researcher_overrides_can_complete(self):
        """ResearcherSubAgent must override _can_complete."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        assert (
            ResearcherSubAgent._can_complete
            is not BaseSubAgent._can_complete
        )

    def test_researcher_no_longer_has_dead_act(self):
        """The dead _act() method should be removed."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        # _act should not exist on ResearcherSubAgent (it was dead code)
        assert not hasattr(ResearcherSubAgent, "_act") or \
            ResearcherSubAgent._act is getattr(BaseSubAgent, "_act", None)

    def test_researcher_can_complete_checks_the_result_shape(self):
        """The researcher rejects a DONE whose result lacks its summary."""
        from jarviscore.kernel.defaults.researcher import ResearcherSubAgent
        researcher = ResearcherSubAgent.__new__(ResearcherSubAgent)

        ok, evidence = researcher._can_complete(_make_state(), {"result": {}})

        assert ok is False
        assert evidence.check == "summary"


# ──────────────────────────────────────────────────────────────────
# 5. Guard Ordering Tests (full pipeline)
# ──────────────────────────────────────────────────────────────────

class TestGuardOrdering:
    """Verify the complete guard ordering in the OODA ACT phase.

    The order is:
    1. Pre-execute hook (boundaries only)
    2. _execute_tool
    3. Identical-call record (a fact, never a refusal)
    4. State-driven exit check
    """

    def test_full_guard_order(self):
        source = inspect.getsource(BaseSubAgent._run_turns)
        positions = {
            "pre_execute_hook": source.index("_pre_execute_hook"),
            "execute_tool": source.index("_execute_tool"),
            "identical_call": source.index("_identical_call_record"),
            "state_driven_exit": source.index("state_driven"),
        }

        assert positions["pre_execute_hook"] < positions["execute_tool"]
        assert positions["execute_tool"] < positions["identical_call"]
        assert positions["identical_call"] < positions["state_driven_exit"]
        for removed in ("is_repeat_failure", "validate_action", "record_outcome"):
            assert removed not in source

    def test_done_gate_before_done_exit(self):
        """_can_complete appears before the AgentOutput return in DONE handler."""
        source = inspect.getsource(BaseSubAgent._run_turns)
        done_idx = source.index("Handle DONE")
        done_block = source[done_idx:done_idx + 3500]
        gate_pos = done_block.index("_can_complete")
        return_pos = done_block.index("return AgentOutput")
        assert gate_pos < return_pos


# ──────────────────────────────────────────────────────────────────
# 6. Native tool turns
# ──────────────────────────────────────────────────────────────────

def _call(name: str, arguments, call_id: Optional[str] = None) -> Dict[str, Any]:
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {"tool_calls": [{"id": call_id or f"call_{name}", "name": name, "arguments": arguments}]}


class _NativeLLM:
    """A provider that carries native tool calls, replaying one reply per request."""

    def __init__(self, replies, native=True):
        self._replies = list(replies)
        self._native = native
        self.requests = []

    def carries_native_tools(self, model=None):
        return self._native

    async def generate(self, messages=None, **kwargs):
        self.requests.append({"messages": [dict(message) for message in messages], **kwargs})
        reply = self._replies.pop(0) if self._replies else _call("done", {"summary": "end", "result": {}})
        return {
            "content": None,
            "tool_calls": [],
            "tokens": {"input": 1, "output": 1, "total": 2},
            "cost_usd": 0.0,
            **reply,
        }


class _NativeAgent(BaseSubAgent):
    def __init__(self, llm, gate=lambda: (True, "")):
        self._gate = gate
        self.searched = []
        super().__init__(agent_id="native", role="tester", llm_client=llm)

    def get_system_prompt(self) -> str:
        return "system"

    def setup_tools(self) -> None:
        self.register_tool("search", self._search, "Search the record.")
        self.register_tool("crm.lookup", self._lookup, "Look up a CRM record.")

    async def _search(self, query: str, limit: int = 5):
        self.searched.append((query, limit))
        return {"status": "success", "hits": [f"{query} was 5"]}

    async def _lookup(self, **params):
        return {"status": "success", "record": params}

    def _can_complete(self, state, parsed):
        return self._gate()


def _functions(request):
    return {tool["function"]["name"]: tool["function"] for tool in request["tools"]}


class TestNativeToolTurns:
    """Where the provider carries tool calls, each turn is one native call."""

    def test_a_turn_offers_the_tools_and_threads_the_call_and_its_result(self):
        llm = _NativeLLM([
            _call("search", {"query": "revenue"}),
            _call("done", {"summary": "Revenue was 5.", "result": {"revenue": 5}}),
        ])
        agent = _NativeAgent(llm)

        result = asyncio.run(agent.run(task="find revenue"))

        assert result.status == "success"
        assert result.payload == {"revenue": 5}
        assert result.metadata["answer"] == "Revenue was 5."
        assert agent.searched == [("revenue", 5)]

        first = llm.requests[0]
        assert first["tool_choice"] == "required"
        # Independent calls arrive together and all run this turn.
        assert first["parallel_tool_calls"] is True
        functions = _functions(first)
        assert {"search", "crm_lookup", "done"} <= set(functions)
        assert functions["search"]["parameters"] == {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
                "working_notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
        }
        # done ends the run: no notes to keep, and the summary is the answer.
        done = functions["done"]["parameters"]
        assert "working_notes" not in done["properties"]
        assert done["required"] == ["summary", "complete"]
        system = first["messages"][0]["content"]
        assert "TOOL:" not in system and "Available tools:" not in system

        threaded = llm.requests[1]["messages"]
        call_message = next(m for m in threaded if m.get("tool_calls"))
        assert call_message["tool_calls"][0]["id"] == "call_search"
        assert call_message["tool_calls"][0]["function"]["name"] == "search"
        tool_message = threaded[threaded.index(call_message) + 1]
        assert tool_message["role"] == "tool"
        assert tool_message["tool_call_id"] == "call_search"
        assert "revenue was 5" in tool_message["content"]

    def test_independent_calls_in_one_reply_all_run_in_one_turn(self):
        both = {"tool_calls": [
            {"id": "call_a", "name": "search", "arguments": json.dumps({"query": "revenue"})},
            {"id": "call_b", "name": "search", "arguments": json.dumps({"query": "margin", "working_notes": ["margin asked"]})},
        ]}
        llm = _NativeLLM([both, _call("done", {"summary": "Both found.", "complete": True})])
        agent = _NativeAgent(llm)

        result = asyncio.run(agent.run(task="find revenue and margin"))

        assert result.status == "success"
        assert agent.searched == [("revenue", 5), ("margin", 5)]
        # Two calls, one model turn: the second request already holds both results.
        assert len(llm.requests) == 2
        threaded = llm.requests[1]["messages"]
        answered = [m["tool_call_id"] for m in threaded if m.get("role") == "tool"]
        assert answered == ["call_a", "call_b"]
        assert len(agent._current_state.tool_history) == 2
        assert any("margin asked" in str(note) for note in agent._current_state.working_notes)

    def test_done_sent_with_other_calls_waits_for_their_results(self):
        rushed = {"tool_calls": [
            {"id": "call_a", "name": "search", "arguments": json.dumps({"query": "revenue"})},
            {"id": "call_done", "name": "done", "arguments": json.dumps({"summary": "guess", "complete": True})},
        ]}
        llm = _NativeLLM([rushed, _call("done", {"summary": "Revenue was 5.", "complete": True})])
        agent = _NativeAgent(llm)

        result = asyncio.run(agent.run(task="find revenue"))

        assert agent.searched == [("revenue", 5)]
        assert result.summary == "Revenue was 5."
        assert len(llm.requests) == 2

    def test_done_without_a_result_carries_an_empty_one(self):
        llm = _NativeLLM([_call("done", {"summary": "Nothing to hand on.", "complete": True})])
        agent = _NativeAgent(llm)

        result = asyncio.run(agent.run(task="say hello"))

        assert result.status == "success"
        assert result.payload == {}
        assert result.summary == "Nothing to hand on."

    def test_a_long_result_reaches_the_agent_whole_and_once(self):
        report = "row " * 5000 + "LAST ROW: 15 rejected"
        llm = _NativeLLM([
            _call("search", {"query": "revenue"}),
            _call("done", {"summary": "Read it.", "result": {}}),
        ])
        agent = _NativeAgent(llm)

        async def long_report(query: str, limit: int = 5):
            return {"status": "success", "report": report}

        agent.register_tool("search", long_report, "Read the whole report.")
        asyncio.run(agent.run(task="read the report"))

        prompt = "\n".join(str(m.get("content")) for m in llm.requests[1]["messages"])
        assert prompt.count("LAST ROW: 15 rejected") == 1
        # Shown in the conversation under its receipt, and not listed again.
        assert "RECENT ACTIONS" not in prompt
        assert "AUTHORITATIVE TOOL RECEIPTS" not in prompt

    def test_a_providers_call_signature_is_threaded_back_with_the_call(self):
        signed = _call("search", {"query": "revenue"})
        signed["tool_calls"][0]["signature"] = "c2ln"
        llm = _NativeLLM([signed, _call("done", {"summary": "5", "result": {}})])

        asyncio.run(_NativeAgent(llm).run(task="find revenue"))

        threaded = next(m for m in llm.requests[1]["messages"] if m.get("tool_calls"))
        assert threaded["tool_calls"][0]["signature"] == "c2ln"

    def test_a_function_name_maps_back_to_its_tool(self):
        llm = _NativeLLM([
            _call("crm_lookup", {"account": "acme"}),
            _call("done", {"summary": "Found.", "result": {}}),
        ])

        result = asyncio.run(_NativeAgent(llm).run(task="look up acme"))

        assert result.status == "success"
        calls = [turn for turn in result.trajectory if turn.get("type") == "tool_call"]
        assert calls[0]["tool"] == "crm.lookup"
        assert "acme" in calls[0]["result"]

    def test_notes_ride_along_with_a_native_call_and_never_reach_the_tool(self):
        # tool_choice="required" leaves no text beside the call, so NOTE: lines
        # cannot carry notes here; every function takes them as an argument.
        llm = _NativeLLM([
            _call("search", {"query": "revenue", "working_notes": ["FY25 report is on page 4"]}),
            _call("done", {"summary": "5", "result": {}, "working_notes": ["Revenue was 5"]}),
        ])
        agent = _NativeAgent(llm)

        asyncio.run(agent.run(task="find revenue"))

        assert agent.searched == [("revenue", 5)]
        assert [n["note"] for n in agent._current_state.working_notes] == [
            "FY25 report is on page 4", "Revenue was 5",
        ]
        # The note is read in the call that carried it while that call is in view.
        later = json.dumps(llm.requests[1]["messages"])
        assert later.count("FY25 report is on page 4") == 1
        assert "MY WORKING NOTES" not in later
        assert "working_notes" in llm.requests[0]["messages"][0]["content"]

    def test_a_tool_cannot_claim_the_notes_argument(self):
        agent = _NativeAgent(_NativeLLM([]))

        async def clash(working_notes: str):
            return {}

        agent.register_tool("clash", clash, "Clashes.")
        with pytest.raises(ValueError, match="reserve"):
            agent._native_tool_specs({})

    def test_a_reply_that_calls_no_function_is_repaired_not_accepted(self):
        llm = _NativeLLM([
            {"content": "Revenue was probably 5."},
            _call("done", {"summary": "Revenue was 5.", "result": {}}),
        ])

        result = asyncio.run(_NativeAgent(llm).run(task="find revenue"))

        assert result.status == "success"
        repair = llm.requests[1]["messages"][-2]
        assert repair["role"] == "user"
        assert "called no function" in repair["content"]

    def test_a_rejected_done_is_threaded_as_the_result_of_that_call(self):
        verdicts = iter([(False, "cite a source"), (True, "")])
        llm = _NativeLLM([
            _call("done", {"summary": "Revenue was 5.", "result": {}}, "call_a"),
            _call("done", {"summary": "Revenue was 5, per the 10-K.", "result": {}}, "call_b"),
        ])

        result = asyncio.run(_NativeAgent(llm, gate=lambda: next(verdicts)).run(task="t"))

        assert result.status == "success"
        threaded = llm.requests[1]["messages"]
        rejection = next(m for m in threaded if m.get("role") == "tool")
        assert rejection["tool_call_id"] == "call_a"
        assert "cite a source" in rejection["content"]

    def test_the_landing_turn_offers_only_done(self):
        llm = _NativeLLM([_call("done", {"summary": "Partial: 5.", "result": {"partial": True}})])
        agent = _NativeAgent(llm)
        agent._native_protocol = True
        history = [{
            "assistant": "",
            "observation": "hits",
            "tool_call": {"id": "c1", "name": "search", "arguments": "{}"},
        }]

        landing = asyncio.run(agent._landing_turn(
            _make_state(), "system", history, None,
            {"input": 0, "output": 0, "total": 0}, 0.0, "turns",
        ))

        assert landing is None
        assert list(_functions(llm.requests[0])) == ["done"]

    def test_a_landing_that_could_not_finish_fails_with_its_reason_when_nothing_resumes(self):
        def land(context):
            llm = _NativeLLM([_call("done", {
                "summary": "sales_2025.csv is not in the workspace; nothing was totalled.",
                "result": {}, "complete": False,
            })])
            agent = _NativeAgent(llm)
            agent._native_protocol = True
            history = [{"assistant": "", "observation": "not found",
                        "tool_call": {"id": "c1", "name": "search", "arguments": "{}"}}]
            return asyncio.run(agent._landing_turn(
                _make_state(context=context), "system", history, None,
                {"input": 0, "output": 0, "total": 0}, 0.0, "turns",
            ))

        final = land({})
        assert final.status == "failure"
        assert final.summary.startswith("sales_2025.csv is not in the workspace")
        assert final.metadata["typed_outcome"] == "FAIL_INCOMPLETE"

        resumable = {"execution_budget": {"max_epochs_per_step": 3}, "execution_epoch": 1}
        assert land(resumable) is None

    def test_a_provider_without_native_tools_keeps_the_text_protocol(self):
        for native in (False, object()):
            llm = _NativeLLM([{"content": _done_reply()}], native=native)

            result = asyncio.run(_NativeAgent(llm).run(task="t"))

            assert result.status == "success"
            assert "tools" not in llm.requests[0]
            assert "TOOL:" in llm.requests[0]["messages"][0]["content"]

    def test_a_tool_that_ends_the_step_gives_its_summary_as_the_answer(self):
        llm = _NativeLLM([_call("publish", {"summary": "Qdrant fuses dense and sparse natively."})])
        agent = _NativeAgent(llm)

        async def publish(summary: str):
            agent._current_state.status = "completed"
            return {"summary": summary, "evidence": [{"pointer": "https://qdrant.tech"}]}

        agent.register_tool("publish", publish, "Publish the findings.")
        result = asyncio.run(agent.run(task="research hybrid search"))

        assert result.status == "success"
        assert result.summary == "Qdrant fuses dense and sparse natively."
        assert result.metadata["answer"] == "Qdrant fuses dense and sparse natively."

    def test_every_done_asks_whether_the_task_was_carried_out(self):
        llm = _NativeLLM([_call("done", {"summary": "5", "result": {}, "complete": True})])

        result = asyncio.run(_NativeAgent(llm).run(task="t"))

        done = _functions(llm.requests[0])["done"]["parameters"]
        assert "complete" in done["required"]
        assert result.status == "success"

    def test_an_agent_that_could_not_do_the_task_fails_with_its_reason(self):
        llm = _NativeLLM([
            _call("search", {"query": "sales_2025.csv"}),
            _call("done", {
                "summary": "The file sales_2025.csv does not exist, so nothing was computed.",
                "result": {"revenue": None},
                "complete": False,
            }),
        ])

        result = asyncio.run(_NativeAgent(llm).run(task="total the file"))

        assert result.status == "failure"
        assert result.summary == "The file sales_2025.csv does not exist, so nothing was computed."
        assert result.payload == {"revenue": None}
        assert result.metadata["typed_outcome"] == "FAIL_INCOMPLETE"
        assert result.metadata["work_record"] == {"search": {"calls": 1, "succeeded": 1}}

    def test_a_done_without_the_flag_still_completes(self):
        llm = _NativeLLM([_call("done", {"summary": "5", "result": {}})])

        assert asyncio.run(_NativeAgent(llm).run(task="t")).status == "success"

    def test_the_text_protocol_can_say_the_task_was_not_carried_out(self):
        reply = "THOUGHT: no file\nCOMPLETE: no\nDONE: The file was not there.\nRESULT: {}"
        llm = _NativeLLM([{"content": reply}], native=False)

        result = asyncio.run(_NativeAgent(llm).run(task="t"))

        assert result.status == "failure"
        assert result.summary == "The file was not there."
        assert "COMPLETE: no" in llm.requests[0]["messages"][0]["content"]

    def test_a_declared_output_schema_types_the_done_result(self):
        from pydantic import BaseModel

        class Answer(BaseModel):
            revenue: int

        done = _NativeAgent(_NativeLLM([]))._done_function({"output_schema": Answer})
        result = done["function"]["parameters"]["properties"]["result"]
        assert result["properties"]["revenue"]["type"] == "integer"
        assert done["function"]["parameters"]["required"] == ["summary", "result", "complete"]

    def test_a_nested_output_schema_keeps_its_references_resolvable(self):
        from typing import List

        from pydantic import BaseModel

        class Citation(BaseModel):
            url: str

        class Assessment(BaseModel):
            outcome: str
            citations: List[Citation]

        parameters = _NativeAgent(_NativeLLM([]))._done_function(
            {"output_schema": Assessment}
        )["function"]["parameters"]

        refs = []

        def collect(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    refs.append(node["$ref"])
                for value in node.values():
                    collect(value)
            elif isinstance(node, list):
                for value in node:
                    collect(value)

        collect(parameters)
        assert refs
        for ref in refs:
            target = parameters
            for part in ref.removeprefix("#/").split("/"):
                target = target[part]
            assert target["properties"]["url"]["type"] == "string"
        assert "$defs" not in parameters["properties"]["result"]

    def test_a_state_carrying_a_declared_output_schema_checkpoints(self):
        from pydantic import BaseModel

        class Answer(BaseModel):
            revenue: int

        state = _make_state(context={"output_schema": Answer, "matter_id": "atlas"})

        restored = KernelState.model_validate_json(state.model_dump_json())

        assert restored.context == {"matter_id": "atlas"}
        assert state.context["output_schema"] is Answer
# ──────────────────────────────────────────────────────────────────
# 7. The runtime records; the agent decides
# ──────────────────────────────────────────────────────────────────

class _RecordingLLM(_ReplayLLM):
    def __init__(self, replies):
        super().__init__(replies)
        self.prompts = []

    async def generate(self, messages=None, **kwargs):
        self.prompts.append(messages)
        return await super().generate(messages=messages, **kwargs)


class _PollingAgent(BaseSubAgent):
    def __init__(self, replies):
        self.polls = 0
        super().__init__(agent_id="poller", role="tester", llm_client=_RecordingLLM(replies))

    def get_system_prompt(self, *args, **kwargs) -> str:
        return "system"

    def setup_tools(self) -> None:
        self.register_tool("poll", self._poll, "Read the order status.")

    async def _poll(self, order: str = "A1") -> Dict[str, Any]:
        self.polls += 1
        return {"status": "success", "order": order, "state": "pending"}


_POLL = 'THOUGHT: check again\nTOOL: poll\nPARAMS: {"order": "A1"}'
_STEERING = (
    "Call DONE with what you have", "call done now", "Stop gathering", "pivot",
    "KNOWLEDGE_PLATEAU", "CONVERGENCE", "already read", "too similar", "Do Not Repeat",
    "EXIT CHECK",
)


class TestRuntimeRecordsAgentDecides:

    def _run(self, polls):
        agent = _PollingAgent([_POLL] * polls + [_done_reply()])
        result = asyncio.run(agent.run(task="watch order A1", max_turns=polls + 2))
        return agent, result

    def test_identical_calls_all_run_and_the_agent_decides_when_to_stop(self):
        agent, result = self._run(12)

        assert agent.polls == 12
        assert result.status == "success"

    def test_identical_call_result_carries_the_earlier_receipt_as_a_fact(self):
        agent, _ = self._run(3)

        last_prompt = "\n".join(str(m.get("content")) for m in agent.llm_client.prompts[-1])
        assert "This exact call (same tool, same arguments) ran 2 time(s) earlier" in last_prompt
        assert "identical to this one" in last_prompt

    def test_no_runtime_steering_reaches_the_agent(self):
        agent, _ = self._run(12)

        for messages in agent.llm_client.prompts:
            text = "\n".join(str(m.get("content")) for m in messages)
            for phrase in _STEERING:
                assert phrase not in text, phrase

    def test_budget_facts_are_a_per_turn_notice_not_a_thought(self):
        from datetime import datetime

        agent, _ = self._run(2)

        today = datetime.now().astimezone().strftime("%d %B %Y")
        for messages in agent.llm_client.prompts:
            text = "\n".join(str(m.get("content")) for m in messages)
            assert text.count("## RUNTIME NOTICE (this turn)") == 1
            assert "Remaining: " in text
            assert "Now: " in text and today in text
        assert not any("Remaining: " in t for t in agent._current_state.thoughts)

    def test_native_turns_carry_facts_and_no_steering(self):
        llm = _NativeLLM([_call("poll", {"order": "A1"})] * 12)
        agent = _PollingAgent([])
        agent.llm_client = llm
        agent._native_protocol = True

        result = asyncio.run(agent.run(task="watch order A1", max_turns=14))

        assert agent.polls == 12
        assert result.status == "success"
        last = "\n".join(str(m.get("content")) for m in llm.requests[-1]["messages"])
        assert "ran 11 time(s) earlier" in last
        for request in llm.requests:
            text = "\n".join(str(m.get("content")) for m in request["messages"])
            assert "## RUNTIME NOTICE" in text
            for phrase in _STEERING:
                assert phrase not in text, phrase


class TestEachPromptExtendsTheLast:
    """Providers serve a prompt's repeated prefix from cache, so a turn adds to the last prompt rather than rewriting it."""

    _NOTE = "order A1 ships from the Leeds depot"

    def _run(self, polls, note_first=False, context=None):
        first = {"order": "A1", **({"working_notes": [self._NOTE]} if note_first else {})}
        llm = _NativeLLM(
            [_call("poll", first, call_id="call_0")]
            + [_call("poll", {"order": "A1"}, call_id=f"call_{i}") for i in range(1, polls)]
        )
        agent = _PollingAgent([])
        agent.llm_client = llm
        asyncio.run(agent.run(task="watch order A1", context=context, max_turns=polls + 2))
        return agent, llm

    @staticmethod
    def _text(request):
        return json.dumps(request["messages"])

    def test_each_prompt_begins_with_the_whole_of_the_last_one(self):
        _, llm = self._run(6)

        for before, after in zip(llm.requests, llm.requests[1:]):
            assert after["tools"] == before["tools"]
            assert after["messages"][:len(before["messages"])] == before["messages"]

    def test_the_conversation_slides_five_exchanges_at_a_time(self):
        _, llm = self._run(17)

        shown = [sum(m["role"] == "tool" for m in r["messages"]) for r in llm.requests]
        assert shown[:15] == list(range(15))
        assert shown[15:17] == [10, 11]

    def test_a_note_returns_once_the_call_that_carried_it_leaves_view(self):
        _, llm = self._run(16, note_first=True)

        in_view = self._text(llm.requests[14])
        assert in_view.count(self._NOTE) == 1
        assert "MY WORKING NOTES" not in in_view
        after_slide = self._text(llm.requests[15])
        assert "MY WORKING NOTES" in after_slide
        assert after_slide.count(self._NOTE) == 1

    def test_the_agent_is_told_before_exchanges_leave_view(self):
        _, llm = self._run(14)

        warning = "leave your view within a turn or two"
        assert warning not in self._text(llm.requests[11])
        assert warning in llm.requests[12]["messages"][-1]["content"]

    def test_the_date_and_budget_are_said_once_not_every_turn(self):
        from datetime import datetime

        _, llm = self._run(6)

        today = datetime.now().astimezone().strftime("%d %B %Y")
        assert "Remaining: " in self._text(llm.requests[0])
        last = self._text(llm.requests[-1])
        assert last.count("Now: ") == 1 and today in last
        assert last.count("Remaining: ") == 1
        # The notice the first turn was given stays where it was, unchanged.
        assert llm.requests[-1]["messages"][2] == llm.requests[0]["messages"][2]

    def test_the_budget_is_said_again_once_it_runs_low(self):
        agent, _ = self._run(1)
        agent._cognition.lease.max_total_tokens = 100
        agent._cognition.lease.thinking_used = 90

        news = agent._turn_news([], [{"lead": "## RUNTIME NOTICE\n" + _now_fact()}], first=False)

        assert "Remaining: " in news
        assert "Now: " not in news

    def test_the_run_id_does_not_lead_the_prompt(self):
        _, llm = self._run(2, context={"workflow_id": "wf-run-4711", "step_id": "lookup"})

        leading = json.dumps(llm.requests[1]["messages"][:2])
        assert "wf-run-4711" not in leading
        assert "lookup" in leading

    def test_receipts_are_cited_in_result_never_in_the_summary(self):
        _, llm = self._run(1)

        done = next(t for t in llm.requests[0]["tools"] if t["function"]["name"] == "done")
        fields = done["function"]["parameters"]["properties"]
        assert "tool_receipt_id" in fields["result"]["description"]
        assert "No receipt ids" in fields["summary"]["description"]
        # Said once, where done is called.
        assert "tool_receipt_id" not in llm.requests[0]["messages"][0]["content"]
