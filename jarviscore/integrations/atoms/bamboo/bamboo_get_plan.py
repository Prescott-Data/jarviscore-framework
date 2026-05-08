def bamboo_get_plan(auth_info: dict, cloud_id: str, plan_key: str) -> dict:
    import requests
    _base = f"https://api.atlassian.com/bamboo/{cloud_id}"
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
    p = _get(f"/rest/api/latest/plan/{plan_key}")
    return {
        "key": p["key"],
        "name": p["name"],
        "project_key": p.get("projectKey"),
        "description": p.get("description"),
        "enabled": p.get("enabled", True),
        "is_building": p.get("isBuilding", False),
        "average_build_time_seconds": p.get("averageBuildTimeInSeconds"),
        "href": p.get("link", {}).get("href")
    }
