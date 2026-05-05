def zoom_create_meeting(auth_info: dict, topic: str, start_time: str, duration: int, user_id: str = "me", agenda: str = "", timezone: str = "UTC", meeting_type: int = 2) -> dict:
    import requests
    _base = "https://api.zoom.us/v2"
    _h = {"Authorization": f"Bearer {auth_info.get('access_token', '')}", "Content-Type": "application/json"}
    def _get(p, params=None, headers=None):
        _r = requests.get(f"{_base}{p}", headers={**_h, **(headers or {})}, params=params or {}, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _post(p, data=None, headers=None):
        _r = requests.post(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _put(p, data=None, headers=None):
        _r = requests.put(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json()
    def _patch(p, data=None, headers=None):
        _r = requests.patch(f"{_base}{p}", headers={**_h, **(headers or {})}, json=data, timeout=30)
        _r.raise_for_status()
        return _r.json() if _r.content else {}
    def _delete(p, headers=None):
        _r = requests.delete(f"{_base}{p}", headers={**_h, **(headers or {})}, timeout=30)
        _r.raise_for_status()
        return _r.json() if _r.content else {}
    """
    Create a Zoom meeting.

    Args:
        auth_info: Dict with access_token for the tool OAuth
        topic: Meeting topic/title
        start_time: Meeting start time in ISO 8601 format (e.g. "2026-04-01T10:00:00")
        duration: Meeting duration in minutes
        user_id: Zoom user ID or email to schedule for. Use "me" for authenticated user (default)
        agenda: Meeting description/agenda (default: "")
        timezone: Timezone for the meeting (default: "UTC")
        meeting_type: 1=instant, 2=scheduled, 3=recurring no fixed time, 8=recurring fixed time (default: 2)

    Returns:
        dict with created meeting details (id, join_url, start_url, topic, etc.)
    """
    class ZoomCapabilities(NexusCapabilities):
        pass

    payload = {
        "topic": topic,
        "type": meeting_type,
        "start_time": start_time,
        "duration": duration,
        "timezone": timezone,
        "agenda": agenda,
    }

    return _post(f"/users/{user_id}/meetings", data=payload)
