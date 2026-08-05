import requests
from typing import Any, Dict, List, Optional

# Trello REST API — Official: https://developer.atlassian.com/cloud/trello/rest/

_TR_ROOT = "https://api.trello.com/1"

def trello_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Trello REST: search records. Official: https://developer.atlassian.com/cloud/trello/rest/"""
    try:
        root, err = _tr_root(base_url, auth_info)
        if err: return _tr_dataset([], 400, err)
        if not query: return _tr_dataset([], 400, "query is required")
        params, aerr = _tr_auth_params(auth_info)
        if aerr: return _tr_dataset([], 401, aerr)
        params.update({"query": query, "modelTypes": "cards,boards", "cards_limit": limit})
        resp = requests.get(f"{root}/search", params=params, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _tr_dataset([], resp.status_code, _tr_err(resp))
        data = resp.json() if resp.content else {}
        cards = data.get("cards") if isinstance(data, dict) else []
        return _tr_dataset(cards if isinstance(cards, list) else [], resp.status_code, "ok")
    except Exception as e: return _tr_dataset([], 500, str(e))


def _tr_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("trello_url") or _TR_ROOT).strip().rstrip("/")
    return root, None


def _tr_auth_params(auth_info):
    auth_info = auth_info or {}
    key = auth_info.get("username")
    token = auth_info.get("password")
    if not key or not token:
        return None, "auth_info requires username and password"
    return {"key": str(key).strip(), "token": str(token).strip()}, None


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
