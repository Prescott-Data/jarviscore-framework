def zoom_update_meeting(auth_info: dict, meeting_id: str, topic: str = None, start_time: str = None, duration: int = None, agenda: str = None, timezone: str = None) -> dict:
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
    Update a Zoom meeting.

    Args:
        auth_info: Dict with access_token for the tool OAuth
        meeting_id: The meeting ID to update
        topic: New meeting topic (optional)
        start_time: New start time in ISO 8601 format (optional)
        duration: New duration in minutes (optional)
        agenda: New agenda/description (optional)
        timezone: New timezone (optional)

    Returns:
        dict with {"updated": True} on success
    """
    class ZoomCapabilities(NexusCapabilities):
        pass

    payload = {}
    if topic is not None:
        payload["topic"] = topic
    if start_time is not None:
        payload["start_time"] = start_time
    if duration is not None:
        payload["duration"] = duration
    if agenda is not None:
        payload["agenda"] = agenda
    if timezone is not None:
        payload["timezone"] = timezone

    _patch(f"/meetings/{meeting_id}", data=payload)
    return {"updated": True, "meeting_id": meeting_id}
