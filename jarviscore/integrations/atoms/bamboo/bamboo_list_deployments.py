def bamboo_list_deployments(auth_info: dict, cloud_id: str) -> list:
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
    resp = _get("/rest/api/latest/deploy/project/all")
    return [
        {
            "id": d.get("id"),
            "name": d.get("name"),
            "plan_key": d.get("planKey", {}).get("key"),
            "description": d.get("description"),
            "environments": [
                {"id": e.get("id"), "name": e.get("name"), "state": e.get("deploymentState")}
                for e in d.get("environments", [])
            ]
        }
        for d in (resp if isinstance(resp, list) else [])
    ]
