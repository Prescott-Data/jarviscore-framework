def bamboo_get_build_results(auth_info: dict, cloud_id: str, plan_key: str, max_results: int = 10) -> list:
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
    resp = _get(f"/rest/api/latest/result/{plan_key}", params={
        "max-result": max_results,
        "expand": "results.result"
    })
    results = resp.get("results", {}).get("result", [])
    return [
        {
            "key": r["key"],
            "build_number": r.get("buildNumber"),
            "state": r.get("state"),
            "build_state": r.get("buildState"),
            "life_cycle_state": r.get("lifeCycleState"),
            "started_at": r.get("buildStartedTime"),
            "completed_at": r.get("buildCompletedTime"),
            "duration_seconds": r.get("buildDurationInSeconds"),
            "href": r.get("link", {}).get("href")
        }
        for r in results
    ]
