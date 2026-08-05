import requests
from typing import Any, Dict, List, Optional

def square_update_payment(auth_info: dict, payment_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Square API v2: update payment. Official: https://developer.squareup.com/reference/square/payments-api/update-payment"""
    try:
        if not payment_id: return _sq_provision({}, 400, "payment_id is required")
        if not isinstance(payload, dict) or not payload: return _sq_provision({}, 400, "payload is required")
        root, _ = _sq_root(base_url, auth_info)
        path = "/customers" if "payment" == "customer" else ("/orders" if "payment" == "order" else "/payments")
        body = payload if "payment" in payload else {"payment": payload}
        _, data, status, msg = _sq_request("put", root + path + "/{payment_id}".format(**locals()), auth_info, json_body=body, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400: return _sq_provision(data if isinstance(data, dict) else {}, status, msg)
        return _sq_provision(data if isinstance(data, dict) else {}, status, "ok", fallback_id=payment_id)
    except Exception as e: return _sq_provision({}, 500, str(e))


# Square Connect API v2 — Official docs: https://developer.squareup.com/reference/square


def _sq_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("square_url") or auth_info.get("base_url") or "https://connect.squareup.com").strip().rstrip("/")
    return root + "/v2", None


def _sq_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    t = str(token).strip()
    headers = {"Accept": "application/json", "Authorization": t if t.lower().startswith("bearer ") else f"Bearer {t}", "Square-Version": str(auth_info.get("square_version") or "2024-04-17")}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _sq_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _sq_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sq_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    for key in ("customer", "order", "payment"):
        if isinstance(obj.get(key), dict):
            obj = obj[key]
            break
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _sq_err(resp, body=None):
    if isinstance(body, dict):
        errs = body.get("errors")
        if isinstance(errs, list) and errs:
            return str(errs[0])[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _sq_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _sq_auth(auth_info, json_body=(json_body is not None))
    if err:
        return None, None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, json=json_body, **kwargs)
    elif method == "put":
        resp = requests.put(url, params=params, json=json_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {}
    if resp.status_code >= 400:
        return resp, data, resp.status_code, _sq_err(resp, data)
    if isinstance(data, dict) and data.get("errors"):
        return resp, data, 400, _sq_err(resp, data)
    return resp, data, resp.status_code, "ok"
