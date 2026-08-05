import requests
from typing import Any, Dict, List, Optional

# X Ads API — Official: https://developer.x.com/en/docs/twitter-ads-api

_XA_ROOT = "https://ads-api.x.com/12"


def twitter_ads_list_ads(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """X Ads API: list ads. Official: https://developer.x.com/en/docs/twitter-ads-api"""
    try:
        root, err = _xa_root(base_url, auth_info)
        if err: return _xa_dataset([], 400, err)
        headers, aerr = _xa_auth(auth_info)
        if aerr: return _xa_dataset([], 401, aerr)
        aid, err = _xa_account(auth_info)
        if err: return _xa_dataset([], 400, err)
        resp = requests.get(f"{root}/accounts/{aid}/promoted_tweets", headers=headers, params={"count": limit}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _xa_dataset([], resp.status_code, _xa_err(resp))
        return _xa_dataset(_xa_rows(resp.json() if resp.content else {}), resp.status_code, "ok")
    except Exception as e: return _xa_dataset([], 500, str(e))



def _xa_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("twitter_ads_url") or _XA_ROOT).strip().rstrip("/")
    return root, None


def _xa_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    tok = str(token).strip()
    return {"Authorization": tok if tok.lower().startswith("bearer ") else f"Bearer {tok}", "Accept": "application/json"}, None


def _xa_account(auth_info):
    auth_info = auth_info or {}
    aid = auth_info.get("account_id") or auth_info.get("ads_account_id")
    if not aid:
        return None, "auth_info.account_id is required"
    return str(aid), None


def _xa_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _xa_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _xa_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _xa_rows(data):
    if isinstance(data, list): return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, list): return [x for x in d if isinstance(x, dict)]
        if isinstance(d, dict): return [d]
    return []
