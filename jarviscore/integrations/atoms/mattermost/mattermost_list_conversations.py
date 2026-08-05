import requests
from typing import Any, Dict, List, Optional


def mattermost_list_conversations(auth_info: dict, team_id: str = "", user_id: str = "", limit: int = 25, page: int = 0, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List channels for a user via GET /users/me/channels or GET /users/me/teams/{team_id}/channels. Official: https://api.mattermost.com/#tag/channels"""
    try:
        root, err = _mm_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, aerr = _mm_headers(auth_info)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        team = _mm_team_id(team_id, auth_info)
        user = _mm_user_id(user_id, auth_info)
        per_page = min(max(int(limit or 25), 1), 200)
        records: List[Dict[str, Any]] = []
        status = 0
        if team:
            url = f"{root}/users/{user}/teams/{team}/channels"
        else:
            url = f"{root}/users/{user}/channels"
        resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        try:
            data = resp.json() if resp.text else []
        except Exception:
            data = []
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": _mm_error(data, resp.text)}
        records = _mm_records(data)
        if team and page:
            start = max(int(page or 0), 0) * per_page
            records = records[start : start + per_page]
        records = _mm_cap(records, limit)
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}


# Mattermost REST API v4 — Official docs:
# Channels https://api.mattermost.com/#tag/channels
# Introduction https://developers.mattermost.com/integrate/reference/rest-api/


def _mm_api_root(base_url):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required"
    if not root.endswith("/api/v4"):
        root = root + "/api/v4"
    return root, None


def _mm_headers(auth_info):
    auth_info = auth_info or {}
    raw = auth_info.get("access_token")
    if not raw:
        return None, "auth_info.access_token is required"
    tok = str(raw).strip()
    prefix = "Bearer "
    auth = tok if tok.lower().startswith(prefix.lower()) else prefix + tok
    return {"Accept": "application/json", "Authorization": auth}, None


def _mm_team_id(team_id, auth_info):
    auth_info = auth_info or {}
    val = team_id or auth_info.get("team_id")
    return str(val) if val not in (None, "") else ""


def _mm_user_id(user_id, auth_info):
    auth_info = auth_info or {}
    val = user_id or auth_info.get("user_id") or "me"
    return str(val)


def _mm_records(data):
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
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
