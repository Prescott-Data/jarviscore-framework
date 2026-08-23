def github_create_or_update_file(auth_info: dict, owner: str, repo: str, path: str, content: str, message: str, branch: str = None, sha: str = None) -> dict:
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
    import base64
    _accept = {"Accept": "application/vnd.github+json"}
    clean_path = path.lstrip("/")

    # An update needs the blob sha of the file being replaced. Look it up when
    # the caller did not supply one; a 404 means the file is new.
    if sha is None:
        params = {"ref": branch} if branch else {}
        try:
            existing = _get(f"/repos/{owner}/{repo}/contents/{clean_path}", params=params, headers=_accept)
            if isinstance(existing, dict):
                sha = existing.get("sha")
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code != 404:
                raise

    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if branch:
        payload["branch"] = branch
    if sha:
        payload["sha"] = sha

    r = _put(f"/repos/{owner}/{repo}/contents/{clean_path}", data=payload, headers=_accept)
    c = r.get("content") or {}
    commit = r.get("commit") or {}
    return {
        "path": c.get("path", clean_path),
        "sha": c.get("sha"),
        "url": c.get("html_url"),
        "commit_sha": commit.get("sha"),
        "commit_url": commit.get("html_url"),
        "created": sha is None,
    }
