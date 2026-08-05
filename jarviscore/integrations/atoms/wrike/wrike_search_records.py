import requests
from typing import Any, Dict, List, Optional

def wrike_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """wrike REST: search records. Official: https://developers.wrike.com/api/v4/"""
    try:
        root, err = _root(base_url, auth_info)
        if err: return _dataset([], 400, err)
        if not query: return _dataset([], 400, 'query is required')
        headers, aerr = _auth(auth_info)
        if aerr: return _dataset([], 401, aerr)
        resp = requests.get(root + "/tasks", headers=headers, params={"title": query}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _dataset([], resp.status_code, _err(resp))
        data = resp.json() if resp.content else {}
        if isinstance(data, dict) and 'data' in data: records = data['data'] if isinstance(data['data'], list) else [data['data']]
        elif isinstance(data, list): records = data
        else: records = [data] if isinstance(data, dict) else []
        return _dataset(records, resp.status_code, 'ok')
    except Exception as e: return _dataset([], 500, str(e))


# wrike REST API — Official: https://developers.wrike.com/api/v4/


def _root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("base_url") or "https://www.wrike.com/api/v4").strip().rstrip("/")
    if not root:
        return None, "base_url is required"
    return root, None


def _auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    tok = str(token).strip()
    return {"Authorization": tok if tok.lower().startswith("bearer ") else f"Bearer {tok}", "Accept": "application/json"}, None


def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("ID") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
