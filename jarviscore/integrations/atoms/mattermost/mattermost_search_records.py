import requests
from typing import Any, Dict, List, Optional


def mattermost_search_records(auth_info: dict, query: str, team_id: str = "", limit: int = 25, page: int = 0, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search posts via POST /posts/search or POST /teams/{team_id}/posts/search. Official: https://api.mattermost.com/#tag/posts"""
    try:
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
        root, err = _mm_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, aerr = _mm_headers(auth_info, json_body=True)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        per_page = min(max(int(limit or 25), 1), 200)
        body = {
            "terms": str(query),
            "is_or_search": False,
            "page": max(int(page or 0), 0),
            "per_page": per_page,
        }
        team = _mm_team_id(team_id, auth_info)
        if team:
            url = f"{root}/teams/{team}/posts/search"
        else:
            url = f"{root}/posts/search"
        resp = requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": _mm_error(data, resp.text)}
        records = _mm_cap(_mm_posts_records(data), limit)
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}


# Mattermost REST API v4 — Official docs:
# Posts https://api.mattermost.com/#tag/posts


def _mm_api_root(base_url):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required"
    if not root.endswith("/api/v4"):
        root = root + "/api/v4"
    return root, None


def _mm_headers(auth_info, json_body=False):
    auth_info = auth_info or {}
    raw = auth_info.get("access_token")
    if not raw:
        return None, "auth_info.access_token is required"
    tok = str(raw).strip()
    prefix = "Bearer "
    auth = tok if tok.lower().startswith(prefix.lower()) else prefix + tok
    headers = {"Accept": "application/json", "Authorization": auth}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _mm_team_id(team_id, auth_info):
    auth_info = auth_info or {}
    val = team_id or auth_info.get("team_id")
    return str(val) if val not in (None, "") else ""


def _mm_posts_records(data):
    if not isinstance(data, dict):
        return []
    posts = data.get("posts") or {}
    order = data.get("order") or []
    if isinstance(posts, dict) and isinstance(order, list) and order:
        return [posts[pid] for pid in order if pid in posts and isinstance(posts[pid], dict)]
    if isinstance(posts, dict):
        return [row for row in posts.values() if isinstance(row, dict)]
    return []


def _mm_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 200)
    return records[:cap]


def _mm_error(data, fallback=""):
    if isinstance(data, dict):
        msg = data.get("message") or data.get("detailed_error")
        if msg:
            return str(msg)[:1000]
    return (fallback or "")[:1000]
