"""Tool programs: an agent's tools called from sandboxed code.

A ReAct turn sends every tool result back through the model. On data-heavy
work (paging through invoices, reading many records) that is most of the cost,
and the model then does arithmetic in its head. A tool program runs the calls,
loops and totals in the Kernel's sandbox and returns only what it prints, while
every call still goes through the agent's own tool path and leaves a receipt.

These tests run real programs through the real sandbox and RPC bridge.
"""

import asyncio
import json

import pytest

from jarviscore.context.context_manager import ContextManager
from jarviscore.execution.coder_sandbox import CoderSandbox
from jarviscore.kernel.defaults.coder import CoderSubAgent
from jarviscore.kernel.state import KernelState
from jarviscore.kernel.subagent import BaseSubAgent

INVOICES = [
    {"invoice_id": f"INV-{n}", "customer_id": f"C-{n % 3}", "amount": float(n), "status": "open"}
    for n in range(1, 13)
]


class Ledger(BaseSubAgent):
    def __init__(self, gate=None):
        self.calls = []
        self._gate = gate
        super().__init__(agent_id="ledger", role="ledger", llm_client=None)

    def get_system_prompt(self) -> str:
        return "ledger"

    def setup_tools(self) -> None:
        self.register_tool("list_invoices", self.list_invoices, "List invoices, 5 per page.")
        self.register_tool("customer_name", self.customer_name, "Name of a customer.")

    def list_invoices(self, page: int = 1) -> str:
        self.calls.append(("list_invoices", page))
        chunk = INVOICES[(page - 1) * 5: page * 5]
        return json.dumps({"page": page, "pages": 3, "invoices": chunk})

    def customer_name(self, customer_id: str) -> str:
        self.calls.append(("customer_name", customer_id))
        return {"C-0": "Zero Ltd", "C-1": "One Ltd", "C-2": "Two Ltd"}[customer_id]

    async def _pre_execute_hook(self, tool_name, params, state):
        return self._gate(tool_name, params) if self._gate else None


def _agent(tmp_path, **kwargs):
    agent = Ledger(**kwargs)
    agent.program_sandbox = CoderSandbox(workspace_dir=tmp_path, allow_unsafe_local_execution=True)
    agent._current_state = KernelState(
        workflow_id="wf", step_id="s1", agent_id="ledger", task="total the ledger", context={},
    )
    return agent


PROGRAM = """
totals = {}
page = 1
while True:
    data = list_invoices(page)
    for invoice in data["invoices"]:
        totals[invoice["customer_id"]] = totals.get(invoice["customer_id"], 0) + invoice["amount"]
    if page >= data["pages"]:
        break
    page += 1
best = max(totals, key=totals.get)
print(customer_name(best), totals[best])
"""


class TestProgramsRunTheAgentsOwnTools:
    def test_a_program_pages_totals_and_reports_only_what_it_prints(self, tmp_path):
        agent = _agent(tmp_path)

        report = asyncio.run(agent._tool_run_tool_program(PROGRAM))

        assert report["status"] == "success"
        assert report["stdout"].strip() == "Zero Ltd 30.0"
        assert report["tool_calls"] == {"list_invoices": 3, "customer_name": 1}
        assert agent.calls == [("list_invoices", 1), ("list_invoices", 2), ("list_invoices", 3),
                               ("customer_name", "C-0")]
        assert "INV-" not in json.dumps(report)

    def test_every_call_leaves_a_receipt_that_stays_out_of_the_agents_view(self, tmp_path):
        agent = _agent(tmp_path)

        report = asyncio.run(agent._tool_run_tool_program(PROGRAM))

        state = agent._current_state
        assert [r.receipt_id for r in state.tool_history] == report["tool_receipts"]
        assert all(r.via_program for r in state.tool_history)
        assert "INV-" in json.dumps([r.tool_output for r in state.tool_history], default=str)
        context = ContextManager().build_context(state)
        assert "INV-" not in context
        assert "AUTHORITATIVE TOOL RECEIPTS" not in context

    def test_a_tool_error_is_raised_in_the_program(self, tmp_path):
        agent = _agent(tmp_path)

        report = asyncio.run(agent._tool_run_tool_program(
            "try:\n    customer_name('C-9')\nexcept RuntimeError as exc:\n    print('caught', exc)"
        ))

        assert report["status"] == "success"
        assert report["stdout"].startswith("caught customer_name:")

    def test_a_call_awaiting_a_persons_decision_is_not_made_from_a_program(self, tmp_path):
        def approval(tool_name, params):
            return {"status": "waiting", "detail": "needs approval"} if tool_name == "customer_name" else None

        agent = _agent(tmp_path, gate=approval)

        report = asyncio.run(agent._tool_run_tool_program("print(customer_name('C-1'))"))

        assert report["status"] == "error"
        assert "call it directly" in report["error"]
        assert ("customer_name", "C-1") not in agent.calls

    def test_a_failing_program_says_why(self, tmp_path):
        agent = _agent(tmp_path)

        report = asyncio.run(agent._tool_run_tool_program("list_invoices(1)['page_count']"))

        assert report["status"] == "error"
        assert report["error_type"] == "KeyError"
        assert report["tool_calls"] == {"list_invoices": 1}


class TestWhenProgramsAreOffered:
    def test_offered_with_a_sandbox_and_domain_tools(self, tmp_path):
        agent = _agent(tmp_path)
        names = {spec["function"]["name"] for spec in agent._native_tool_specs({})[0]}
        assert "run_tool_program" in names

    def test_not_offered_without_a_sandbox(self):
        agent = Ledger()
        names = {spec["function"]["name"] for spec in agent._native_tool_specs({})[0]}
        assert "run_tool_program" not in names

    def test_not_offered_where_the_sandbox_cannot_run_code(self, tmp_path):
        class Unconfined:
            allow_unsafe_local_execution = False
            confined = False

        agent = Ledger()
        agent.program_sandbox = Unconfined()
        names = {spec["function"]["name"] for spec in agent._native_tool_specs({})[0]}
        assert "run_tool_program" not in names

    def test_the_coder_writes_its_own_code_and_is_not_a_program_host(self, tmp_path):
        assert CoderSubAgent.programmable is False

    def test_the_description_lists_the_tools_and_learns_what_they_return(self, tmp_path):
        agent = _agent(tmp_path)
        before = agent._program_description({})
        assert "list_invoices(page: integer = ...)" in before
        assert "customer_name(customer_id: string)" in before
        assert "list_invoices(page: integer = ...) -> not seen yet" in before
        assert "print a small sample first" in before

        asyncio.run(agent._tool_run_tool_program("list_invoices(1)"))

        after = agent._program_description({})
        assert 'list_invoices(page: integer = ...) -> {"page":"int","pages":"int","invoices":[{' in after


class TestToolDefinitionsHoldStillForTheRun:
    """Tool definitions lead every prompt: one that changes mid-run makes every later turn miss the cache."""

    def test_learning_a_shape_mid_run_leaves_the_definitions_as_they_were(self, tmp_path):
        agent = _agent(tmp_path)
        before, _ = agent._native_tool_specs({})

        asyncio.run(agent._tool_run_tool_program("list_invoices(1)"))
        after, _ = agent._native_tool_specs({})

        assert json.dumps(after) == json.dumps(before)
        tail = agent._shapes_learned_this_run()
        assert tail.startswith("## RETURN SHAPES LEARNED THIS RUN")
        assert '- list_invoices: {"page":"int","pages":"int","invoices":[{' in tail
        # A result in the conversation shows its own shape.
        assert agent._shapes_learned_this_run(frozenset({"list_invoices"})) == ""

    def test_a_new_run_describes_what_the_agent_already_learned(self, tmp_path):
        agent = _agent(tmp_path)
        asyncio.run(agent._tool_run_tool_program("list_invoices(1)"))
        agent._current_state = KernelState(
            workflow_id="wf", step_id="s2", agent_id="ledger", task="again", context={},
        )

        specs, _ = agent._native_tool_specs({})

        program = next(s for s in specs if s["function"]["name"] == "run_tool_program")
        assert '"pages":"int"' in program["function"]["description"]
        assert agent._shapes_learned_this_run() == ""

    def test_read_turn_result_is_offered_from_the_first_turn(self, tmp_path):
        agent = _agent(tmp_path)
        names = {spec["function"]["name"] for spec in agent._native_tool_specs({})[0]}
        assert "read_turn_result" in names
