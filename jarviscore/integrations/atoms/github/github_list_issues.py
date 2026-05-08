def github_list_issues(auth_info: dict, owner: str, repo: str, state: str = "open", max_results: int = 30) -> list:
    import requests
    _base = "https://api.github.com"
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
    items = _get(f"/repos/{owner}/{repo}/issues", params={
        "state": state,
        "per_page": max_results,
        "sort": "updated"
    }, headers={"Accept": "application/vnd.github+json"})
    return [
        {
            "number": i["number"],
            "title": i["title"],
            "state": i["state"],
            "body": i.get("body"),
            "url": i["html_url"],
            "user": i["user"]["login"],
            "labels": [l["name"] for l in i.get("labels", [])],
            "created_at": i["created_at"],
            "updated_at": i["updated_at"],
            "is_pull_request": "pull_request" in i
        }
        for i in items
        if "pull_request" not in i
    ]
