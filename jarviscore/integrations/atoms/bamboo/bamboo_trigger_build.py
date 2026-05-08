def bamboo_trigger_build(auth_info: dict, cloud_id: str, plan_key: str, custom_revision: str = None) -> dict:
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
    params = {}
    if custom_revision:
        params["customRevision"] = custom_revision
    resp = _post(f"/rest/api/latest/queue/{plan_key}", data=params or None)
    return {
        "build_number": resp.get("buildNumber"),
        "build_result_key": resp.get("buildResultKey"),
        "plan_key": resp.get("planKey"),
        "trigger_reason": resp.get("triggerReason"),
        "href": resp.get("link", {}).get("href")
    }
