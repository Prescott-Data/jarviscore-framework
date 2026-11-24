ATOM_POLICY = {
    "effect": "read",
    "approval": "never",
}

_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList"


def _reason(resp: dict) -> str:
    """Google's own reason for a refusal, short."""
    error = ((resp.get("json") or {}).get("error") or {}) if isinstance(resp.get("json"), dict) \
        else {}
    said = error.get("message") if isinstance(error, dict) else None
    return f"{resp.get('status_code')} {said or str(resp.get('body') or '')[:300]}".strip()


async def google_calendar_list_calendars() -> dict:
    """List the calendars the person has: their own, ones shared with them, team and
    holiday calendars. Each has `id` (what every other calendar tool takes as
    `calendar_id`), `name`, `primary` (true for their own), `access` (owner, writer,
    reader or freeBusyReader: only owner and writer can be written to), `time_zone` and
    `shown` (whether it is ticked in their calendar view). Their own comes first.
    https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list
    """
    calendars, token = [], None
    for _ in range(5):  # 250 a page: more calendars than anybody has
        params = {"maxResults": 250, "fields": (
            "nextPageToken,items(id,summary,summaryOverride,primary,accessRole,timeZone,"
            "selected,hidden)")}
        if token:
            params["pageToken"] = token
        resp = await nexus_call("GET", _URL, params=params)  # noqa: F821
        if not resp["ok"]:
            return {"success": False, "data": None,
                    "error": f"the calendars could not be listed: {_reason(resp)}"}
        data = resp["json"] or {}
        for item in data.get("items") or []:
            if item.get("hidden"):
                continue
            calendars.append({
                "id": item.get("id"),
                "name": item.get("summaryOverride") or item.get("summary"),
                "primary": bool(item.get("primary")),
                "access": item.get("accessRole"),
                "time_zone": item.get("timeZone"),
                "shown": bool(item.get("selected")),
            })
        token = data.get("nextPageToken")
        if not token:
            break
    calendars.sort(key=lambda c: (not c["primary"], str(c["name"] or "").lower()))
    return {"success": True, "data": {"calendars": calendars, "count": len(calendars)},
            "error": None}
