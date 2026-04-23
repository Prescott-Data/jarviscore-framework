def github_create_issue(auth_info: dict, owner: str, repo: str, title: str, body: str = None, labels: list = None) -> dict:
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
    payload = {"title": title}
    if body:
        payload["body"] = body
    if labels:
        payload["labels"] = labels
    i = _post(f"/repos/{owner}/{repo}/issues", data=payload, headers={"Accept": "application/vnd.github+json"})
    return {
        "number": i["number"],
        "title": i["title"],
        "state": i["state"],
        "url": i["html_url"],
        "created_at": i["created_at"]
    }
