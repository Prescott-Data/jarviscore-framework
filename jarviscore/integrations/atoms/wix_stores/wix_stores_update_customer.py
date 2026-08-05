import requests
from typing import Any, Dict, List, Optional

# Wix REST API — Official: https://dev.wix.com/docs/rest/business-solutions
# Base: https://www.wixapis.com. Products: /stores/v1; Orders (eCom): /ecom/v1; Customers (Contacts): /contacts/v4.
# Auth: Authorization: {access_token} (raw, no Bearer) + wix-site-id header (site-level calls).
WIX_API = "https://www.wixapis.com"


def wix_stores_update_customer(auth_info: dict, contact_id: str, revision: int, site_id: str = "", first_name: str = "", last_name: str = "", email: str = "", timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """wix_stores API: update customer. Official: https://dev.wix.com/docs/rest/business-solutions/stores"""
    try:
        if not contact_id:
            return _wx_provision({}, 400, "contact_id is required")
        if revision is None:
            return _wx_provision({}, 400, "revision is required (optimistic concurrency)")
        root, err = _wx_root(base_url, auth_info)
        if err:
            return _wx_provision({}, 400, err)
        headers, aerr = _wx_headers(auth_info, site_id)
        if aerr:
            return _wx_provision({}, 401, aerr)
        info: Dict[str, Any] = {}
        if first_name or last_name:
            info["name"] = {"first": first_name, "last": last_name}
        if email:
            info["emails"] = {"items": [{"email": email, "primary": True}]}
        resp = requests.patch(f"{root}/contacts/v4/contacts/{contact_id}", headers=headers, json={"info": info, "revision": revision}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return _wx_provision({}, resp.status_code, _wx_err(resp))
        return _wx_provision(resp.json() if resp.content else {}, resp.status_code, "ok", key="contact", fallback_id=contact_id)
    except Exception as e:
        return _wx_provision({}, 500, str(e))



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
