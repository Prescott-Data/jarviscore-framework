import requests
from typing import Any, Dict, List, Optional


def mattermost_get_conversation(auth_info: dict, conversation_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get a channel by id via GET /channels/{channel_id}. Official: https://api.mattermost.com/#tag/channels"""
    try:
        channel_id = _mm_channel_id(conversation_id, auth_info)
        if not channel_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "conversation_id is required"}
        root, err = _mm_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, aerr = _mm_headers(auth_info)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        resp = requests.get(f"{root}/channels/{channel_id}", headers=headers, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": _mm_error(data, resp.text)}
        records = [data] if isinstance(data, dict) and data.get("id") else ([data] if isinstance(data, dict) else [])
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}


# Mattermost REST API v4 — Official docs:
# Channels https://api.mattermost.com/#tag/channels


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


def _mm_channel_id(conversation_id, auth_info):
    auth_info = auth_info or {}
    val = conversation_id or auth_info.get("channel_id") or auth_info.get("conversation_id")
    return str(val) if val not in (None, "") else ""


def _mm_error(data, fallback=""):
    if isinstance(data, dict):
        msg = data.get("message") or data.get("detailed_error")
        if msg:
            return str(msg)[:1000]
    return (fallback or "")[:1000]
