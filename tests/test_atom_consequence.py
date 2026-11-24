"""A shipped atom may say what one call does, from the call's arguments."""

from unittest.mock import AsyncMock

import pytest

from jarviscore.execution import atom_contract
from jarviscore.execution.atom_contract import read_contract
from jarviscore.kernel.defaults import coder
from jarviscore.kernel.defaults.coder import CoderSubAgent, consequence_as_called
from jarviscore.testing.mocks import MockRedisContextStore

SEND = '''ATOM_POLICY = {
    "effect": "notify",
    "approval": "required",
    "idempotency_fields": ["to", "subject"],
    "consequence": "Sends one email.",
}


def _consequence(params: dict) -> str:
    """What this call does, from its arguments alone."""
    if params.get("subject") == "boom":
        raise ValueError("no")
    if params.get("subject") == "silent":
        return "  "
    return f'Sends an email to {params.get("to")}.\\nSubject: "{params.get("subject")}".'


async def mail_send_message(to: str, subject: str) -> dict:
    """Send one email."""
    return await nexus_call("POST", "https://example.test/send", json={"to": to})
'''


@pytest.fixture
def atom():
    result = read_contract(SEND, system="mail", expected_name="mail_send_message")
    assert result.ok, result.report()
    return result.atom


@pytest.fixture
def shipped(monkeypatch):
    """The package ships SEND as mail_send_message."""
    monkeypatch.setattr(atom_contract, "shipped_source", lambda atom: SEND)
    coder._consequence_hook.cache_clear()


def test_a_shipped_atom_words_the_call_from_its_arguments(atom, shipped):
    said = consequence_as_called(atom, SEND, {"to": "ana@example.com", "subject": "Hello"})
    assert said == 'Sends an email to ana@example.com. Subject: "Hello".'


def test_source_that_is_not_the_shipped_file_keeps_the_sentence_it_declares(atom, shipped):
    repaired = SEND.replace("Send one email.", "Send one email, repaired.")
    assert consequence_as_called(atom, repaired, {"to": "a@example.com"}) == "Sends one email."
    assert consequence_as_called(atom, None, {"to": "a@example.com"}) == "Sends one email."


def test_an_atom_the_package_does_not_ship_is_never_run_here(atom):
    assert consequence_as_called(atom, SEND, {"to": "a@example.com"}) == "Sends one email."


def test_a_hook_that_fails_or_says_nothing_leaves_the_declared_sentence(atom, shipped):
    for subject in ("boom", "silent"):
        assert consequence_as_called(atom, SEND, {"subject": subject}) == "Sends one email."


def test_a_long_sentence_is_cut_and_an_atom_without_a_hook_is_unchanged(
    atom, shipped, monkeypatch,
):
    long = consequence_as_called(atom, SEND, {"to": "x" * 5000, "subject": "s"})
    assert len(long) == 1500
    plain = SEND[:SEND.index("def _consequence")] + SEND[SEND.index("async def"):]
    monkeypatch.setattr(atom_contract, "shipped_source", lambda atom: plain)
    assert consequence_as_called(atom, plain, {"to": "a@example.com"}) == "Sends one email."


@pytest.mark.asyncio
async def test_the_person_is_asked_with_the_calls_own_sentence_and_it_runs_once_approved(
    atom, shipped,
):
    class Registry:
        def get_function_code(self, name):
            return SEND

        def update_execution_stats(self, *args, **kwargs):
            pass

    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry()
    agent.redis_store = MockRedisContextStore()
    agent._tool_execute_code = AsyncMock(return_value={"status": "success", "data": {}})
    call = agent._atom_tool(atom.name)

    waiting = await call(to="ana@example.com", subject="Hello")
    assert waiting["typed_outcome"] == "WAITING_FOR_APPROVAL"
    assert waiting["consequence"] == 'Sends an email to ana@example.com. Subject: "Hello".'
    request = agent.redis_store.get_hitl_request("wf", "step", waiting["action_id"])
    assert request["action"]["params"] == {"to": "ana@example.com", "subject": "Hello"}

    agent.redis_store.resolve_hitl_request("wf", "step", "approve", action_id=waiting["action_id"])
    assert (await call(to="ana@example.com", subject="Hello"))["status"] == "success"
    agent._tool_execute_code.assert_awaited_once()
