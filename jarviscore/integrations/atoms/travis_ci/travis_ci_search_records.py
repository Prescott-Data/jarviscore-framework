import requests
from typing import Any, Dict, List, Optional

# Travis CI API v3 — Official: https://developer.travis-ci.com/resource

_TR_ROOT = "https://api.travis-ci.com"

def travis_ci_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Travis CI API v3: search records. Official: https://developer.travis-ci.com/resource"""
    try:
        root, err = _tr_root(base_url, auth_info)
        if err: return _tr_dataset([], 400, err)
        if not query: return _tr_dataset([], 400, "query is required")
        headers, aerr = _tr_auth(auth_info)
        if aerr: return _tr_dataset([], 401, aerr)
        resp = requests.get(f"{root}/repos", headers=headers, params={"limit": 100}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _tr_dataset([], resp.status_code, _tr_err(resp))
        data = resp.json() if resp.content else {}
        repos = data.get("repositories") if isinstance(data, dict) else []
        q = query.lower()
        matched = [r for r in repos if isinstance(r, dict) and q in str(r.get("slug","")).lower()]
        return _tr_dataset(matched[:limit], resp.status_code, "ok")
    except Exception as e: return _tr_dataset([], 500, str(e))


def _tr_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("travis_url") or _TR_ROOT).strip().rstrip("/")
    return root, None


def _tr_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.access_token is required"
    tok = str(token).strip()
    return {"Authorization": tok if tok.lower().startswith("token ") else f"token {tok}", "Accept": "application/json", "Travis-API-Version": "3"}, None


def _tr_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _tr_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _tr_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
