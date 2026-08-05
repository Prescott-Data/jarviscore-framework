import requests
from typing import Any, Dict, List, Optional


def mattermost_create_message(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create a post via POST /posts. Official: https://api.mattermost.com/#tag/posts"""
    try:
        root, err = _mm_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        headers, aerr = _mm_headers(auth_info, json_body=True)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr, "provision_ids": []}
        body, berr = _mm_post_body(payload, auth_info)
        if berr:
            return {"records": [], "data_count": 0, "status": 400, "message": berr, "provision_ids": []}
        resp = requests.post(f"{root}/posts", headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": _mm_error(data, resp.text), "provision_ids": []}
        return _mm_provision(data, resp.status_code)
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}


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


def _mm_error(data, fallback=""):
    if isinstance(data, dict):
        msg = data.get("message") or data.get("detailed_error")
        if msg:
            return str(msg)[:1000]
    return (fallback or "")[:1000]


def _mm_provision(data, status, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    obj_id = obj.get("id") or fallback_id
    ids = [obj_id] if obj_id not in (None, "") else []
    records = [obj] if obj else ([{"id": obj_id}] if obj_id else [])
    return {
        "records": records,
        "data_count": len(records),
        "status": status,
        "message": "ok" if status < 400 else _mm_error(data, str(obj)),
        "provision_ids": ids,
    }


def _mm_post_body(payload, auth_info):
    body = dict(payload) if isinstance(payload, dict) else {}
    auth_info = auth_info or {}
    channel_id = body.get("channel_id") or body.get("conversation_id") or auth_info.get("channel_id") or auth_info.get("conversation_id")
    message = body.get("message") or body.get("text")
    if not channel_id or not message:
        return None, "payload.channel_id and payload.message are required"
    out = {"channel_id": str(channel_id), "message": str(message)}
    if body.get("root_id") not in (None, ""):
        out["root_id"] = body.get("root_id")
    if body.get("file_ids"):
        out["file_ids"] = body.get("file_ids")
    return out, None
