import requests
from typing import Any, Dict, List, Optional

# Wix REST API — Official: https://dev.wix.com/docs/rest/business-solutions
# Base: https://www.wixapis.com. Products: /stores/v1; Orders (eCom): /ecom/v1; Customers (Contacts): /contacts/v4.
# Auth: Authorization: {access_token} (raw, no Bearer) + wix-site-id header (site-level calls).
WIX_API = "https://www.wixapis.com"


def wix_stores_search_records(auth_info: dict, query: str, site_id: str = "", limit: int = 100, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """wix_stores API: search records. Official: https://dev.wix.com/docs/rest/business-solutions/stores"""
    try:
        if not query:
            return _wx_dataset([], 400, "query is required")
        import json
        root, err = _wx_root(base_url, auth_info)
        if err:
            return _wx_dataset([], 400, err)
        headers, aerr = _wx_headers(auth_info, site_id)
        if aerr:
            return _wx_dataset([], 401, aerr)
        body = {"query": {"filter": json.dumps({"name": {"$contains": query}}), "paging": {"limit": limit}}}
        resp = requests.post(f"{root}/stores/v1/products/query", headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return _wx_dataset([], resp.status_code, _wx_err(resp))
        return _wx_dataset(_wx_list(resp.json() if resp.content else {}), resp.status_code, "ok")
    except Exception as e:
        return _wx_dataset([], 500, str(e))



def _wx_root(base_url, auth_info):
    auth_info = auth_info or {}
    raw = (base_url or auth_info.get("base_url") or WIX_API).strip().rstrip("/")
    if "wixapis.com" not in raw:
        return None, "base_url must be https://www.wixapis.com"
    return raw[: raw.index("wixapis.com") + len("wixapis.com")], None


def _wx_headers(auth_info, site_id):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    sid = site_id or auth_info.get("site_id")
    if not sid:
        return None, "site_id is required (wix-site-id header for site-level calls)"
    tok = str(token).strip()
    if tok.lower().startswith("bearer "):
        tok = tok.split(" ", 1)[1]
    return {"Authorization": tok, "wix-site-id": str(sid), "Content-Type": "application/json", "Accept": "application/json"}, None


def _wx_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _wx_provision(data, status, msg, key=None, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get(key) if key and isinstance(obj.get(key), dict) else obj
    pid = inner.get("id") or inner.get("_id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = inner if inner else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _wx_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _wx_list(data):
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        return [data] if data else []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _wx_obj(data, key):
    if isinstance(data, dict):
        if isinstance(data.get(key), dict):
            return [data[key]]
        return [data] if data else []
    return []
