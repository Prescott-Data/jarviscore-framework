def github_get_file(auth_info: dict, owner: str, repo: str, path: str, ref: str = None) -> dict:
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
    params = {}
    if ref:
        params["ref"] = ref
    f = _get(f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
               params=params,
               headers={"Accept": "application/vnd.github+json"})
    content = base64.b64decode(f["content"]).decode("utf-8") if f.get("encoding") == "base64" else f.get("content", "")
    return {
        "name": f["name"],
        "path": f["path"],
        "sha": f["sha"],
        "size": f["size"],
        "url": f["html_url"],
        "content": content
    }
