"""The Calendar atoms: the request each sends, the result it shapes, what it refuses, and
what it says a call does."""

import pytest

from jarviscore.execution.atom_contract import SHIPPED_ATOMS_DIR, read_contract

SYSTEM = "google_calendar"
DIR = SHIPPED_ATOMS_DIR / SYSTEM
API = "https://www.googleapis.com/calendar/v3/"


def contract(name):
    """The shipped atom's source read against the contract."""
    return read_contract((DIR / f"{name}.py").read_text(encoding="utf-8"),
                         system=SYSTEM, expected_name=name)


def atom(name):
    result = contract(name)
    assert result.ok, result.report()
    return result.atom


def consequence(name, params):
    """What the atom says a call does, from its arguments (its `_consequence`)."""
    namespace = {}
    exec((DIR / f"{name}.py").read_text(encoding="utf-8"), namespace)  # noqa: S102
    return namespace["_consequence"](params)


def load(name, answer):
    """The atom's function with `nexus_call` answered by `answer(method, path, kwargs)`,
    which returns a JSON body, or (status, body) for a refusal."""
    calls = []

    async def nexus_call(method, url, **kwargs):
        path = url.removeprefix(API)
        calls.append((method, path, kwargs))
        body = answer(method, path, kwargs)
        if isinstance(body, tuple):
            status, reason = body
            return {"ok": status < 300, "status_code": status, "body": str(reason), "headers": {},
                    "json": reason if isinstance(reason, dict) else None}
        return {"ok": True, "status_code": 200, "json": body, "body": "", "headers": {}}

    namespace = {"nexus_call": nexus_call}
    exec((DIR / f"{name}.py").read_text(encoding="utf-8"), namespace)  # noqa: S102
    return namespace[name], calls


def refused(reason, status=403):
    return (status, {"error": {"code": status, "message": reason}})


EVENT = {
    "id": "e1", "status": "confirmed", "summary": "Call with Sam",
    "start": {"dateTime": "2026-11-24T11:30:00-05:00", "timeZone": "America/New_York"},
    "end": {"dateTime": "2026-11-24T12:00:00-05:00", "timeZone": "America/New_York"},
    "organizer": {"email": "owner@example.com", "self": True},
    "attendees": [
        {"email": "owner@example.com", "self": True, "responseStatus": "accepted"},
        {"email": "sam@example.com", "responseStatus": "needsAction", "displayName": "Sam"},
    ],
    "hangoutLink": "https://meet.google.com/abc-defg-hij",
    "htmlLink": "https://calendar.google.com/event?eid=e1",
}
THEIRS = {
    **EVENT, "id": "e2", "summary": "Board prep",
    "organizer": {"email": "lee@example.com"},
    "attendees": [
        {"email": "lee@example.com", "organizer": True, "responseStatus": "accepted"},
        {"email": "owner@example.com", "self": True, "responseStatus": "needsAction"},
    ],
}


EFFECTS = {
    "google_calendar_list_events": "read",
    "google_calendar_list_calendars": "read",
    "google_calendar_find_free_time": "read",
    "google_calendar_create_event": "write",
    "google_calendar_update_event": "write",
    "google_calendar_delete_event": "destructive",
    "google_calendar_respond_to_event": "notify",
}


def test_every_calendar_atom_passes_the_contract_with_the_effect_it_should_have():
    assert {p.stem for p in DIR.glob("google_calendar_*.py")} == set(EFFECTS)
    for name, effect in EFFECTS.items():
        policy = atom(name).policy
        assert policy.effect == effect, name
        if effect != "read":
            assert policy.idempotency_fields and policy.consequence, name


def test_changing_cancelling_and_answering_wait_for_approval_and_the_reads_never_do():
    """What each atom declares; an institution's control policy may ask for more."""
    for name in ("google_calendar_update_event", "google_calendar_delete_event",
                 "google_calendar_respond_to_event"):
        assert atom(name).policy.requires_approval, name
    for name in ("google_calendar_list_events", "google_calendar_list_calendars",
                 "google_calendar_find_free_time"):
        assert not atom(name).policy.requires_approval, name


def test_the_one_read_that_posts_posts_only_the_free_busy_query():
    """A declared read with a POST stays a read. That is right for exactly as long as the
    POST is Google's free/busy query and nothing else."""
    source = (DIR / "google_calendar_find_free_time.py").read_text(encoding="utf-8")
    assert atom("google_calendar_find_free_time").policy.effect == "read"
    assert source.count('"POST"') == 1 and 'f"{_API}/freeBusy"' in source
    for verb in ('"PUT"', '"PATCH"', '"DELETE"'):
        assert verb not in source


# ── find_events ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_find_events_requires_a_range_and_returns_what_the_next_step_needs():
    series = {**THEIRS, "id": "e3_20261124", "recurringEventId": "e3", "summary": "Standup",
              "hangoutLink": None, "conferenceData": {"entryPoints": [
                  {"entryPointType": "phone", "uri": "tel:+1"},
                  {"entryPointType": "video", "uri": "https://zoom.us/j/1"}]}}
    day_off = {"id": "e4", "summary": "Offsite", "eventType": "outOfOffice",
               "start": {"date": "2026-11-25"}, "end": {"date": "2026-11-27"}}
    gone = {"id": "e5", "status": "cancelled"}
    tool, calls = load("google_calendar_list_events", lambda *a: {
        "timeZone": "America/New_York", "nextPageToken": "p2",
        "items": [EVENT, series, day_off, gone]})
    out = await tool(time_min="2026-11-24T00:00:00-05:00", time_max="2026-11-27T00:00:00-05:00",
                     query="sam", max_results=500)
    assert out["success"], out
    method, path, kwargs = calls[0]
    assert (method, path) == ("GET", "calendars/primary/events")
    assert kwargs["params"]["timeMin"] == "2026-11-24T00:00:00-05:00"
    assert kwargs["params"]["singleEvents"] == "true" and kwargs["params"]["q"] == "sam"
    assert kwargs["params"]["orderBy"] == "startTime" and kwargs["params"]["maxResults"] == 50
    data = out["data"]
    assert data["count"] == 3 and data["next_page_token"] == "p2"
    first, second, third = data["events"]
    assert first["meet_link"] == "https://meet.google.com/abc-defg-hij"
    assert first["organized_by_me"] and first["my_response"] == "accepted"
    assert first["guests"] == [
        {"email": "sam@example.com", "name": "Sam", "response": "needsAction"}]
    assert first["guest_count"] == 1 and not first["all_day"] and not first["repeats"]
    assert second["repeats"] and second["series_id"] == "e3"
    assert second["meet_link"] == "https://zoom.us/j/1" and second["my_response"] == "needsAction"
    assert third["all_day"] and third["start"] == "2026-11-25"
    assert third["event_type"] == "outOfOffice"

    for bad in ({"time_min": "", "time_max": "2026-11-27T00:00:00-05:00"},
                {"time_min": "2026-11-24", "time_max": "2026-11-27T00:00:00-05:00"},
                {"time_min": "2026-11-24T00:00:00", "time_max": "2026-11-27T00:00:00-05:00"}):
        refusal = await tool(**bad)
        assert not refusal["success"] and "UTC offset" in refusal["error"]
    assert len(calls) == 1  # a refused call never reaches Google


@pytest.mark.asyncio
async def test_find_events_pages_and_says_googles_reason_when_refused():
    tool, calls = load("google_calendar_list_events", lambda *a: {"items": []})
    out = await tool(time_min="2026-11-24T00:00:00Z", time_max="2026-11-25T00:00:00Z",
                     page_token="p2", calendar_id="team@group.calendar.google.com")
    assert calls[0][1] == "calendars/team@group.calendar.google.com/events"
    assert calls[0][2]["params"]["pageToken"] == "p2" and "q" not in calls[0][2]["params"]
    assert out["data"]["events"] == [] and "next_page_token" not in out["data"]
    tool, _ = load("google_calendar_list_events",
                   lambda *a: refused("Request had insufficient authentication scopes."))
    out = await tool(time_min="2026-11-24T00:00:00Z", time_max="2026-11-25T00:00:00Z")
    assert not out["success"]
    assert "403 Request had insufficient authentication scopes." in out["error"]


@pytest.mark.asyncio
async def test_a_crowded_period_is_told_in_less_detail_and_always_fits():
    import json

    def crowded(n, guests=80, words=5000):
        return [{**EVENT, "id": f"e{i}", "description": "x" * words,
                 "start": {"dateTime": f"2026-11-24T{8 + i % 12:02d}:00:00-05:00"},
                 "attendees": [{"email": f"guest{g}@example.com", "responseStatus": "accepted"}
                               for g in range(guests)]} for i in range(n)]

    # a quiet day keeps everything
    tool, _ = load("google_calendar_list_events", lambda *a: {"items": crowded(3)})
    out = await tool(time_min="2026-11-24T00:00:00Z", time_max="2026-11-25T00:00:00Z")
    event = out["data"]["events"][0]
    assert len(event["guests"]) == 20 and event["guest_count"] == 80
    assert len(event["description"]) == 401
    # the sandbox shows `data` twice (docs/tools.md): under 10,000 here is under 20,000 there
    for many in (12, 25, 50):
        tool, _ = load("google_calendar_list_events",
                       lambda *a, many=many: {"items": crowded(many), "nextPageToken": "p2"})
        out = await tool(time_min="2026-11-24T00:00:00Z", time_max="2026-11-25T00:00:00Z",
                         max_results=50)
        data = out["data"]
        assert len(json.dumps(out)) < 10_000, many
        assert all(e["guest_count"] == 80 for e in data["events"])
        if data["count"] < many:
            # what did not fit is reached by time, and the page token is not offered with it
            assert data["continue_from"] == f"2026-11-24T{8 + data['count'] % 12:02d}:00:00-05:00"
            assert "next_page_token" not in data
        else:
            assert data["next_page_token"] == "p2"
    assert data["count"] < 50  # fifty crowded events do not fit, and the answer says so


# ── list_calendars ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_calendars_puts_the_persons_own_first_and_leaves_hidden_ones_out():
    tool, calls = load("google_calendar_list_calendars", lambda *a: {"items": [
        {"id": "hol", "summary": "Holidays", "accessRole": "reader", "selected": True},
        {"id": "x", "summary": "Old", "hidden": True},
        {"id": "owner@example.com", "summary": "owner@example.com", "primary": True,
         "summaryOverride": "Alex", "accessRole": "owner", "timeZone": "America/New_York"},
    ]})
    out = await tool()
    assert calls[0][1] == "users/me/calendarList"
    assert [c["id"] for c in out["data"]["calendars"]] == ["owner@example.com", "hol"]
    assert out["data"]["calendars"][0] == {
        "id": "owner@example.com", "name": "Alex", "primary": True, "access": "owner",
        "time_zone": "America/New_York", "shown": False}


# ── find_free_time ───────────────────────────────────────────────────────────


def busy(*blocks):
    return {"busy": [{"start": a, "end": b} for a, b in blocks]}


@pytest.mark.asyncio
async def test_free_time_is_inside_working_hours_in_the_zone_given_for_everyone_asked():
    def answer(method, path, kwargs):
        assert (method, path) == ("POST", "freeBusy")
        return {"calendars": {
            "primary": busy(("2026-11-24T14:00:00Z", "2026-11-24T15:00:00Z")),   # 09-10 ET
            "sam@example.com": busy(("2026-11-24T15:30:00Z", "2026-11-24T21:00:00Z")),
            "ext@other.com": {"errors": [{"reason": "notFound"}]},
        }}

    tool, calls = load("google_calendar_find_free_time", answer)
    out = await tool(
        time_min="2026-11-24T00:00:00-05:00", time_max="2026-11-26T00:00:00-05:00",
        duration_minutes=30, attendees=["Sam@Example.com", "ext@other.com"],
        time_zone="America/New_York")
    assert out["success"], out
    sent = calls[0][2]["json"]
    assert sent["timeZone"] == "America/New_York"
    assert sent["items"] == [{"id": "primary"}, {"id": "sam@example.com"},
                             {"id": "ext@other.com"}]
    data = out["data"]
    # Tuesday: the one gap both have inside 09:00 to 17:00 Eastern is 10:00 to 10:30
    assert data["slots"][0] == {
        "start": "2026-11-24T10:00:00-05:00", "end": "2026-11-24T10:30:00-05:00",
        "free_until": "2026-11-24T10:30:00-05:00"}
    # 16:00 to 17:00 on Tuesday is free too; Wednesday is free all day
    assert data["slots"][1]["start"] == "2026-11-24T16:00:00-05:00"
    assert data["slots"][2] == {
        "start": "2026-11-25T09:00:00-05:00", "end": "2026-11-25T09:30:00-05:00",
        "free_until": "2026-11-25T17:00:00-05:00"}
    assert data["unknown"] == ["ext@other.com"] and "ext@other.com" in data["note"]
    assert data["checked"] == ["primary", "sam@example.com"]
    assert data["working_hours"] == "09:00 to 17:00, Monday to Friday"


@pytest.mark.asyncio
async def test_free_time_leaves_weekends_out_and_follows_the_zone_it_is_given():
    tool, _ = load("google_calendar_find_free_time",
                   lambda *a: {"calendars": {"primary": busy()}})
    # Saturday 28 and Sunday 29 November 2026
    out = await tool(time_min="2026-11-28T00:00:00+03:00", time_max="2026-11-30T00:00:00+03:00",
                     time_zone="Africa/Nairobi")
    assert out["data"]["slots"] == [] and "No time" in out["data"]["note"]
    out = await tool(time_min="2026-11-28T00:00:00+03:00", time_max="2026-11-30T00:00:00+03:00",
                     time_zone="Africa/Nairobi", weekends=True, day_start="10:00",
                     day_end="12:00", duration_minutes=60)
    assert [s["start"] for s in out["data"]["slots"]] == [
        "2026-11-28T10:00:00+03:00", "2026-11-29T10:00:00+03:00"]
    # the same Monday asked about in two zones: nine o'clock is each zone's own
    for zone, nine in (("America/New_York", "2026-11-30T09:00:00-05:00"),
                       ("Africa/Nairobi", "2026-11-30T09:00:00+03:00")):
        out = await tool(time_min="2026-11-30T00:00:00Z", time_max="2026-12-01T12:00:00Z",
                         time_zone=zone, max_slots=1)
        assert out["data"]["slots"][0]["start"] == nine


@pytest.mark.asyncio
async def test_with_no_zone_given_free_time_asks_google_for_the_calendars_own():
    def answer(method, path, kwargs):
        if method == "GET":
            assert path == "calendars/primary"
            return {"timeZone": "America/New_York"}
        return {"calendars": {"primary": busy()}}

    tool, calls = load("google_calendar_find_free_time", answer)
    out = await tool(time_min="2026-11-24T00:00:00Z", time_max="2026-11-25T00:00:00Z")
    assert out["data"]["time_zone"] == "America/New_York"
    assert [c[0] for c in calls] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_free_time_refuses_what_it_cannot_answer():
    tool, calls = load("google_calendar_find_free_time", lambda *a: {"calendars": {}})
    ok = {"time_min": "2026-11-24T00:00:00Z", "time_max": "2026-11-25T00:00:00Z",
          "time_zone": "America/New_York"}
    for bad, said in (
        ({**ok, "time_min": "tomorrow"}, "UTC offset"),
        ({**ok, "time_max": "2026-11-23T00:00:00Z"}, "after time_min"),
        ({**ok, "time_max": "2027-01-30T00:00:00Z"}, "at most 31 days"),
        ({**ok, "day_start": "9am"}, "HH:MM"),
        ({**ok, "day_start": "18:00"}, "before day_end"),
        ({**ok, "time_zone": "Eastern"}, "not a time zone name"),
    ):
        out = await tool(**bad)
        assert not out["success"] and said in out["error"], out
    assert calls == []
    tool, _ = load("google_calendar_find_free_time", lambda *a: refused("Rate Limit Exceeded"))
    assert "Rate Limit Exceeded" in (await tool(**ok))["error"]


# ── update_event ─────────────────────────────────────────────────────────────


def one(event):
    def answer(method, path, kwargs):
        if method == "GET":
            return event if path.endswith(event["id"]) else refused("Not Found", 404)
        body = kwargs.get("json") or {}
        merged = {**event, **{k: v for k, v in body.items() if k != "conferenceData"}}
        if "conferenceData" in body:
            merged["hangoutLink"] = "https://meet.google.com/new-link"
        return merged
    return answer


@pytest.mark.asyncio
async def test_moving_an_event_keeps_its_length_and_emails_the_guests():
    tool, calls = load("google_calendar_update_event", one(EVENT))
    out = await tool(event_id="e1", title="call with sam", start="2026-11-24T14:00:00-05:00")
    assert out["success"], out
    method, path, kwargs = calls[-1]
    assert (method, path) == ("PATCH", "calendars/primary/events/e1")
    assert kwargs["params"] == {"sendUpdates": "all"}
    assert kwargs["json"] == {
        "start": {"dateTime": "2026-11-24T14:00:00-05:00", "date": None,
                  "timeZone": "America/New_York"},
        "end": {"dateTime": "2026-11-24T14:30:00-05:00", "date": None,
                "timeZone": "America/New_York"},
    }
    assert out["data"]["changed"] == ["end", "start"] and out["data"]["guests_emailed"]


@pytest.mark.asyncio
async def test_guests_are_added_and_removed_and_the_others_stay():
    tool, calls = load("google_calendar_update_event", one(EVENT))
    out = await tool(event_id="e1", title="Call with Sam", add_guests=["Ann@Example.com"],
                     remove_guests=["sam@example.com"], new_title="Call with Ann")
    sent = calls[-1][2]["json"]
    assert sent["summary"] == "Call with Ann"
    assert [g["email"] for g in sent["attendees"]] == ["owner@example.com",
                                                      "ann@example.com"]
    assert sent["attendees"][0]["responseStatus"] == "accepted"  # the entry kept whole
    assert out["data"]["guests"] == [{"email": "ann@example.com", "response": None}]
    refusal = await tool(event_id="e1", title="Call with Sam", remove_guests=["bob@x.com"])
    assert not refusal["success"] and "not a guest" in refusal["error"]
    assert "sam@example.com" in refusal["error"]


@pytest.mark.asyncio
async def test_a_meet_link_is_added_once_and_an_own_event_with_no_guests_emails_nobody():
    alone = {**EVENT, "attendees": [], "hangoutLink": None}
    tool, calls = load("google_calendar_update_event", one(alone))
    out = await tool(event_id="e1", title="Call with Sam", video_call=True)
    kwargs = calls[-1][2]
    assert kwargs["params"] == {"sendUpdates": "none", "conferenceDataVersion": 1}
    request = kwargs["json"]["conferenceData"]["createRequest"]
    assert request["conferenceSolutionKey"] == {"type": "hangoutsMeet"}
    assert out["data"]["meet_link"] == "https://meet.google.com/new-link"
    again, calls2 = load("google_calendar_update_event", one(alone))
    await again(event_id="e1", title="Call with Sam", video_call=True)
    assert calls2[-1][2]["json"]["conferenceData"]["createRequest"] == request  # same request id
    # an event that has a link already is not asked for another
    tool, calls = load("google_calendar_update_event", one(EVENT))
    out = await tool(event_id="e1", title="Call with Sam", video_call=True)
    assert not out["success"] and "nothing to change" in out["error"]


@pytest.mark.asyncio
async def test_update_refuses_the_wrong_event_someone_elses_and_bad_times():
    tool, calls = load("google_calendar_update_event", one(EVENT))
    wrong = await tool(event_id="e1", title="Board prep", location="Room 2")
    assert not wrong["success"] and "'Call with Sam', not 'Board prep'" in wrong["error"]
    assert not (await tool(event_id="e1", title="Call with Sam", start="2pm"))["success"]
    assert not (await tool(event_id="", title="x", location="y"))["success"]
    assert not (await tool(event_id="e1", title="Call with Sam"))["success"]
    assert [c[0] for c in calls].count("PATCH") == 0
    tool, calls = load("google_calendar_update_event", one(THEIRS))
    theirs = await tool(event_id="e2", title="Board prep", location="Room 2")
    assert not theirs["success"] and "lee@example.com's event" in theirs["error"]
    assert "google_calendar_respond_to_event" in theirs["error"]
    assert [c[0] for c in calls] == ["GET"]
    # where the organiser lets guests change it, a guest may
    open_ = {**THEIRS, "guestsCanModify": True}
    tool, calls = load("google_calendar_update_event", one(open_))
    assert (await tool(event_id="e2", title="Board prep", location="Room 2"))["success"]


@pytest.mark.asyncio
async def test_a_whole_series_is_changed_on_the_series_and_never_moved():
    occurrence = {**EVENT, "id": "s1_20261124", "recurringEventId": "s1"}
    tool, calls = load("google_calendar_update_event", one(occurrence))
    out = await tool(event_id="s1_20261124", title="Call with Sam", location="Room 2",
                     whole_series=True)
    assert calls[-1][1] == "calendars/primary/events/s1" and out["data"]["whole_series"]
    moved = await tool(event_id="s1_20261124", title="Call with Sam", whole_series=True,
                       start="2026-11-24T14:00:00-05:00")
    assert not moved["success"] and "one occurrence" in moved["error"]
    # an all-day event moves by date and keeps its number of days
    days = {**EVENT, "id": "d1", "start": {"date": "2026-11-25"}, "end": {"date": "2026-11-27"}}
    tool, calls = load("google_calendar_update_event", one(days))
    await tool(event_id="d1", title="Call with Sam", start="2026-12-01")
    assert calls[-1][2]["json"] == {"start": {"date": "2026-12-01", "dateTime": None},
                                    "end": {"date": "2026-12-03", "dateTime": None}}


def test_an_update_says_what_changes_and_that_guests_are_emailed():
    words = consequence("google_calendar_update_event", {
        "event_id": "e1", "title": "Call with Sam", "start": "2026-11-24T14:00:00-05:00",
        "add_guests": ["ann@example.com"], "video_call": True})
    assert words == (
        'Changes the event "Call with Sam": moves it to 2026-11-24T14:00:00-05:00, same '
        "length; invites ann@example.com; adds a Google Meet link. Guests of the event, and "
        "anyone invited or removed, are emailed the change.")
    series = consequence("google_calendar_update_event", {
        "title": "Standup", "location": "Room 2", "whole_series": True})
    assert series.startswith('Changes every occurrence of "Standup"')


# ── cancel_event ─────────────────────────────────────────────────────────────


def deleting(event, status=204):
    def answer(method, path, kwargs):
        if method == "GET":
            return event
        return (status, "") if status != 204 else (204, "")
    return answer


@pytest.mark.asyncio
async def test_cancelling_emails_the_guests_and_names_them():
    tool, calls = load("google_calendar_delete_event", deleting(EVENT))
    out = await tool(event_id="e1", title="Call with Sam")
    assert out["success"], out
    method, path, kwargs = calls[-1]
    assert (method, path) == ("DELETE", "calendars/primary/events/e1")
    assert kwargs["params"] == {"sendUpdates": "all"}
    assert out["data"]["guests"] == ["sam@example.com"] and not out["data"]["already"]
    assert "carries no message" in out["data"]["note"]


@pytest.mark.asyncio
async def test_one_occurrence_or_the_series_is_decided_by_the_call_and_said():
    occurrence = {**EVENT, "id": "s1_20261124", "recurringEventId": "s1"}
    tool, calls = load("google_calendar_delete_event", deleting(occurrence))
    one_ = await tool(event_id="s1_20261124", title="Call with Sam")
    assert calls[-1][1].endswith("/events/s1_20261124") and not one_["data"]["whole_series"]
    every = await tool(event_id="s1_20261124", title="Call with Sam", whole_series=True)
    assert calls[-1][1].endswith("/events/s1") and every["data"]["whole_series"]
    # the id of the series itself is never taken for one occurrence
    master = {**EVENT, "id": "s1", "recurrence": ["RRULE:FREQ=WEEKLY"]}
    tool, calls = load("google_calendar_delete_event", deleting(master))
    refusal = await tool(event_id="s1", title="Call with Sam")
    assert not refusal["success"] and "whole repeating series" in refusal["error"]
    assert [c[0] for c in calls] == ["GET"]
    assert (await tool(event_id="s1", title="Call with Sam", whole_series=True))["success"]

    words = consequence("google_calendar_delete_event", {"event_id": "x", "title": "Standup"})
    assert words.startswith('Cancels "Standup": this one event (this one occurrence')
    words = consequence("google_calendar_delete_event", {"title": "Standup", "whole_series": True})
    assert words.startswith('Cancels "Standup" and every occurrence of it')
    assert "carries no message" in words


@pytest.mark.asyncio
async def test_cancel_refuses_someone_elses_meeting_and_the_wrong_title():
    tool, calls = load("google_calendar_delete_event", deleting(THEIRS))
    out = await tool(event_id="e2", title="Board prep")
    assert not out["success"] and "lee@example.com's event" in out["error"]
    assert "google_calendar_respond_to_event" in out["error"]
    tool2, calls2 = load("google_calendar_delete_event", deleting(EVENT))
    wrong = await tool2(event_id="e1", title="Board prep")
    assert not wrong["success"] and "nothing was cancelled" in wrong["error"]
    assert [c[0] for c in calls + calls2] == ["GET", "GET"]


@pytest.mark.asyncio
async def test_cancelling_twice_is_cancelled_once():
    tool, calls = load("google_calendar_delete_event",
                       deleting({**EVENT, "status": "cancelled"}))
    out = await tool(event_id="e1", title="Call with Sam")
    assert out["success"] and out["data"]["already"] and [c[0] for c in calls] == ["GET"]
    tool, _ = load("google_calendar_delete_event", deleting(EVENT, status=410))
    assert (await tool(event_id="e1", title="Call with Sam"))["data"]["already"]
    tool, _ = load("google_calendar_delete_event", lambda m, p, k: EVENT if m == "GET"
                   else refused("Forbidden"))
    assert "403 Forbidden" in (await tool(event_id="e1", title="Call with Sam"))["error"]


# ── respond_to_event ─────────────────────────────────────────────────────────


def answering(event):
    def answer(method, path, kwargs):
        if method == "GET":
            return event
        return {**event, **kwargs["json"]}
    return answer


@pytest.mark.asyncio
async def test_an_answer_changes_only_the_persons_own_entry_and_tells_the_organiser():
    tool, calls = load("google_calendar_respond_to_event", answering(THEIRS))
    out = await tool(event_id="e2", title="board prep", response="Declined",
                     comment="Travelling that day.",
                     propose_start="2026-11-25T10:00:00-05:00",
                     propose_end="2026-11-25T10:30:00-05:00")
    assert out["success"], out
    method, path, kwargs = calls[-1]
    assert (method, path) == ("PATCH", "calendars/primary/events/e2")
    assert kwargs["params"] == {"sendUpdates": "all"}
    assert kwargs["json"] == {"attendees": [
        {"email": "lee@example.com", "organizer": True, "responseStatus": "accepted"},
        {"email": "owner@example.com", "self": True, "responseStatus": "declined",
         "comment": "Travelling that day. Could we do 2026-11-25T10:00:00-05:00 to "
                    "2026-11-25T10:30:00-05:00 instead?"},
    ]}
    assert out["data"]["response"] == "declined" and out["data"]["organizer"] == "lee@example.com"
    assert THEIRS["attendees"][1]["responseStatus"] == "needsAction"  # the read is not edited


@pytest.mark.asyncio
async def test_respond_refuses_what_is_not_an_invitation_and_a_bad_answer():
    tool, calls = load("google_calendar_respond_to_event", answering(EVENT))
    alone = {**EVENT, "attendees": []}
    tool2, _ = load("google_calendar_respond_to_event", answering(alone))
    own = await tool2(event_id="e1", title="Call with Sam", response="accepted")
    assert not own["success"] and "the person organises it" in own["error"]
    for bad, said in (
        ({"response": "yes"}, '"accepted", "declined" or "tentative"'),
        ({"response": "declined", "propose_start": "Friday"}, "UTC offset"),
        ({"response": "declined", "propose_end": "2026-11-25T10:30:00-05:00"},
         "needs propose_start"),
        ({"response": "accepted", "title": "Board prep"}, "nothing was answered"),
    ):
        out = await tool(**{"event_id": "e1", "title": "Call with Sam", **bad})
        assert not out["success"] and said in out["error"], out
    assert "PATCH" not in [c[0] for c in calls]


@pytest.mark.asyncio
async def test_an_answer_google_did_not_keep_is_not_reported_as_given():
    def answer(method, path, kwargs):
        return THEIRS  # the PATCH comes back unchanged
    tool, _ = load("google_calendar_respond_to_event", answer)
    out = await tool(event_id="e2", title="Board prep", response="accepted")
    assert not out["success"] and "'needsAction', not 'accepted'" in out["error"]


@pytest.mark.asyncio
async def test_a_whole_series_is_answered_on_the_series():
    occurrence = {**THEIRS, "id": "s2_20261124", "recurringEventId": "s2"}
    series = {**THEIRS, "id": "s2"}

    def answer(method, path, kwargs):
        if method == "GET":
            return occurrence if path.endswith("s2_20261124") else series
        return {**series, **kwargs["json"]}
    tool, calls = load("google_calendar_respond_to_event", answer)
    out = await tool(event_id="s2_20261124", title="Board prep", response="accepted",
                     whole_series=True)
    assert calls[-1][1] == "calendars/primary/events/s2" and out["data"]["whole_series"]


def test_an_answer_says_the_answer_and_the_note_the_organiser_reads():
    words = consequence("google_calendar_respond_to_event", {
        "title": "Board prep", "response": "declined", "comment": "Travelling.",
        "propose_start": "2026-11-25T10:00:00-05:00"})
    assert words == (
        'Declines the invitation "Board prep" in the person\'s name; the organiser is '
        'emailed the answer. The organiser reads this note: "Travelling. Could we do '
        '2026-11-25T10:00:00-05:00 instead?"')
    plain = consequence("google_calendar_respond_to_event", {
        "title": "Board prep", "response": "accepted"})
    assert plain.startswith('Accepts the invitation "Board prep"')
    assert plain.endswith("No note is sent.")


def test_the_helpers_two_atoms_share_are_the_same_in_each():
    """An atom is one file run alone in the sandbox, so shared code is kept in each."""
    import ast

    def helper(path, name):
        tree = ast.parse(path.read_text())
        return next((ast.dump(n) for n in tree.body
                     if isinstance(n, ast.FunctionDef) and n.name == name), None)

    for name in ("_reason", "_same"):
        copies = {helper(p, name) for p in DIR.glob("google_calendar_*.py")} - {None}
        assert len(copies) == 1, name
