def youtube_get_channel(auth_info: dict, channel_id: str) -> dict:
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
    resp = _get("/channels", params={
        "part": "snippet,statistics,contentDetails",
        "id": channel_id
    })
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Channel '{channel_id}' not found")
    item = items[0]
    return {
        "id": item["id"],
        "title": item["snippet"]["title"],
        "description": item["snippet"]["description"],
        "published_at": item["snippet"]["publishedAt"],
        "subscriber_count": item["statistics"].get("subscriberCount"),
        "video_count": item["statistics"].get("videoCount"),
        "view_count": item["statistics"].get("viewCount"),
        "thumbnail": item["snippet"]["thumbnails"].get("default", {}).get("url"),
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"].get("uploads")
    }
