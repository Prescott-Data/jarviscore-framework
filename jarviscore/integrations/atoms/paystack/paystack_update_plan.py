import requests
from typing import Any, Dict, List, Optional



def paystack_update_plan(auth_info: dict, plan_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update plan by id or plan code via PUT. Official: https://paystack.com/docs/api/plan/#update-plan"""
    try:
        root, err = _ps_root(base_url, auth_info)
        if err:
            return _ps_provision({}, 400, err)
        if not plan_id:
            return _ps_provision({}, 400, "plan_id is required")
        if not isinstance(payload, dict) or not payload:
            return _ps_provision({}, 400, "payload is required")
        resp, data, status, err = _ps_request("put", root + f"/plan/{plan_id}", auth_info, json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _ps_provision({}, 401, err)
        if not _ps_ok(resp, data):
            return _ps_provision(data, status, _ps_err(resp))
        return _ps_provision(data, status, "ok", fallback_id=plan_id)

    except Exception as e:
        return _ps_provision({}, 500, str(e))


# Paystack REST API — Official docs: https://paystack.com/docs/api/


def _ps_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("paystack_url") or auth_info.get("base_url") or "https://api.paystack.co").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://api.paystack.co)"
    return root, None


def _ps_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    secret = auth_info.get("api_key")
    if not secret:
        return None, "auth_info.api_key is required"
    headers = {"Accept": "application/json", "Authorization": "Bearer " + str(secret).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _ps_cap(limit):
    return min(max(int(limit or 25), 1), 100)


def _ps_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _ps_ok(resp, data):
    if resp.status_code >= 400:
        return False
    return not (isinstance(data, dict) and data.get("status") is False)


def _ps_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _ps_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get("data") if isinstance(obj.get("data"), dict) else obj
    if not isinstance(inner, dict):
        inner = obj
    pid = inner.get("reference") or inner.get("customer_code") or inner.get("plan_code") or inner.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = inner if inner else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _ps_items(data):
    if not isinstance(data, dict):
        return []
    inner = data.get("data")
    if isinstance(inner, list):
        return [x for x in inner if isinstance(x, dict)]
    if isinstance(inner, dict):
        return [inner]
    return []


def _ps_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _ps_auth(auth_info, json_body=(json_body is not None))
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
    return resp, data, resp.status_code, None


def _ps_paginate(url, auth_info, params, limit, timeout, verify_ssl):
    auth_info = auth_info or {}
    cap = _ps_cap(limit)
    page = max(int(auth_info.get("page") or 1), 1)
    records = []
    status = 200
    pages = 0
    base_params = dict(params or {})
    use_cursor = str(auth_info.get("use_cursor", "")).lower() in ("1", "true", "yes")
    cursor = auth_info.get("cursor")
    while len(records) < cap and pages < 50:
        pages += 1
        req_params = dict(base_params)
        req_params["perPage"] = min(cap - len(records), 100)
        if use_cursor:
            req_params["use_cursor"] = "true"
            if cursor:
                req_params["next"] = cursor
        else:
            req_params["page"] = page
        resp, data, status, err = _ps_request("get", url, auth_info, params=req_params, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return records, 401, err
        if not _ps_ok(resp, data):
            return records, status, _ps_err(resp)
        batch = _ps_items(data)
        records.extend(batch)
        meta = data.get("meta") if isinstance(data, dict) else {}
        if use_cursor:
            cursor = meta.get("next") if isinstance(meta, dict) else None
            if not cursor or not batch:
                break
        else:
            page_count = meta.get("pageCount") if isinstance(meta, dict) else None
            if page_count and page >= int(page_count):
                break
            if not batch:
                break
            page += 1
    return records[:cap], status, "ok"
