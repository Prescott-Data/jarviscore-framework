def slack_list_channels(auth_info: dict, exclude_archived: bool = True, limit: int = 200) -> list:
    import requests
    _base = "https://slack.com/api"
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
    channels = []
    cursor = None
    while True:
        params = {"limit": limit, "exclude_archived": "true" if exclude_archived else "false"}
        if cursor:
            params["cursor"] = cursor
        resp = _get("/conversations.list", params=params)
        if not resp.get("ok"):
            raise RuntimeError(resp.get("error", "Slack API error"))
        channels.extend(resp.get("channels", []))
        cursor = resp.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    return channels
