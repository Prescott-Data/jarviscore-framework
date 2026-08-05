import requests
from typing import Any, Dict, List, Optional

def shift4shop_update_order(auth_info: dict, order_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Shift4Shop REST: update order. Official: https://developers.3dcart.com/rest-api/orders"""
    try:
        if not order_id: return _s4_provision({}, 400, "order_id is required")
        if not isinstance(payload, dict) or not payload: return _s4_provision({}, 400, "payload is required")
        root, err = _s4_root(base_url, auth_info)
        if err: return _s4_provision({}, 400, err)
        headers, aerr = _s4_auth(auth_info)
        if aerr: return _s4_provision({}, 401, aerr)
        headers["Content-Type"] = "application/json"
        resp = requests.put(root + "/Orders/" + str(order_id), headers=headers, json=payload, timeout=timeout, verify=verify_ssl)
        try: data = resp.json() if resp.content else {}
        except Exception: data = {}
        if resp.status_code >= 400: return _s4_provision(data if isinstance(data, dict) else {}, resp.status_code, _s4_err(resp))
        return _s4_provision(data if isinstance(data, dict) else {}, resp.status_code, "ok", fallback_id=order_id)
    except Exception as e: return _s4_provision({}, 500, str(e))


# Shift4Shop REST API — Official docs: https://developers.3dcart.com/


def _s4_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("shift4shop_url") or auth_info.get("store_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://store.example.com)"
    if not root.endswith("/3dCartWebAPI/v1"):
        root = root + "/3dCartWebAPI/v1"
    return root, None


def _s4_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key") or auth_info.get("token")
    if not token:
        return None, "auth_info.api_key is required"
    private_key = auth_info.get("private_key") or auth_info.get("secure_url_token") or ""
    secure_url = (auth_info.get("secure_url") or auth_info.get("shift4shop_url") or auth_info.get("store_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    return {"Accept": "application/json", "Content-Type": "application/json", "Token": str(token).strip(), "PrivateKey": str(private_key).strip(), "SecureURL": secure_url, "Authorization": "Bearer " + str(token).strip()}, None


def _s4_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _s4_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _s4_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("CatalogID") or obj.get("OrderID") or obj.get("CustomerID") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _s4_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
