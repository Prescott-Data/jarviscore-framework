def bamboo_list_plans(auth_info: dict, cloud_id: str, project_key: str = None, max_results: int = 25) -> list:
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
    params = {"max-result": max_results, "expand": "plans.plan"}
    if project_key:
        resp = _get(f"/rest/api/latest/project/{project_key}", params=params)
        plans = resp.get("plans", {}).get("plan", [])
    else:
        resp = _get("/rest/api/latest/plan", params=params)
        plans = resp.get("plans", {}).get("plan", [])
    return [
        {
            "key": p["key"],
            "name": p["name"],
            "project_key": p.get("projectKey"),
            "enabled": p.get("enabled", True),
            "href": p.get("link", {}).get("href")
        }
        for p in plans
    ]
