def oracle_cx_list_activities(auth_info: dict, instance_url: str, limit: int = 25, offset: int = 0) -> list:
    import requests
    _base = f"{instance_url.rstrip('/')}/crmRestApi/resources/latest"
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
    resp = _get("/activities", params={"limit": limit, "offset": offset})
    return [
        {
            "id": a.get("ActivityId"),
            "subject": a.get("Subject"),
            "type": a.get("ActivityTypeCode"),
            "status": a.get("ActivityStatusCode"),
            "priority": a.get("ActivityPriorityCode"),
            "due_date": a.get("ActualEndDate"),
            "owner": a.get("OwnerName"),
            "created_at": a.get("CreationDate")
        }
        for a in resp.get("items", [])
    ]
