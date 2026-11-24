"""Which shipped atoms a step is offered, by the step's effect."""
from pathlib import Path
from types import SimpleNamespace

import pytest

import jarviscore
from jarviscore.kernel.defaults.coder import CoderSubAgent

ATOMS = Path(jarviscore.__file__).parent / "integrations" / "atoms" / "google_calendar"
NAMES = (
    "google_calendar_list_events", "google_calendar_create_event", "google_calendar_delete_event",
)


def _offered(effect: str) -> set:
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent._run_context = {"effect": effect}
    agent.code_registry = SimpleNamespace(
        get_functions_by_system=lambda system: [{"function_name": name} for name in NAMES],
        get_function_code=lambda name: (ATOMS / f"{name}.py").read_text(),
    )
    return set(agent._valid_atoms("google_calendar"))


@pytest.mark.parametrize("effect, offered", [
    ("read", {"google_calendar_list_events"}),
    ("write", {"google_calendar_list_events", "google_calendar_create_event"}),
    # Sending an invitation is creating the event with its guests: a step that notifies is
    # offered the atom that writes, or it has nothing to send the invitation with.
    ("notify", {"google_calendar_list_events", "google_calendar_create_event"}),
    # Removing is often two acts, or a different one: replacing an event is deleting it and
    # creating its successor, and a meeting someone else organises is declined (an answer,
    # which notifies), not deleted. A step that deletes is offered every atom.
    ("destructive", {"google_calendar_list_events", "google_calendar_create_event",
                     "google_calendar_delete_event"}),
])
def test_a_step_is_offered_the_atoms_its_effect_covers(effect, offered):
    assert _offered(effect) == offered


def test_a_step_that_only_reads_is_never_offered_an_atom_that_changes_anything():
    for effect in ("read", "propose", "final_response"):
        assert _offered(effect) == {"google_calendar_list_events"}


DECLINE = '''ATOM_POLICY = {
    "effect": "notify",
    "approval": "required",
    "idempotency_fields": ["event_id"],
    "consequence": "Declines one invitation; the organiser is told.",
}


async def google_calendar_decline_event(event_id: str) -> dict:
    """Decline an invitation."""
    resp = await nexus_call("PATCH", f"https://www.googleapis.com/calendar/v3/{event_id}")
    return {"success": resp["ok"]}
'''


def test_a_step_that_deletes_is_offered_the_atoms_that_notify():
    """An atom that answers an invitation declares "notify"; getting the person out of
    someone else's meeting is a step that deletes, and that atom is what does it."""
    agent = CoderSubAgent.__new__(CoderSubAgent)
    agent.code_registry = SimpleNamespace(
        get_functions_by_system=lambda system: [{"function_name": "google_calendar_decline_event"}],
        get_function_code=lambda name: DECLINE,
    )
    agent._run_context = {"effect": "destructive"}
    assert set(agent._valid_atoms("google_calendar")) == {"google_calendar_decline_event"}
    for effect in ("write", "read"):
        agent._run_context = {"effect": effect}
        assert agent._valid_atoms("google_calendar") == {}  # a write step never sends
