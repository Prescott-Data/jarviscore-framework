import requests
from typing import Any, Dict, List, Optional

def woocommerce_list_orders(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """woocommerce REST: list orders. Official: https://woocommerce.github.io/woocommerce-rest-api-docs/"""
    try:
        root, err = _root(base_url, auth_info)
        if err: return _dataset([], 400, err)
        headers, aerr = _auth(auth_info)
        if isinstance(headers, str) or aerr: return _dataset([], 401, aerr or headers)
        auth = headers if isinstance(headers, tuple) else None
        hdrs = headers if isinstance(headers, dict) else {'Accept':'application/json'}
        resp = requests.get(root + "/orders", headers=hdrs, auth=auth, params={'per_page': limit}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _dataset([], resp.status_code, _err(resp))
        data = resp.json() if resp.content else {}
        return _dataset(data if isinstance(data, list) else ([data] if isinstance(data, dict) else []), resp.status_code, 'ok')
    except Exception as e: return _dataset([], 500, str(e))


# woocommerce REST API — Official: https://woocommerce.github.io/woocommerce-rest-api-docs/


def _root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("base_url") or "https://example.com/wp-json/wc/v3").strip().rstrip("/")
    if not root:
        return None, "base_url is required"
    return root, None


def _auth(auth_info):
    auth_info = auth_info or {}
    username = auth_info.get("username")
    password = auth_info.get("password")
    if username and password:
        return (str(username), str(password)), None
    return None, "auth_info requires username and password"


def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _err(resp):
    return (resp.text or ("HTTP " + str(resp.status_code)))[:1000]
