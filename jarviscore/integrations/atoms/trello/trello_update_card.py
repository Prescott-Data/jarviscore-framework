import requests
from typing import Any, Dict, List, Optional

# Trello REST API — Official: https://developer.atlassian.com/cloud/trello/rest/

_TR_ROOT = "https://api.trello.com/1"

def trello_update_card(auth_info: dict, card_id: str, name: str = "", timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Trello REST: update card. Official: https://developer.atlassian.com/cloud/trello/rest/"""
    try:
        root, err = _tr_root(base_url, auth_info)
        if err: return _tr_provision({}, 400, err)
        if not card_id: return _tr_provision({}, 400, "card_id is required")
        params, aerr = _tr_auth_params(auth_info)
        if aerr: return _tr_provision({}, 401, aerr)
        if name: params["name"] = name
        resp = requests.put(f"{root}/cards/{card_id}", params=params, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _tr_provision({}, resp.status_code, _tr_err(resp))
        data = resp.json() if resp.content else {}
        return _tr_provision(data if isinstance(data, dict) else {}, resp.status_code, "ok", fallback_id=card_id)
    except Exception as e: return _tr_provision({}, 500, str(e))


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
