import requests
from typing import Any, Dict, List, Optional

# Jumia Seller Center API — http://sellerapi.sellercenter.jumia.com/v2.7.11/product-endpoints/getproducts/
JUMIA_SC_API = "http://sellerapi.sellercenter.jumia.com"
SC_VERSION = "1.0"


def jumia_seller_center_list_products(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List products via GetProducts. Official: http://sellerapi.sellercenter.jumia.com/v2.7.11/product-endpoints/getproducts/"""
    try:
        base, err = _jsc_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        user_id, api_key, cerr = _jsc_creds(auth_info)
        if cerr:
            return {"records": [], "data_count": 0, "status": 401, "message": cerr}
        cap = min(max(int(limit or 25), 1), 500)
        records: List[Dict[str, Any]] = []
        offset = 0
        status = 0
        while len(records) < cap:
            extra = {"Limit": str(min(cap - len(records), 500)), "Offset": str(offset)}
            resp = _jsc_call(base, "GetProducts", user_id, api_key, extra, timeout=timeout, verify_ssl=verify_ssl)
            data = _jsc_json(resp)
            status = 400 if data.get("ErrorResponse") else resp.status_code
            if status >= 400:
                return {"records": records, "data_count": len(records), "status": status, "message": _jsc_message(resp, data)}
            batch = _jsc_products(data)
            if not batch:
                break
            records.extend(batch)
            if len(batch) < int(extra["Limit"]):
                break
            offset += len(batch)
        return {"records": records[:cap], "data_count": len(records[:cap]), "status": status or 200, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _jsc_root(base_url):
    root = (base_url or JUMIA_SC_API).rstrip("/")
    if not root:
        return None, "base_url is required (http://sellerapi.sellercenter.jumia.com)"
    return root, None


def _jsc_creds(auth_info):
    auth_info = auth_info or {}
    user_id = auth_info.get("username")
    api_key = auth_info.get("password")
    if not user_id or not api_key:
        return None, None, "auth_info requires username and password"
    return str(user_id), str(api_key), None


def _jsc_timestamp():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _jsc_encode(params):
    from urllib.parse import quote
    parts = []
    for key in sorted(params.keys()):
        if key == "Signature":
            continue
        val = params[key]
        if val is None:
            continue
        parts.append(f"{quote(str(key), safe='')}={quote(str(val), safe='')}")
    return "&".join(parts)


def _jsc_sign(params, api_key):
    import hashlib
    import hmac
    encoded = _jsc_encode(params)
    return hmac.new(api_key.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).hexdigest()


def _jsc_call(base, action, user_id, api_key, extra=None, body=None, timeout=30, verify_ssl=True):
    params = {
        "Action": action,
        "Format": "JSON",
        "Timestamp": _jsc_timestamp(),
        "UserID": user_id,
        "Version": SC_VERSION,
    }
    if extra:
        params.update({k: v for k, v in extra.items() if v is not None})
    params["Signature"] = _jsc_sign(params, api_key)
    if body is not None:
        return requests.post(f"{base}/", params=params, data=body, headers={"Content-Type": "application/xml"}, timeout=timeout, verify=verify_ssl)
    return requests.get(f"{base}/", params=params, timeout=timeout, verify=verify_ssl)


def _jsc_json(resp):
    try:
        return resp.json() if resp.text else {}
    except Exception:
        return {}


def _jsc_body(data):
    if not isinstance(data, dict):
        return {}
    success = data.get("SuccessResponse") or {}
    body = success.get("Body") if isinstance(success, dict) else None
    return body if isinstance(body, dict) else {}


def _jsc_products(data):
    records = []
    body = _jsc_body(data)
    products = body.get("Products") if isinstance(body, dict) else None
    if isinstance(products, dict):
        prod = products.get("Product")
        if isinstance(prod, list):
            records.extend([p for p in prod if isinstance(p, dict)])
        elif isinstance(prod, dict):
            records.append(prod)
    return records


def _jsc_message(resp, data):
    if isinstance(data, dict) and data.get("ErrorResponse"):
        err = data["ErrorResponse"]
        head = err.get("Head") if isinstance(err, dict) else {}
        if isinstance(head, dict) and head.get("ErrorMessage"):
            return str(head["ErrorMessage"])
        return "Seller Center API error"
    if resp.status_code >= 400:
        return resp.text[:1000]
    return "ok"
