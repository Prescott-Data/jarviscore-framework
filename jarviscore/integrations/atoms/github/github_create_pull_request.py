def github_create_pull_request(auth_info: dict, owner: str, repo: str, title: str, head: str, base: str = None, body: str = None, draft: bool = False) -> dict:
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
    _accept = {"Accept": "application/vnd.github+json"}

    target = base
    if not target:
        target = _get(f"/repos/{owner}/{repo}", headers=_accept).get("default_branch", "main")

    payload = {"title": title, "head": head, "base": target, "draft": bool(draft)}
    if body:
        payload["body"] = body

    # A pull request for this head/base pair may already be open; return it
    # instead of failing so a re-run stays idempotent.
    try:
        pr = _post(f"/repos/{owner}/{repo}/pulls", data=payload, headers=_accept)
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 422:
            raise
        open_prs = _get(f"/repos/{owner}/{repo}/pulls",
                        params={"head": f"{owner}:{head}", "base": target, "state": "open"},
                        headers=_accept)
        if not open_prs:
            raise
        pr = open_prs[0]

    return {
        "number": pr["number"],
        "title": pr["title"],
        "state": pr["state"],
        "url": pr["html_url"],
        "head": pr["head"]["ref"],
        "base": pr["base"]["ref"],
        "created_at": pr["created_at"],
    }
