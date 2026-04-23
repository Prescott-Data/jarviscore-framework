def google_calendar_delete_event(auth_info: dict, event_id: str, calendar_id: str = "primary") -> dict:
    import requests
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}"}
    resp = requests.delete(f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}", headers=_h, timeout=30)
    if resp.status_code == 204:
        return {"success": True, "event_id": event_id, "deleted": True}
    resp.raise_for_status()
    return {"success": True, "event_id": event_id, "deleted": True}
