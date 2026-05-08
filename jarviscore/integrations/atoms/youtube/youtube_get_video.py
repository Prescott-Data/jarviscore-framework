def youtube_get_video(auth_info: dict, video_id: str) -> dict:
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
    resp = _get("/videos", params={
        "part": "snippet,contentDetails,statistics",
        "id": video_id
    })
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Video '{video_id}' not found")
    item = items[0]
    return {
        "id": item["id"],
        "title": item["snippet"]["title"],
        "description": item["snippet"]["description"],
        "channel": item["snippet"]["channelTitle"],
        "published_at": item["snippet"]["publishedAt"],
        "duration": item["contentDetails"]["duration"],
        "view_count": item["statistics"].get("viewCount"),
        "like_count": item["statistics"].get("likeCount"),
        "comment_count": item["statistics"].get("commentCount"),
        "thumbnail": item["snippet"]["thumbnails"].get("high", {}).get("url")
    }
