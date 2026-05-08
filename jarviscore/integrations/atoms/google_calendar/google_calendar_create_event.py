def google_calendar_create_event(auth_info: dict, summary: str, start_datetime: str, end_datetime: str, description: str = "", location: str = "", attendees: list = None, calendar_id: str = "primary") -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    payload = {"summary": summary, "description": description, "location": location, "start": {"dateTime": start_datetime, "timeZone": "Africa/Nairobi"}, "end": {"dateTime": end_datetime, "timeZone": "Africa/Nairobi"}}
    if attendees:
        payload["attendees"] = [{"email": e} for e in attendees]
    resp = requests.post(f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events", headers=_h, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return {"success": True, "event_id": data.get("id"), "html_link": data.get("htmlLink"), "summary": summary}
