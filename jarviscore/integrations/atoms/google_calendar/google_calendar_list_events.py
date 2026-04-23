def google_calendar_list_events(auth_info: dict, calendar_id: str = "primary", time_min: str = None, time_max: str = None, max_results: int = 20) -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    params = {"maxResults": max_results, "singleEvents": "true", "orderBy": "startTime"}
    if time_min: params["timeMin"] = time_min
    if time_max: params["timeMax"] = time_max
    resp = requests.get(f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events", headers=_h, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    events = [{"id": e["id"], "summary": e.get("summary"), "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date")), "end": e.get("end", {}).get("dateTime", e.get("end", {}).get("date")), "location": e.get("location"), "description": e.get("description")} for e in data.get("items", [])]
    return {"success": True, "events": events, "count": len(events)}
