import re

ATOM_POLICY = {
    "effect": "notify",
    "approval": "required",
    "idempotency_fields": [
        "event_id", "title", "response", "comment", "propose_start", "propose_end",
        "whole_series", "calendar_id",
    ],
    "consequence": (
        "Answers one calendar invitation in the person's name; the organiser is told."
    ),
}

# The answer is the person's own entry among the event's guests; Google tells the
# organiser when asked to (sendUpdates).

_API = "https://www.googleapis.com/calendar/v3/calendars"
_FULL = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$"
_ANSWERS = {"accepted": "Accepts", "declined": "Declines", "tentative": "Answers maybe to"}


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _same(a: str, b: str) -> bool:
    """Whether two titles are the same but for capitals and spacing."""
    return " ".join(str(a or "").lower().split()) == " ".join(str(b or "").lower().split())


def _note(params: dict) -> str:
    """The comment the organiser reads: the person's words, then the time proposed."""
    comment = str(params.get("comment") or "").strip()
    start = str(params.get("propose_start") or "").strip()
    end = str(params.get("propose_end") or "").strip()
    if start:
        proposal = f"Could we do {start}" + (f" to {end}" if end else "") + " instead?"
        comment = f"{comment} {proposal}".strip()
    return comment


def _consequence(params: dict) -> str:
    """What the approval request says this call does, from its arguments alone."""
    verb = _ANSWERS.get(str(params.get("response") or "").strip().lower(), "Answers")
    which = ", every occurrence" if params.get("whole_series") is True else ""
    note = _note(params)
    said = f' The organiser reads this note: "{note}"' if note else " No note is sent."
    return (f'{verb} the invitation "{params.get("title") or "?"}"{which} in the '
            f"person's name; the organiser is emailed the answer.{said}")


async def google_calendar_respond_to_event(
    event_id: str,
    title: str,
    response: str,
    comment: str = "",
    propose_start: str = "",
    propose_end: str = "",
    whole_series: bool = False,
    calendar_id: str = "primary",
) -> dict:
    """Answer an invitation the person received: accept, decline or maybe, with an
    optional note, and optionally another time proposed.

    `event_id` is the event's id from google_calendar_list_events and `title` its title as
    listed there (the call is refused when they do not belong together). `response` is
    "accepted", "declined" or "tentative". `comment` is a short note the organiser reads
    with the answer. To propose another time, pass `propose_start` (and `propose_end`) as
    full times with their UTC offset: Google's API has no proposal of its own, so the
    proposed time is written into the note ("Could we do ... instead?") and the answer is
    usually "declined" or "tentative". `whole_series` true answers every occurrence of a
    repeating event.

    The organiser is emailed the answer. Returns `response` as Google now holds it,
    `comment` as sent, the event's summary, start, organizer and html_link. An event the
    person organises has no invitation to answer: change it with
    google_calendar_update_event or cancel it with google_calendar_delete_event.
    https://developers.google.com/workspace/calendar/api/v3/reference/events/patch
    """
    event_id, calendar = str(event_id or "").strip(), str(calendar_id or "primary").strip()
    answer = str(response or "").strip().lower()
    if not event_id or not str(title or "").strip():
        return {"success": False, "data": None,
                "error": "event_id and the event's title as listed are both needed"}
    if answer not in _ANSWERS:
        return {"success": False, "data": None,
                "error": 'response is "accepted", "declined" or "tentative"'}
    for name, value in (("propose_start", propose_start), ("propose_end", propose_end)):
        if value and not re.match(_FULL, str(value).strip()):
            return {"success": False, "data": None,
                    "error": f"{name} must be a full time with its UTC offset, like "
                             f"2026-11-24T14:00:00-05:00; got {value!r}"}
    if propose_end and not propose_start:
        return {"success": False, "data": None, "error": "propose_end needs propose_start"}
    got = await nexus_call("GET", f"{_API}/{calendar}/events/{event_id}")  # noqa: F821
    if not got["ok"]:
        return {"success": False, "data": None,
                "error": f"the event could not be read: {_reason(got)}"}
    event = got["json"] or {}
    if event.get("status") == "cancelled":
        return {"success": False, "data": None, "error": "that event has been cancelled"}
    if not _same(event.get("summary") or "(no title)", title):
        return {"success": False, "data": None,
                "error": f"event {event_id} is titled {event.get('summary')!r}, not {title!r}; "
                         "nothing was answered. Pass the id and title of the same event."}
    target = event_id
    if whole_series is True and event.get("recurringEventId"):
        target = event["recurringEventId"]
        got = await nexus_call("GET", f"{_API}/{calendar}/events/{target}")  # noqa: F821
        if not got["ok"]:
            return {"success": False, "data": None,
                    "error": f"the series could not be read: {_reason(got)}"}
        event = got["json"] or {}
    guests = [dict(g) for g in event.get("attendees") or []]
    mine = next((g for g in guests if g.get("self")), None)
    if mine is None:
        whose = "the person organises it" if (event.get("organizer") or {}).get("self") \
            else "the person is not among its guests"
        return {"success": False, "data": None,
                "error": f"there is no invitation to answer on this event: {whose}"}
    note = _note({"comment": comment, "propose_start": propose_start,
                  "propose_end": propose_end})
    mine["responseStatus"] = answer
    if note:
        mine["comment"] = note
    done = await nexus_call(  # noqa: F821
        "PATCH",
        f"{_API}/{calendar}/events/{target}",
        headers={"Content-Type": "application/json"},
        params={"sendUpdates": "all"},
        json={"attendees": guests},
    )
    if not done["ok"]:
        return {"success": False, "data": None,
                "error": f"the invitation was not answered: {_reason(done)}"}
    now = done["json"] or {}
    held = next((g for g in now.get("attendees") or [] if g.get("self")), {})
    if held.get("responseStatus") != answer:
        return {"success": False, "data": None,
                "error": f"Google holds the answer as {held.get('responseStatus')!r}, not "
                         f"{answer!r}; check the event before saying it was answered"}
    start = now.get("start") or {}
    return {
        "success": True,
        "data": {
            "event_id": now.get("id") or target,
            "summary": now.get("summary"),
            "start": start.get("dateTime") or start.get("date"),
            "organizer": (now.get("organizer") or {}).get("email"),
            "response": held.get("responseStatus"),
            "comment": held.get("comment") or "",
            "whole_series": target != event_id,
            "html_link": now.get("htmlLink"),
        },
        "error": None,
    }
