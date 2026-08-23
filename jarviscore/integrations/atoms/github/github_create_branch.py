def github_create_branch(auth_info: dict, owner: str, repo: str, branch: str, from_branch: str = None) -> dict:
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

    # Default to the repo's own default branch rather than assuming "main".
    base_branch = from_branch
    if not base_branch:
        base_branch = _get(f"/repos/{owner}/{repo}", headers=_accept).get("default_branch", "main")

    base_ref = _get(f"/repos/{owner}/{repo}/git/ref/heads/{base_branch}", headers=_accept)
    base_sha = base_ref["object"]["sha"]

    # Creating a ref that already exists returns 422; treat that as success so
    # re-running a workflow against the same branch is not a hard failure.
    try:
        r = _post(f"/repos/{owner}/{repo}/git/refs",
                  data={"ref": f"refs/heads/{branch}", "sha": base_sha},
                  headers=_accept)
        created = True
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 422:
            raise
        r = _get(f"/repos/{owner}/{repo}/git/ref/heads/{branch}", headers=_accept)
        created = False

    return {
        "branch": branch,
        "ref": r.get("ref"),
        "sha": r["object"]["sha"],
        "from_branch": base_branch,
        "created": created,
        "url": f"https://github.com/{owner}/{repo}/tree/{branch}",
    }
