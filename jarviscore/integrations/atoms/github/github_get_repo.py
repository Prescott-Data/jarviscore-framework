def github_get_repo(auth_info: dict, owner: str, repo: str) -> dict:
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
    r = _get(f"/repos/{owner}/{repo}", headers={"Accept": "application/vnd.github+json"})
    return {
        "id": r["id"],
        "name": r["name"],
        "full_name": r["full_name"],
        "description": r.get("description"),
        "private": r["private"],
        "url": r["html_url"],
        "default_branch": r["default_branch"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "language": r.get("language"),
        "stars": r["stargazers_count"],
        "forks": r["forks_count"],
        "open_issues": r["open_issues_count"],
        "topics": r.get("topics", [])
    }
