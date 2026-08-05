import requests
from typing import Any, Dict, List, Optional

def twilio_list_messages(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Twilio REST: list messages. Official: https://www.twilio.com/docs/usage/api"""
    try:
        root, err = _tw_root(base_url, auth_info)
        if err: return _tw_dataset([], 400, err)
        sid, token, aerr = _tw_account(auth_info)
        if aerr: return _tw_dataset([], 401, aerr)
        resp = requests.get(f"{root}/Messages.json", auth=(sid, token), params={"PageSize": limit}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _tw_dataset([], resp.status_code, _tw_err(resp))
        data = resp.json() if resp.content else {}
        return _tw_dataset(_tw_items(data, "messages"), resp.status_code, "ok")
    except Exception as e: return _tw_dataset([], 500, str(e))

# Twilio REST API — Official: https://www.twilio.com/docs/usage/api


def _tw_account(auth_info):
    auth_info = auth_info or {}
    sid = auth_info.get("username")
    token = auth_info.get("password")
    if not sid or not token:
        return None, None, "auth_info requires username and password"
    return str(sid).strip(), str(token).strip(), None


def _tw_root(base_url, auth_info):
    auth_info = auth_info or {}
    sid, _, err = _tw_account(auth_info)
    if err:
        return None, err
    root = (base_url or auth_info.get("twilio_url") or f"https://api.twilio.com/2010-04-01/Accounts/{sid}").strip().rstrip("/")
    return root, None


def _tw_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _tw_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("sid") or obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _tw_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _tw_items(data, key):
    if isinstance(data, dict):
        items = data.get(key)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []
