def youtube_get_playlist_items(auth_info: dict, playlist_id: str, max_results: int = 25) -> list:
    import requests
    _base = "https://www.googleapis.com/youtube/v3"
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
    resp = _get("/playlistItems", params={
        "part": "snippet,contentDetails",
        "playlistId": playlist_id,
        "maxResults": max_results
    })
    return [
        {
            "video_id": item["contentDetails"]["videoId"],
            "title": item["snippet"]["title"],
            "description": item["snippet"]["description"],
            "published_at": item["snippet"]["publishedAt"],
            "position": item["snippet"]["position"],
            "thumbnail": item["snippet"]["thumbnails"].get("default", {}).get("url")
        }
        for item in resp.get("items", [])
    ]
