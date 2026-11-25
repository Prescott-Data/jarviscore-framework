import hashlib
import re
from datetime import datetime

ATOM_POLICY = {
    "effect": "write",
    "approval": "required",
    "idempotency_fields": [
        "event_id", "title", "calendar_id", "new_title", "start", "end", "description",
        "location", "add_guests", "remove_guests", "video_call", "whole_series",
    ],
    "consequence": (
        "Changes one calendar event as listed. If the event has guests, each is emailed "
        "the change."
    ),
}

# This reads the event, changes only what was asked, and tells Google to email the guests
# (sendUpdates), which it does not do unless asked.

_API = "https://www.googleapis.com/calendar/v3/calendars"
_FULL = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$"
_DATE = r"^\d{4}-\d{2}-\d{2}$"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _same(a: str, b: str) -> bool:
    """Whether two titles are the same but for capitals and spacing."""
    return " ".join(str(a or "").lower().split()) == " ".join(str(b or "").lower().split())


def _people(value) -> list:
    return list(dict.fromkeys(str(v).strip().lower() for v in (value or []) if str(v).strip()))


def _consequence(params: dict) -> str:
    """What the approval request says this call does, from its arguments alone."""
    said = []
    if params.get("new_title"):
        said.append(f'renames it "{params["new_title"]}"')
    if params.get("start"):
        said.append(f'moves it to {params["start"]}'
                    + (f' until {params["end"]}' if params.get("end") else ", same length"))
    elif params.get("end"):
        said.append(f'ends it at {params["end"]}')
    if params.get("location"):
        said.append(f'sets the place to "{params["location"]}"')
    if params.get("description"):
        said.append("replaces its description")
    adding, removing = _people(params.get("add_guests")), _people(params.get("remove_guests"))
    if adding:
        said.append("invites " + ", ".join(adding))
    if removing:
        said.append("removes " + ", ".join(removing))
    if params.get("video_call") is True:
        said.append("adds a Google Meet link")
    which = "every occurrence of" if params.get("whole_series") is True else "the event"
    what = "; ".join(said) or "changes nothing"
    return (f'Changes {which} "{params.get("title") or "?"}": {what}. Guests of the event, '
            "and anyone invited or removed, are emailed the change.")


async def google_calendar_update_event(
    event_id: str,
    title: str,
    new_title: str = "",
    start: str = "",
    end: str = "",
    description: str = "",
    location: str = "",
    add_guests: list = None,  # noqa: RUF013 - the tool schema reads the bare type
    remove_guests: list = None,  # noqa: RUF013 - the tool schema reads the bare type
    video_call: bool = False,
    whole_series: bool = False,
    calendar_id: str = "primary",
) -> dict:
    """Change one existing calendar event: move it, rename it, change its place or
    description, invite or remove guests, add a Google Meet link. Only what you pass
    changes; everything left out stays as it is.

    `event_id` is the event's id from google_calendar_list_events, and `title` is its
    title as listed there: the call is refused when the two do not belong together, so
    the approval request names the event that is changed. `new_title` renames it. To move it
    pass `start` as a full time with its UTC offset (2026-11-24T14:00:00-05:00); `end`
    left out keeps the event's length. An all-day event takes dates (2026-11-24; `end` is
    the day after the last day). `add_guests` and `remove_guests` are email addresses; the
    other guests stay. `video_call` true adds a Google Meet link when the event has none.
    `whole_series` true changes every occurrence of a repeating event (not its time: move
    one occurrence at a time).

    Guests are emailed the change. Returns the event as it is afterwards: summary, start,
    end, guests with their responses, meet_link, html_link, and `changed`, the fields
    that were sent. An event organised by someone else can be changed only where they let
    guests do so; otherwise the call is refused and says whose event it is.
    https://developers.google.com/workspace/calendar/api/v3/reference/events/patch
    """
    event_id, calendar = str(event_id or "").strip(), str(calendar_id or "primary").strip()
    if not event_id or not str(title or "").strip():
        return {"success": False, "data": None,
                "error": "event_id and the event's title as listed are both needed"}
    for name, value in (("start", start), ("end", end)):
        text = str(value or "").strip()
        if text and not (re.match(_FULL, text) or re.match(_DATE, text)):
            return {"success": False, "data": None,
                    "error": f"{name} must be a full time with its UTC offset "
                             f"(2026-11-24T14:00:00-05:00), or a date for an all-day event; "
                             f"got {value!r}"}
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
                         "nothing was changed. Pass the id and title of the same event."}
    organizer = event.get("organizer") or {}
    if not organizer.get("self") and not event.get("guestsCanModify"):
        return {"success": False, "data": None,
                "error": f"this is {organizer.get('email') or 'someone else'}'s event and "
                         "guests may not change it. To ask for another time, answer the "
                         "invitation with google_calendar_respond_to_event."}
    target = event_id
    if whole_series is True and event.get("recurringEventId"):
        if start or end:
            return {"success": False, "data": None,
                    "error": "the time of a whole series is not changed here: move one "
                             "occurrence (whole_series false)"}
        target = event["recurringEventId"]

    body, start, end = {}, str(start or "").strip(), str(end or "").strip()
    if new_title and new_title.strip():
        body["summary"] = new_title.strip()
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if start or end:
        old_start, old_end = event.get("start") or {}, event.get("end") or {}
        dated = bool(re.match(_DATE, start or end))
        if start and end and bool(re.match(_DATE, start)) != bool(re.match(_DATE, end)):
            return {"success": False, "data": None,
                    "error": "start and end must both be times or both be dates"}
        key = "date" if dated else "dateTime"
        if start and not end:
            # the same length as before, worked out here, not by the caller
            if key not in old_start or key not in old_end:
                return {"success": False, "data": None,
                        "error": "pass end as well: the event changes between all-day and "
                                 "timed, so its length cannot be kept"}
            read = datetime.fromisoformat
            length = (read(old_end[key].replace("Z", "+00:00"))
                      - read(old_start[key].replace("Z", "+00:00")))
            moved = read(start.replace("Z", "+00:00")) + length
            end = moved.date().isoformat() if dated else moved.isoformat()
        for name, value, old in (("start", start, old_start), ("end", end, old_end)):
            if not value:
                continue
            body[name] = {key: value, "date" if key == "dateTime" else "dateTime": None}
            if key == "dateTime" and old.get("timeZone"):
                body[name]["timeZone"] = old["timeZone"]
    guests = list(event.get("attendees") or [])
    adding, removing = _people(add_guests), _people(remove_guests)
    if adding or removing:
        have = {str(g.get("email") or "").lower() for g in guests}
        missing = [r for r in removing if r not in have]
        if missing:
            return {"success": False, "data": None,
                    "error": f"not a guest of this event: {', '.join(missing)}. Guests: "
                             + (", ".join(sorted(have)) or "none")}
        guests = [g for g in guests if str(g.get("email") or "").lower() not in removing]
        guests += [{"email": a} for a in adding if a not in have]
        body["attendees"] = guests
    params = {"sendUpdates": "all" if (guests or event.get("attendees")) else "none"}
    if video_call is True and not event.get("hangoutLink"):
        seed = f"{calendar}|{target}|meet"
        body["conferenceData"] = {"createRequest": {
            "requestId": hashlib.sha1(seed.encode()).hexdigest()[:32],
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }}
        params["conferenceDataVersion"] = 1
    if not body:
        return {"success": False, "data": None,
                "error": "nothing to change: pass what should be different"}
    done = await nexus_call(  # noqa: F821
        "PATCH",
        f"{_API}/{calendar}/events/{target}",
        headers={"Content-Type": "application/json"},
        params=params,
        json=body,
    )
    if not done["ok"]:
        return {"success": False, "data": None,
                "error": f"the event was not changed: {_reason(done)}"}
    now = done["json"] or {}
    entries = (now.get("conferenceData") or {}).get("entryPoints") or []
    after = now.get("attendees") or []
    out = {
        "event_id": now.get("id") or target,
        "summary": now.get("summary"),
        "start": (now.get("start") or {}).get("dateTime") or (now.get("start") or {}).get("date"),
        "end": (now.get("end") or {}).get("dateTime") or (now.get("end") or {}).get("date"),
        "guests": [{"email": g.get("email"), "response": g.get("responseStatus")}
                   for g in after if not g.get("self")],
        "meet_link": now.get("hangoutLink") or next(
            (p.get("uri") for p in entries if p.get("entryPointType") == "video"), None),
        "html_link": now.get("htmlLink"),
        "changed": sorted(body),
        "guests_emailed": params["sendUpdates"] == "all",
        "whole_series": target != event_id,
    }
    if video_call is True and not out["meet_link"]:
        out["note"] = ("Google returned no Meet link yet; open the event to check before "
                       "telling anyone it has one.")
    return {"success": True, "data": out, "error": None}
