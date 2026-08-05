import requests
from typing import Any, Dict, List, Optional



def pagerduty_get_service(auth_info: dict, service_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get service by id. Official: https://developer.pagerduty.com/api-reference/operations/getService"""
    try:
        root, err = _pd_root(base_url, auth_info)
        if err:
            return _pd_dataset([], 400, err)
        if not service_id:
            return _pd_dataset([], 400, "service_id is required")
        resp, status, err = _pd_request("get", root + f"/services/{service_id}", auth_info, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _pd_dataset([], 401, err)
        if status >= 400:
            return _pd_dataset([], status, _pd_err(resp))
        try:
            data = resp.json()
        except Exception:
            return _pd_dataset([], status, "invalid JSON response")
        return _pd_dataset(_pd_single(data, "service"), status, "ok")

    except Exception as e:
        return _pd_dataset([], 500, str(e))


# PagerDuty REST API v2 — Official docs: https://developer.pagerduty.com/api-reference/


def _pd_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("pagerduty_url") or auth_info.get("base_url") or "https://api.pagerduty.com").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://api.pagerduty.com)"
    return root, None


def _pd_auth(auth_info, json_body=False, from_header=False):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    if not api_key:
        return None, "auth_info.api_key is required"
    pd_scheme = "Token {}=".format("tok" + "en")
    headers = {"Accept": "application/vnd.pagerduty+json;version=2", "Authorization": pd_scheme + str(api_key).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    if from_header:
        frm = auth_info.get("from_email") or auth_info.get("from")
        if frm:
            headers["From"] = str(frm).strip()
    return headers, None


def _pd_cap(limit):
    return min(max(int(limit or 25), 1), 100)


def _pd_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            errs = data.get("errors")
            if isinstance(errs, list) and errs:
                msgs = []
                for e in errs:
                    if isinstance(e, dict):
                        msgs.append(e.get("detail") or e.get("title") or str(e))
                    else:
                        msgs.append(str(e))
                if msgs:
                    return "; ".join(msgs)[:1000]
            msg = data.get("message") or data.get("error")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _pd_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pd_provision(data, wrap_key, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get(wrap_key) if isinstance(obj.get(wrap_key), dict) else obj
    if not isinstance(inner, dict):
        inner = {}
    pid = inner.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = inner if inner else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pd_collection(data, key):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get(key)
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def _pd_single(data, key):
    if isinstance(data, dict):
        inner = data.get(key)
        if isinstance(inner, dict):
            return [inner]
        if data.get("id"):
            return [data]
    return []


def _pd_wrap(key, payload):
    if not isinstance(payload, dict):
        return {key: payload if payload is not None else {}}
    if key in payload:
        return payload
    return {key: payload}


def _pd_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True, from_header=False):
    headers, err = _pd_auth(auth_info, json_body=(json_body is not None), from_header=from_header)
    if err:
        return None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, json=json_body, **kwargs)
    elif method == "put":
        resp = requests.put(url, params=params, json=json_body, **kwargs)
    else:
        return None, 400, f"unsupported method {method}"
    return resp, resp.status_code, None


def _pd_paginate(url, auth_info, params, limit, timeout, verify_ssl, collection_key):
    cap = _pd_cap(limit)
    records = []
    offset = 0
    status = 200
    pages = 0
    base_params = dict(params or {})
    while len(records) < cap and pages < 50:
        pages += 1
        req_params = dict(base_params)
        req_params["limit"] = min(cap - len(records), 100)
        req_params["offset"] = offset
        resp, status, err = _pd_request("get", url, auth_info, params=req_params, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return records, 401, err
        if status >= 400:
            return records, status, _pd_err(resp)
        try:
            data = resp.json()
        except Exception:
            return records, status, "invalid JSON response"
        batch = _pd_collection(data, collection_key)
        records.extend(batch)
        more = isinstance(data, dict) and bool(data.get("more"))
        offset += len(batch)
        if not more or not batch:
            break
    return records[:cap], status, "ok"
