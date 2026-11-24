ATOM_POLICY = {
    "effect": "destructive",
    "approval": "required",
    "idempotency_fields": ["event_id", "title", "calendar_id", "whole_series"],
    "consequence": (
        "Cancels one calendar event the person organises; its guests are emailed the "
        "cancellation."
    ),
}

# Deleting whatever id is given cancels an occurrence or a series without saying which, and
# takes someone else's meeting off the person's calendar without telling its organiser (that
# is a decline: google_calendar_respond_to_event). This reads the event first, refuses what
# is not the person's to cancel, and says what it did.

_API = "https://www.googleapis.com/calendar/v3/calendars"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _same(a: str, b: str) -> bool:
    """Whether two titles are the same but for capitals and spacing."""
    return " ".join(str(a or "").lower().split()) == " ".join(str(b or "").lower().split())


def _consequence(params: dict) -> str:
    """What the approval request says this call does, from its arguments alone."""
    title = params.get("title") or "?"
    if params.get("whole_series") is True:
        what = f'Cancels "{title}" and every occurrence of it, if it repeats'
    else:
        what = f'Cancels "{title}": this one event (this one occurrence, if it repeats)'
    return (f"{what}. Its guests are emailed Google's cancellation, which carries no "
            "message. It cannot be undone from here.")


async def google_calendar_delete_event(
    event_id: str,
    title: str,
    whole_series: bool = False,
    calendar_id: str = "primary",
) -> dict:
    """Cancel an event the person organises. Its guests are emailed the cancellation.

    `event_id` is the event's id from google_calendar_list_events and `title` its title as
    listed there: the call is refused when the two do not belong together, so the approval
    request names the event that is cancelled. For a repeating event the id is one
    occurrence's: `whole_series` false cancels that occurrence only, true cancels every
    occurrence.

    Google's cancellation email carries no message. When the guests should be told why,
    that is a separate email to the `guests` this returns. An event organised by someone
    else is not cancelled here (it would vanish from the person's calendar and tell
    nobody): decline it with google_calendar_respond_to_event.

    Returns `cancelled`, `summary`, `start`, `whole_series`, `guests` (who was emailed)
    and `already` true when it had been cancelled before this call.
    https://developers.google.com/workspace/calendar/api/v3/reference/events/delete
    """
    event_id, calendar = str(event_id or "").strip(), str(calendar_id or "primary").strip()
    if not event_id or not str(title or "").strip():
        return {"success": False, "data": None,
                "error": "event_id and the event's title as listed are both needed"}
    got = await nexus_call("GET", f"{_API}/{calendar}/events/{event_id}")  # noqa: F821
    if not got["ok"]:
        return {"success": False, "data": None,
                "error": f"the event could not be read: {_reason(got)}"}
    event = got["json"] or {}
    if not _same(event.get("summary") or "(no title)", title):
        return {"success": False, "data": None,
                "error": f"event {event_id} is titled {event.get('summary')!r}, not {title!r}; "
                         "nothing was cancelled. Pass the id and title of the same event."}
    start = event.get("start") or {}
    guests = [g.get("email") for g in event.get("attendees") or [] if not g.get("self")]
    series = whole_series is True and bool(event.get("recurringEventId"))
    out = {
        "cancelled": True,
        "summary": event.get("summary"),
        "start": start.get("dateTime") or start.get("date"),
        "whole_series": series or (whole_series is True and bool(event.get("recurrence"))),
        "guests": guests,
        "already": False,
    }
    if event.get("status") == "cancelled":
        return {"success": True, "data": {**out, "already": True}, "error": None}
    organizer = event.get("organizer") or {}
    if not organizer.get("self"):
        return {"success": False, "data": None,
                "error": f"this is {organizer.get('email') or 'someone else'}'s event, not the "
                         "person's to cancel. Decline it with "
                         "google_calendar_respond_to_event; nothing was changed."}
    if event.get("recurrence") and whole_series is not True:
        return {"success": False, "data": None,
                "error": "that id is the whole repeating series, not one occurrence. Pass "
                         "the id of the occurrence to cancel, or whole_series true."}
    target = event["recurringEventId"] if series else event_id
    gone = await nexus_call(  # noqa: F821
        "DELETE", f"{_API}/{calendar}/events/{target}", params={"sendUpdates": "all"})
    if gone["status_code"] == 410:  # Google: already deleted
        return {"success": True, "data": {**out, "already": True}, "error": None}
    if not gone["ok"] and gone["status_code"] != 204:
        return {"success": False, "data": None,
                "error": f"the event was not cancelled: {_reason(gone)}"}
    if guests:
        out["note"] = ("The guests were emailed Google's cancellation, which carries no "
                       "message. To say why, email them.")
    return {"success": True, "data": out, "error": None}
