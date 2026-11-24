from unittest.mock import AsyncMock

import pytest

from jarviscore.execution.atom_contract import read_contract
from jarviscore.kernel.defaults.coder import CoderSubAgent
from jarviscore.testing.mocks import MockRedisContextStore


SOURCE = '''
ATOM_POLICY = {
    "effect": "destructive",
    "approval": "required",
    "idempotency_fields": ["message_id"],
    "consequence": "Permanently deletes the message.",
}
async def gmail_delete_message(message_id: str) -> dict:
    """Delete one message."""
    return await nexus_call("DELETE", f"https://example.test/messages/{message_id}")
'''

WRITE_SOURCE = '''
ATOM_POLICY = {
    "effect": "write",
    "approval": "never",
    "idempotency_fields": ["summary", "start_datetime", "end_datetime"],
    "consequence": "Creates one calendar event.",
}
async def google_calendar_create_event(
    summary: str, start_datetime: str, end_datetime: str
) -> dict:
    """Create one calendar event."""
    return await nexus_call("POST", "https://example.test/events", json={
        "summary": summary, "start": start_datetime, "end": end_datetime,
    })
'''


class Registry:
    def get_function_code(self, name):
        return SOURCE

    def update_execution_stats(self, *args, **kwargs):
        pass


class ExecutionStore:
    def __init__(self):
        self.results = {}

    def get_atom_execution(self, action_id):
        return self.results.get(action_id)

    def save_atom_execution(self, action_id, result):
        self.results[action_id] = result


def test_http_delete_without_policy_is_rejected():
    source = '''
async def demo_delete_item(item_id: str) -> dict:
    """Delete one item."""
    return await nexus_call("DELETE", f"https://example.test/{item_id}")
'''
    contract = read_contract(source, system="demo", expected_name="demo_delete_item")
    assert not contract.ok
    assert "require a destructive ATOM_POLICY" in contract.report()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
def test_http_mutation_without_policy_is_never_treated_as_read(method):
    source = f'''\nasync def shop_create_item(item: dict) -> dict:\n    """Create one item."""\n    return await nexus_call("{method}", "https://example.test/items", json=item)\n'''

    contract = read_contract(source, system="shop", expected_name="shop_create_item")

    assert not contract.ok
    assert "require an explicit ATOM_POLICY" in contract.report()


def test_idempotency_fields_must_name_parameters():
    invalid = SOURCE.replace('["message_id"]', '["missing_id"]')
    contract = read_contract(invalid, system="gmail", expected_name="gmail_delete_message")
    assert not contract.ok
    assert "must name parameters" in contract.report()


def test_write_atom_requires_idempotency_identity_and_consequence():
    invalid = WRITE_SOURCE.replace(
        '"idempotency_fields": ["summary", "start_datetime", "end_datetime"],',
        '"idempotency_fields": [],',
    )
    contract = read_contract(
        invalid, system="google_calendar", expected_name="google_calendar_create_event"
    )
    assert not contract.ok
    assert "write atoms require idempotency_fields" in contract.report()


@pytest.mark.asyncio
async def test_approval_precedes_execution_and_retry_is_idempotent():
    atom = read_contract(
        SOURCE, system="gmail", expected_name="gmail_delete_message"
    ).atom
    assert atom is not None
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry()
    agent.redis_store = MockRedisContextStore()
    agent._tool_execute_code = AsyncMock(
        return_value={"status": "success", "data": {"deleted": True}}
    )
    call = agent._atom_tool(atom.name)

    waiting = await call(message_id="m-1")
    assert waiting["typed_outcome"] == "WAITING_FOR_APPROVAL"
    assert waiting["consequence"] == "Permanently deletes the message."
    agent._tool_execute_code.assert_not_awaited()
    request = agent.redis_store.get_hitl_request("wf", "step", waiting["action_id"])
    assert request["action"]["params"] == {"message_id": "m-1"}

    agent.redis_store.resolve_hitl_request(
        "wf", "step", "approve", action_id=waiting["action_id"]
    )
    first = await call(message_id="m-1")
    retry = await call(message_id="m-1")

    assert first["status"] == retry["status"] == "success"
    assert "already ran" in retry["note"]
    agent._tool_execute_code.assert_awaited_once()
    settled = agent.redis_store.get_hitl_request("wf", "step", waiting["action_id"])
    assert settled["outcome"] == {"status": "success", "data": {"deleted": True}}


@pytest.mark.asyncio
async def test_a_declined_atom_never_runs():
    atom = read_contract(
        SOURCE, system="gmail", expected_name="gmail_delete_message"
    ).atom
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry()
    agent.redis_store = MockRedisContextStore()
    agent._tool_execute_code = AsyncMock()
    call = agent._atom_tool(atom.name)

    waiting = await call(message_id="m-1")
    agent.redis_store.resolve_hitl_request(
        "wf", "step", "reject", action_id=waiting["action_id"]
    )

    assert (await call(message_id="m-1"))["semantic_error"] == "ACTION_DECLINED"
    agent._tool_execute_code.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_atom_executes_without_approval_and_retry_is_idempotent():
    atom = read_contract(
        WRITE_SOURCE,
        system="google_calendar",
        expected_name="google_calendar_create_event",
    ).atom
    assert atom is not None
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "calendar"}
    agent.code_registry = Registry()
    agent.redis_store = ExecutionStore()
    agent._tool_execute_code = AsyncMock(
        return_value={"status": "success", "data": {"event_id": "evt-1"}}
    )
    call = agent._atom_tool(atom.name)

    first = await call(
        summary="Discovery Call",
        start_datetime="2026-09-10T13:00:00+03:00",
        end_datetime="2026-09-10T13:30:00+03:00",
    )
    retry = await call(
        summary="Discovery Call",
        start_datetime="2026-09-10T13:00:00+03:00",
        end_datetime="2026-09-10T13:30:00+03:00",
    )

    assert first == retry
    agent._tool_execute_code.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_retry_is_recognised_inside_its_own_work_and_not_across_others():
    """The "already ran" record stops a retry repeating an effect: the same step
    dispatched again, or another step of the same workflow making the same call. It does
    not answer for a later, separate piece of work: asked on Tuesday to do again what was
    done on Monday, the atom runs. Kept under the action alone, a second request to archive
    a message that had come back was told it had already run, and nothing happened."""
    atom = read_contract(
        WRITE_SOURCE, system="google_calendar", expected_name="google_calendar_create_event",
    ).atom
    store = ExecutionStore()
    event = {"summary": "Discovery Call", "start_datetime": "2026-09-10T13:00:00+03:00",
             "end_datetime": "2026-09-10T13:30:00+03:00"}

    def agent_in(workflow, step):
        agent = CoderSubAgent.__new__(CoderSubAgent)
        agent._atoms = {atom.name: atom}
        agent._run_context = {"workflow_id": workflow, "step_id": step}
        agent.code_registry = Registry()
        agent.redis_store = store
        agent._tool_execute_code = AsyncMock(
            return_value={"status": "success", "data": {"event_id": f"evt-{workflow}"}})
        return agent

    monday = agent_in("monday", "book")
    first = await monday._atom_tool(atom.name)(**event)
    again = await monday._atom_tool(atom.name)(**event)
    assert first == again
    monday._tool_execute_code.assert_awaited_once()
    # another step of the same work (a repaired plan re-issuing the write) is still a retry
    repaired = agent_in("monday", "book-again")
    assert await repaired._atom_tool(atom.name)(**event) == first
    repaired._tool_execute_code.assert_not_awaited()
    # a separate piece of work runs
    tuesday = agent_in("tuesday", "book")
    later = await tuesday._atom_tool(atom.name)(**event)
    tuesday._tool_execute_code.assert_awaited_once()
    assert later["data"] == {"event_id": "evt-tuesday"}
    # work that names no workflow keeps the record under the action alone, as before
    loose, loose_again = agent_in("", "a"), agent_in("", "b")
    await loose._atom_tool(atom.name)(**event)
    await loose_again._atom_tool(atom.name)(**event)
    loose._tool_execute_code.assert_awaited_once()
    loose_again._tool_execute_code.assert_not_awaited()


OUTBOUND_ATOMS = [
    ("gmail", "gmail_send_email"),
    ("msgraph", "msgraph_send_email"),
    ("msgraph", "msgraph_send_chat_message"),
    ("telegram", "telegram_create_message"),
    ("whatsapp_business", "whatsapp_business_create_message"),
    ("twilio", "twilio_create_message"),
    ("sendgrid", "sendgrid_send_email"),
    ("linkedin", "linkedin_create_post"),
    ("twitter", "twitter_post_tweet"),
    ("twitter", "twitter_reply_tweet"),
]


@pytest.mark.parametrize("system,name", OUTBOUND_ATOMS)
def test_speaking_for_the_user_waits_for_their_approval(system, name):
    from pathlib import Path

    import jarviscore

    source = (Path(jarviscore.__file__).parent / "integrations" / "atoms" / system / f"{name}.py").read_text()
    contract = read_contract(source, system=system, expected_name=name)

    assert contract.ok, contract.report()
    assert contract.atom.policy.effect == "notify"
    assert contract.atom.policy.requires_approval


@pytest.mark.asyncio
async def test_an_application_guard_refuses_before_approval_or_execution():
    atom = read_contract(
        SOURCE, system="gmail", expected_name="gmail_delete_message"
    ).atom
    seen = []

    def guard(guarded_atom, params, context):
        seen.append((guarded_atom.name, params, context["step_id"]))
        return "the recipient is suppressed"

    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._atoms = {atom.name: atom}
    agent._run_context = {"workflow_id": "wf", "step_id": "step"}
    agent.code_registry = Registry()
    agent.redis_store = MockRedisContextStore()
    agent.effect_guards = (guard,)
    agent._tool_execute_code = AsyncMock()

    refused = await agent._atom_tool(atom.name)(message_id="m-1")

    assert refused["semantic_error"] == "EFFECT_REFUSED_BY_GUARD"
    assert "the recipient is suppressed" in refused["error"]
    assert "typed_outcome" not in refused
    assert seen == [("gmail_delete_message", {"message_id": "m-1"}, "step")]
    agent._tool_execute_code.assert_not_awaited()

    agent.effect_guards = (lambda *_: None,)
    waiting = await agent._atom_tool(atom.name)(message_id="m-1")
    assert waiting["typed_outcome"] == "WAITING_FOR_APPROVAL"
