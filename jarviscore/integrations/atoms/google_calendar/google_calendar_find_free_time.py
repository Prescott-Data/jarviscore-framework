import re
from datetime import datetime, time, timedelta

ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

# Google's free/busy query is a POST that changes nothing: it answers when the named
# calendars are busy, never with what. It is this atom's one POST, and the atom is a read.

_API = "https://www.googleapis.com/calendar/v3"
_FULL = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$"
_CLOCK = r"^([01]?\d|2[0-3]):([0-5]\d)$"
_LONGEST = 31  # days in one question


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


def _moment(value: str) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))


def _free(busy: list, start: datetime, end: datetime) -> list:
    """The gaps in [start, end) that no busy interval covers; `busy` is sorted."""
    gaps, at = [], start
    for b_start, b_end in busy:
        if b_end <= at:
            continue
        if b_start >= end:
            break
        if b_start > at:
            gaps.append((at, b_start))
        at = max(at, b_end)
    if at < end:
        gaps.append((at, end))
    return gaps


async def google_calendar_find_free_time(
    time_min: str,
    time_max: str,
    duration_minutes: int = 30,
    attendees: list = None,  # noqa: RUF013 - the tool schema reads the bare type
    calendar_ids: list = None,  # noqa: RUF013 - the tool schema reads the bare type
    time_zone: str = "",
    day_start: str = "09:00",
    day_end: str = "17:00",
    weekends: bool = False,
    max_slots: int = 8,
) -> dict:
    """Find times when the person and everyone named are free, inside working hours.

    `time_min` and `time_max` bound the search, each a full time with its UTC offset
    (2026-11-24T00:00:00-05:00), at most 31 days apart. `duration_minutes` is how long the
    meeting is. `attendees` are the other people's email addresses. `calendar_ids` are the
    person's calendars that count as busy (default: their own, "primary"; add others
    from google_calendar_list_calendars). `time_zone` is the IANA zone the working hours
    are in (America/New_York): pass the person's; left out, their calendar's own zone is
    used. `day_start` and `day_end` are the working hours as HH:MM in that zone; `weekends`
    false leaves Saturday and Sunday out.

    Returns `slots`, earliest first: each a `start` and `end` of the asked length, with
    `free_until`, the moment that free stretch ends (so a later start in the same stretch
    also works). `unknown` lists people whose calendar Google would not show (outside the
    organisation, or not shared): they were not checked, and a slot may not suit them; say
    so. Nothing is booked. Times are in `time_zone`.
    https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query
    """
    from zoneinfo import ZoneInfo

    for name, value in (("time_min", time_min), ("time_max", time_max)):
        if not re.match(_FULL, str(value or "").strip()):
            return {
                "success": False, "data": None,
                "error": f"{name} must be a full time with its UTC offset, like "
                         f"2026-11-24T00:00:00-05:00; got {value!r}",
            }
    opens = re.match(_CLOCK, str(day_start).strip())
    closes = re.match(_CLOCK, str(day_end).strip())
    if not opens or not closes:
        return {"success": False, "data": None,
                "error": "day_start and day_end are times of day as HH:MM, like 09:00"}
    opens = time(int(opens.group(1)), int(opens.group(2)))
    closes = time(int(closes.group(1)), int(closes.group(2)))
    length = timedelta(minutes=max(5, int(duration_minutes or 30)))
    if opens >= closes:
        return {"success": False, "data": None, "error": "day_start must be before day_end"}
    begin, finish = _moment(time_min), _moment(time_max)
    if finish <= begin:
        return {"success": False, "data": None, "error": "time_max must be after time_min"}
    if finish - begin > timedelta(days=_LONGEST):
        return {"success": False, "data": None,
                "error": f"ask about at most {_LONGEST} days at a time"}

    zone_name = str(time_zone or "").strip()
    if not zone_name:
        own = await nexus_call(  # noqa: F821
            "GET", f"{_API}/calendars/primary", params={"fields": "timeZone"})
        if not own["ok"]:
            return {"success": False, "data": None,
                    "error": f"the calendar's time zone could not be read: {_reason(own)}"}
        zone_name = (own["json"] or {}).get("timeZone") or ""
    try:
        zone = ZoneInfo(zone_name)
    except Exception:  # noqa: BLE001 - an unknown name, or no zone data
        return {"success": False, "data": None,
                "error": f"{zone_name!r} is not a time zone name (Continent/City)"}

    own_calendars = [str(c).strip() for c in (calendar_ids or ["primary"]) if str(c).strip()]
    people = [str(a).strip().lower() for a in (attendees or []) if str(a).strip()]
    asked = list(dict.fromkeys(own_calendars + people))
    resp = await nexus_call(  # noqa: F821
        "POST",
        f"{_API}/freeBusy",
        headers={"Content-Type": "application/json"},
        json={
            "timeMin": begin.isoformat(),
            "timeMax": finish.isoformat(),
            "timeZone": zone_name,
            "items": [{"id": each} for each in asked],
        },
    )
    if not resp["ok"]:
        return {"success": False, "data": None,
                "error": f"free/busy could not be read: {_reason(resp)}"}
    answered = (resp["json"] or {}).get("calendars") or {}
    busy, unknown = [], []
    for each in asked:
        found = answered.get(each) or {}
        if found.get("errors") or each not in answered:
            unknown.append(each)
            continue
        for block in found.get("busy") or []:
            busy.append((_moment(block["start"]), _moment(block["end"])))
    busy.sort()

    limit = max(1, min(int(max_slots or 8), 20))
    slots, day = [], begin.astimezone(zone).date()
    last = finish.astimezone(zone).date()
    while day <= last and len(slots) < limit:
        if weekends or day.weekday() < 5:
            start = max(datetime.combine(day, opens, tzinfo=zone), begin)
            end = min(datetime.combine(day, closes, tzinfo=zone), finish)
            if end - start >= length:
                for gap_start, gap_end in _free(busy, start, end):
                    if gap_end - gap_start < length or len(slots) >= limit:
                        continue
                    opening = gap_start.astimezone(zone)
                    slots.append({
                        "start": opening.isoformat(),
                        "end": (opening + length).isoformat(),
                        "free_until": gap_end.astimezone(zone).isoformat(),
                    })
        day += timedelta(days=1)
    out = {
        "slots": slots,
        "duration_minutes": int(length.total_seconds() // 60),
        "time_zone": zone_name,
        "working_hours": f"{opens.strftime('%H:%M')} to {closes.strftime('%H:%M')}"
                         + ("" if weekends else ", Monday to Friday"),
        "checked": [each for each in asked if each not in unknown],
        "unknown": unknown,
    }
    if unknown:
        out["note"] = ("Google would not show the calendar of: " + ", ".join(unknown)
                       + ". They were not checked; a slot may not suit them.")
    if not slots:
        out["note"] = (out.get("note", "") + " No time in this period is free for everyone "
                       "checked inside those working hours.").strip()
    return {"success": True, "data": out, "error": None}
