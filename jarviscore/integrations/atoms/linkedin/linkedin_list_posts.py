def linkedin_list_posts(auth_info: dict, author_urn: str, count: int = 25, start: int = 0) -> list:
    import requests
    _base = "https://api.linkedin.com/v2"
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
    resp = _get("/ugcPosts", params={
        "q": "authors",
        "authors": f"List({author_urn})",
        "count": count,
        "start": start
    })
    return [
        {
            "id": post.get("id"),
            "author": post.get("author"),
            "created_at": post.get("created", {}).get("time"),
            "visibility": post.get("visibility", {}).get("com.linkedin.ugc.MemberNetworkVisibility"),
            "text": post.get("specificContent", {})
                       .get("com.linkedin.ugc.ShareContent", {})
                       .get("shareCommentary", {})
                       .get("text"),
            "media": [
                {"type": m.get("media"), "status": m.get("status")}
                for m in post.get("specificContent", {})
                              .get("com.linkedin.ugc.ShareContent", {})
                              .get("media", [])
            ]
        }
        for post in resp.get("elements", [])
    ]
