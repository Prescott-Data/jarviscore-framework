"""Replay: a recorded run re-simulated from its record reproduces its decisions, effects stubbed."""
import json
import os

import pytest

from jarviscore.control import policy as policy_module
from jarviscore.evidence import journal as journal_module
from jarviscore.evidence.journal import verify
from jarviscore.evidence.replay import replay, runs
from jarviscore.kernel.subagent import BaseSubAgent


def call(name, arguments, call_id=None):
    return {"tool_calls": [{"id": call_id or f"call_{name}", "name": name, "arguments": json.dumps(arguments)}]}


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def carries_native_tools(self, model=None):
        return True

    async def generate(self, messages=None, **kwargs):
        self.calls += 1
        reply = self.replies.pop(0)
        return {"content": None, "tool_calls": [], "tokens": {"input": 10, "output": 5, "total": 15},
                "cost_usd": 0.0, **reply}


class LedgerAgent(BaseSubAgent):
    """Looks up an invoice and pays it: one read, one effect."""

    effects = []

    def __init__(self, agent_id="ledger", llm_client=None):
        super().__init__(agent_id=agent_id, role="ledger", llm_client=llm_client)

    def get_system_prompt(self) -> str:
        return "You settle invoices."

    def setup_tools(self) -> None:
        self.register_tool("lookup", self._lookup, "Look up an invoice.")
        self.register_tool("pay", self._pay, "Pay an invoice.")

    async def _lookup(self, invoice: str):
        return {"status": "success", "invoice": invoice, "amount": 1250}

    async def _pay(self, invoice: str, amount: int):
        LedgerAgent.effects.append((invoice, amount))
        return {"status": "success", "payment": "PAY-1"}

    def _can_complete(self, state, parsed):
        return True, ""


SCRIPT = [
    call("lookup", {"invoice": "INV-7"}),
    call("pay", {"invoice": "INV-7", "amount": 1250}),
    call("done", {"summary": "Paid INV-7: PAY-1.", "result": {}, "complete": True}),
]


@pytest.fixture
def journal(monkeypatch, tmp_path):
    def configure(capture="full"):
        (tmp_path / "policy.json").write_text("{}")
        monkeypatch.setenv("JARVISCORE_CONTROL_MODE", "report")
        monkeypatch.setenv("JARVISCORE_CONTROL_POLICY", str(tmp_path / "policy.json"))
        monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(tmp_path / "journal"))
        monkeypatch.setenv("JARVISCORE_JOURNAL_CAPTURE", capture)
        monkeypatch.setattr(policy_module, "_cached", None)
        monkeypatch.setattr(journal_module, "_journal", None)
        LedgerAgent.effects = []
        return str(tmp_path / "journal")
    return configure


async def record(root):
    agent = LedgerAgent(llm_client=ScriptedLLM(SCRIPT))
    output = await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})
    assert output.status == "success" and LedgerAgent.effects == [("INV-7", 1250)]
    return output


@pytest.mark.asyncio
async def test_a_recorded_run_replays_to_the_same_decisions_with_no_model_and_no_effect(journal):
    root = journal()
    await record(root)
    LedgerAgent.effects = []

    report = await replay(root, "wf/pay")

    assert report.reproduced, report.divergence
    assert report.decisions == 2 and report.model_calls == 3
    assert report.requests_matched == 3  # the agent asked the model exactly what it asked before
    assert LedgerAgent.effects == []  # nothing was paid again
    assert runs(root) == ["wf/pay"]
    assert verify(root).ok


@pytest.mark.asyncio
async def test_a_changed_agent_diverges_and_the_replay_says_where(journal):
    root = journal()
    await record(root)

    class Stingier(LedgerAgent):
        def get_system_prompt(self) -> str:
            return "You settle invoices, but never above 1000."

    report = await replay(root, "wf/pay", factory=lambda agent_id, llm: Stingier(agent_id, llm))

    # Same recorded answers, so the same decisions; but the requests were not the ones the record holds.
    assert report.reproduced and report.requests_matched == 0


@pytest.mark.asyncio
async def test_an_agent_that_now_decides_differently_diverges_at_that_decision(journal):
    root = journal()
    await record(root)

    class Cautious(LedgerAgent):
        async def _pre(self, *args):
            return None

        def setup_tools(self) -> None:
            super().setup_tools()

    report = await replay(root, "wf/pay", factory=lambda agent_id, llm: Cautious(agent_id, llm))
    assert report.reproduced

    # Edit the record of the first decision's arguments: the replayed agent no longer matches it.
    events = [json.loads(line) for line in open(os.path.join(root, "runs", "wf_pay.jsonl"))]
    first = next(e for e in events if e["kind"] == "tool.result")
    first["data"]["params"] = "0" * 64
    from jarviscore.evidence import replay as replay_module

    original = replay_module._records
    replay_module._records = lambda *_: events
    try:
        report = await replay(root, "wf/pay")
    finally:
        replay_module._records = original
    assert not report.reproduced and "decision 1: lookup was called with other arguments" in report.divergence


@pytest.mark.asyncio
async def test_tampered_content_is_caught(journal):
    root = journal()
    await record(root)
    content = os.path.join(root, "content")
    for folder in os.listdir(content):
        for name in os.listdir(os.path.join(content, folder)):
            path = os.path.join(content, folder, name)
            text = open(path).read()
            if "PAY-1" in text and "payment" in text:
                open(path, "w").write(text.replace("PAY-1", "PAY-9"))

    with pytest.raises(ValueError, match="does not match its digest"):
        await replay(root, "wf/pay")


@pytest.mark.asyncio
async def test_a_digest_only_record_is_verifiable_but_says_it_cannot_be_replayed(journal):
    root = journal(capture="digests")
    await record(root)

    report = await replay(root, "wf/pay")

    assert verify(root).ok
    assert not report.reproduced and "JOURNAL_CAPTURE=full" in report.divergence


@pytest.mark.asyncio
async def test_a_journal_that_cannot_be_written_never_breaks_a_run(journal, monkeypatch, tmp_path):
    journal()
    blocked = tmp_path / "read-only"
    blocked.mkdir()
    blocked.chmod(0o500)
    monkeypatch.setenv("JARVISCORE_JOURNAL_DIR", str(blocked / "journal"))
    monkeypatch.setattr(journal_module, "_journal", None)
    try:
        output = await LedgerAgent(llm_client=ScriptedLLM(SCRIPT)).run(
            task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})
    finally:
        blocked.chmod(0o700)
    assert output.status == "success"


@pytest.mark.asyncio
async def test_concurrent_runs_of_one_agent_each_record_their_own_run_and_leave_it_clean(journal):
    import asyncio

    root = journal()

    class Slow(ScriptedLLM):
        async def generate(self, messages=None, **kwargs):
            await asyncio.sleep(0.01)
            return await super().generate(messages=messages, **kwargs)

    agent = LedgerAgent(llm_client=Slow(SCRIPT + SCRIPT))
    real = agent.llm_client
    await asyncio.gather(
        agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "a"}),
        agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "b"}),
    )

    assert getattr(agent.llm_client, "_jc_inner", None) is real  # wrapped once, never stacked
    recorded = 0
    for run in ("wf/a", "wf/b"):
        events = [json.loads(line) for line in open(os.path.join(root, "runs", run.replace("/", "_") + ".jsonl"))]
        assert [e["kind"] for e in events].count("run.start") == 1
        recorded += sum(e["kind"] == "model.call" for e in events)
    assert recorded == real.calls  # every call recorded once, in the run that made it


@pytest.mark.asyncio
async def test_old_replay_content_is_pruned_and_the_journal_still_verifies(journal):
    import time as time_module

    from jarviscore.evidence.journal import prune_content

    root = journal()
    await record(root)
    old = time_module.time() - 40 * 86400
    for folder, _, names in os.walk(os.path.join(root, "content")):
        for name in names:
            os.utime(os.path.join(folder, name), (old, old))

    assert prune_content(root, 30) > 0
    assert verify(root).ok
    report = await replay(root, "wf/pay")
    assert not report.reproduced and "not kept" in report.divergence


@pytest.mark.asyncio
async def test_a_tool_offered_at_run_time_is_replayed_as_it_was_offered(journal):
    root = journal()
    agent = LedgerAgent(llm_client=ScriptedLLM(SCRIPT))
    schema = {"type": "object", "properties": {"invoice": {"type": "string"}}}
    agent.register_tool("erp_extra", lambda **_: {"status": "success"}, "An integration offered at run time.",
                        phase="action", parameters=schema)
    await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})

    rebuilt = []

    def factory(agent_id, llm):
        rebuilt.append(LedgerAgent(agent_id=agent_id, llm_client=llm))
        return rebuilt[-1]

    report = await replay(root, "wf/pay", factory=factory)
    assert report.reproduced, report.divergence
    tool = rebuilt[0]._tools["erp_extra"]
    # Same description and schema the model saw, charged to the same budget.
    assert (tool.description, tool.declared_phase, tool.parameters) == (
        "An integration offered at run time.", "action", schema)
    assert report.requests_matched == report.model_calls


class ReviewedLedgerAgent(LedgerAgent):
    """A gate asks the model before each payment, as the effect reviewer does."""

    async def _pre_execute_hook(self, tool_name, params, state):
        if tool_name == "pay":
            await self.llm_client.generate(messages=[{"role": "user", "content": "Review this payment."}])
        return await super()._pre_execute_hook(tool_name, params, state)


@pytest.mark.asyncio
async def test_a_gate_s_own_model_call_is_not_handed_to_the_agent_on_replay(journal):
    root = journal()
    reviewed = [SCRIPT[0], SCRIPT[1], {"content": '{"allow": true}'}, SCRIPT[2]]
    agent = ReviewedLedgerAgent(llm_client=ScriptedLLM(reviewed))
    output = await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})
    assert output.status == "success" and agent.llm_client.calls == 4

    report = await replay(root, "wf/pay")

    assert report.reproduced, report.divergence
    # The gate's call is played back with the gate; the agent gets only its own three answers.
    assert report.model_calls == 3 and report.requests_matched == 3


class _Sandbox:
    def get_manifest(self):
        return "- fetch() (function/callable)"


class SandboxedLedgerAgent(LedgerAgent):
    """Its prompt names what its sandbox offers, as the coder's does."""

    def __init__(self, agent_id="ledger", llm_client=None, sandbox=None):
        self.sandbox = sandbox
        super().__init__(agent_id=agent_id, llm_client=llm_client)

    def get_system_prompt(self) -> str:
        manifest = self.sandbox.get_manifest() if self.sandbox else ""
        return "You settle invoices." + (f"\n\n## SANDBOX ENVIRONMENT\n{manifest}" if manifest else "")


@pytest.mark.asyncio
async def test_the_sandbox_s_description_is_part_of_the_replayed_prompt(journal):
    root = journal()
    agent = SandboxedLedgerAgent(llm_client=ScriptedLLM(SCRIPT), sandbox=_Sandbox())
    await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})

    report = await replay(root, "wf/pay")  # rebuilt with no sandbox, as every replay is

    assert report.reproduced, report.divergence
    assert report.requests_matched == report.model_calls == 3


class Memory:
    """Cross-session memory and checkpoints, as the Kernel attaches them."""

    def __init__(self):
        self.checkpoint = None

    async def recall(self, query, limit=5):
        return []

    async def remember(self, text, kind=None, role=None):
        return True

    async def load_checkpoint(self):
        return self.checkpoint

    async def save_checkpoint(self, raw):
        self.checkpoint = raw

    async def log_turn(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_tools_offered_because_memory_was_attached_are_offered_on_replay(journal):
    root = journal()
    agent = LedgerAgent(llm_client=ScriptedLLM(SCRIPT))
    await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"}, memory=Memory())

    report = await replay(root, "wf/pay")  # no memory on replay

    assert report.reproduced, report.divergence
    assert report.requests_matched == report.model_calls == 3


@pytest.mark.asyncio
async def test_a_resumed_run_replays_from_its_checkpoint(journal):
    root = journal()
    memory = Memory()
    context = {"workflow_id": "wf", "step_id": "pay"}
    first = LedgerAgent(llm_client=ScriptedLLM(SCRIPT[:2] + [{"content": "", "tool_calls": []}] * 3))
    await first.run(task="Pay invoice INV-7", context=context, max_turns=3, memory=memory)
    assert memory.checkpoint
    resumed = LedgerAgent(llm_client=ScriptedLLM([SCRIPT[2]]))
    output = await resumed.run(task="Pay invoice INV-7", context={**context, "_resume": True}, memory=memory)
    assert output.status == "success"

    report = await replay(root, "wf/pay")  # the resumed run: the last one recorded

    assert report.reproduced, report.divergence
    # It asked the model with the conversation it resumed with, as recorded.
    assert report.requests_matched == report.model_calls == 1


@pytest.mark.asyncio
async def test_a_tool_the_runtime_added_is_offered_with_the_same_arguments_on_replay(journal):
    root = journal()
    agent = LedgerAgent(llm_client=ScriptedLLM(SCRIPT))

    def read_mailbox(limit: int = 10):
        return {"status": "success", "messages": []}

    # As the Kernel adds it: no declared schema, so its arguments are read from its signature.
    agent.register_tool("read_mailbox", read_mailbox, "Read unread notifications.")
    await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})

    report = await replay(root, "wf/pay")

    assert report.reproduced, report.divergence
    assert report.requests_matched == report.model_calls == 3


class SetUpLedgerAgent(LedgerAgent):
    """Like the coder: its run looks at the host first, and offers and prompts from what it found."""

    host = {"providers": 3}

    async def run(self, task, context=None, **kwargs):
        self._found = self.host["providers"]
        self.register_tool("request_access", self._lookup, f"Connect one of {self._found} providers.")
        return await super().run(task, context, **kwargs)

    def get_system_prompt(self) -> str:
        return f"You settle invoices. {getattr(self, '_found', 0)} providers are registered."

    def _replay_facts(self):
        return {"found": self._found}

    def _restore_replay_facts(self, facts):
        self._found = facts["found"]


@pytest.mark.asyncio
async def test_what_the_agent_s_setup_found_on_the_host_is_what_it_is_prompted_with_on_replay(journal, monkeypatch):
    root = journal()
    agent = SetUpLedgerAgent(llm_client=ScriptedLLM(SCRIPT))
    await agent.run(task="Pay invoice INV-7", context={"workflow_id": "wf", "step_id": "pay"})
    monkeypatch.setattr(SetUpLedgerAgent, "host", {"providers": 0})  # the replay's host has none

    report = await replay(root, "wf/pay")

    assert report.reproduced, report.divergence
    assert report.requests_matched == report.model_calls == 3
