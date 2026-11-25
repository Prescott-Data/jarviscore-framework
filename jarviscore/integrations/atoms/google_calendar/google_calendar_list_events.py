import json
import re

ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

# The range is required: with none Google answers with the calendar's oldest events. The
# read pages, searches, and returns what the next step needs (the Meet link, whether an
# event repeats, the person's own answer).

_API = "https://www.googleapis.com/calendar/v3/calendars"
_FULL = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$"
_FIELDS = (
    "nextPageToken,timeZone,items(id,status,summary,description,location,start,end,"
    "recurringEventId,eventType,hangoutLink,conferenceData/entryPoints,htmlLink,"
    "organizer(email,displayName,self),"
    "attendees(email,displayName,responseStatus,self,optional,organizer,comment))"
)
# The answer is sized to be read whole by a model. A crowded week is told in less detail
# before it is told in part: (description characters, guests listed) per event.
_ROOM = 9000
_DETAIL = ((400, 20), (120, 8), (0, 3), (0, 0))


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _event(e: dict, words: int = 400, listed: int = 20) -> dict:
    start, end = e.get("start") or {}, e.get("end") or {}
    guests = e.get("attendees") or []
    mine = next((g for g in guests if g.get("self")), None)
    organizer = e.get("organizer") or {}
    entries = (e.get("conferenceData") or {}).get("entryPoints") or []
    meet = e.get("hangoutLink") or next(
        (p.get("uri") for p in entries if p.get("entryPointType") == "video"), None)
    out = {
        "id": e.get("id"),
        "summary": e.get("summary") or "(no title)",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "status": e.get("status"),
        "event_type": e.get("eventType") or "default",
        "repeats": bool(e.get("recurringEventId")),
        "organizer": organizer.get("email"),
        "organized_by_me": bool(organizer.get("self")),
        # the person's own answer; "organizer" when it is theirs and has no guest entry
        "my_response": (mine or {}).get("responseStatus")
        or ("organizer" if organizer.get("self") else None),
        "guest_count": len([g for g in guests if not g.get("self")]),
        "guests": [
            {
                "email": g.get("email"),
                "name": g.get("displayName"),
                "response": g.get("responseStatus"),
                **({"optional": True} if g.get("optional") else {}),
                **({"comment": g["comment"][:200]} if g.get("comment") else {}),
            }
            for g in guests if not g.get("self")
        ][:listed],
        "meet_link": meet,
        "html_link": e.get("htmlLink"),
    }
    if e.get("recurringEventId"):
        out["series_id"] = e["recurringEventId"]
    if e.get("location"):
        out["location"] = e["location"]
    if e.get("description") and words:
        text = e["description"]
        out["description"] = text[:words] + ("…" if len(text) > words else "")
    return {k: v for k, v in out.items() if v is not None}


async def google_calendar_list_events(
    time_min: str,
    time_max: str,
    query: str = "",
    calendar_id: str = "primary",
    max_results: int = 25,
    page_token: str = "",
) -> dict:
    """List the events of one calendar between two moments, earliest first.

    `time_min` and `time_max` are required, each a full time with its UTC offset
    (2026-11-24T00:00:00-05:00): a day is its midnight to the next midnight. `query` keeps
    only events whose title, description, location or guests contain those words (a
    person's name, "board"). `calendar_id` is "primary" for the person's own; another
    calendar's id comes from google_calendar_list_calendars. `max_results` is 1 to 50; when
    the answer has `next_page_token`, there are more: call again with it as `page_token`.

    A repeating event comes back as its single occurrences, each with `repeats` true and
    the `series_id` they share. Each event has: id, summary, start, end (a date alone when
    `all_day`), status, event_type (default, outOfOffice, focusTime, workingLocation,
    birthday), organizer, organized_by_me, my_response (accepted, declined, tentative,
    needsAction, or organizer), guests with each one's response, guest_count, meet_link
    (the video link, when the event has one), location, description (its first 400
    characters), html_link. A field an event does not have is left out. A period with
    many crowded events is told with shorter descriptions and fewer guests listed
    (`guest_count` is always whole); when even that is too much, the first events come
    back with `continue_from`, the time to pass as `time_min` for the rest.
    https://developers.google.com/workspace/calendar/api/v3/reference/events/list
    """
    time_min, time_max = str(time_min or "").strip(), str(time_max or "").strip()
    for name, value in (("time_min", time_min), ("time_max", time_max)):
        if not re.match(_FULL, value):
            return {
                "success": False, "data": None,
                "error": f"{name} must be a full time with its UTC offset, like "
                         f"2026-11-24T00:00:00-05:00; got {value!r}",
            }
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": max(1, min(int(max_results or 25), 50)),
        "fields": _FIELDS,
    }
    if query and query.strip():
        params["q"] = query.strip()
    if page_token:
        params["pageToken"] = page_token
    calendar = str(calendar_id or "primary").strip()
    resp = await nexus_call("GET", f"{_API}/{calendar}/events", params=params)  # noqa: F821
    if not resp["ok"]:
        return {"success": False, "data": None,
                "error": f"the calendar could not be read: {_reason(resp)}"}
    data = resp["json"] or {}
    items = [e for e in data.get("items") or [] if e.get("status") != "cancelled"]
    for words, listed in _DETAIL:
        events = [_event(e, words, listed) for e in items]
        if len(json.dumps(events)) <= _ROOM:
            break
    out = {"calendar_id": calendar, "calendar_time_zone": data.get("timeZone")}
    kept = list(events)
    while len(kept) > 1 and len(json.dumps(kept)) > _ROOM:
        kept.pop()
    if len(kept) < len(events):
        out["continue_from"] = events[len(kept)]["start"]
        out["note"] = (f"{len(events) - len(kept)} more event(s) were read and did not fit: "
                       "call again with time_min set to continue_from.")
    out = {"events": kept, "count": len(kept), **out}
    if data.get("nextPageToken") and "continue_from" not in out:
        out["next_page_token"] = data["nextPageToken"]
        out["note"] = "There are more events in this period: call again with page_token."
    return {"success": True, "data": out, "error": None}
