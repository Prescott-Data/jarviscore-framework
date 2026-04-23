def github_get_pull_request(auth_info: dict, owner: str, repo: str, pull_number: int) -> dict:
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
    pr = _get(f"/repos/{owner}/{repo}/pulls/{pull_number}", headers={"Accept": "application/vnd.github+json"})
    return {
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "body": pr.get("body"),
        "url": pr["html_url"],
        "user": pr["user"]["login"],
        "head": pr["head"]["ref"],
        "base": pr["base"]["ref"],
        "draft": pr.get("draft", False),
        "mergeable": pr.get("mergeable"),
        "merged": pr.get("merged", False),
        "commits": pr.get("commits"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "changed_files": pr.get("changed_files"),
        "created_at": pr["created_at"],
        "updated_at": pr["updated_at"]
    }
