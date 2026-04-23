def github_list_repos(auth_info: dict, visibility: str = "all", max_results: int = 30) -> list:
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
    resp = _get("/user/repos", params={
        "visibility": visibility,
        "sort": "updated",
        "per_page": max_results
    }, headers={"Accept": "application/vnd.github+json"})
    return [
        {
            "id": repo["id"],
            "name": repo["name"],
            "full_name": repo["full_name"],
            "description": repo.get("description"),
            "private": repo["private"],
            "url": repo["html_url"],
            "default_branch": repo["default_branch"],
            "updated_at": repo["updated_at"],
            "language": repo.get("language"),
            "stars": repo["stargazers_count"],
            "forks": repo["forks_count"]
        }
        for repo in resp
    ]
