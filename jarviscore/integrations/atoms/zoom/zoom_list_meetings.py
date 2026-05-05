def zoom_list_meetings(auth_info: dict, user_id: str = "me", meeting_type: str = "scheduled", page_size: int = 30) -> list:
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
    List meetings for a Zoom user.

    Args:
        auth_info: Dict with access_token for the tool OAuth
        user_id: Zoom user ID or email. Use "me" for the authenticated user (default)
        meeting_type: Type of meetings — "scheduled", "live", "upcoming", "upcoming_meetings",
                      "previous_meetings" (default: "scheduled")
        page_size: Number of records per page, max 300 (default: 30)

    Returns:
        list of meeting objects (id, topic, start_time, duration, join_url, etc.)
    """
    class ZoomCapabilities(NexusCapabilities):
        pass

    meetings = []
    next_page_token = ""

    while True:
        params = {"type": meeting_type, "page_size": page_size}
        if next_page_token:
            params["next_page_token"] = next_page_token

        response = _get(f"/users/{user_id}/meetings", params=params)
        meetings.extend(response.get("meetings", []))

        next_page_token = response.get("next_page_token", "")
        if not next_page_token:
            break

    return meetings
