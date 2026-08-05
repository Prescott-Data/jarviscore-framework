import requests
from typing import Any, Dict, List, Optional


def podio_update_project(auth_info: dict, project_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update app configuration. Official: https://developers.podio.com/doc/applications/update-app-22342"""
    try:
        if not project_id:
            return _po_provision({}, 400, "project_id is required")
        if not isinstance(payload, dict) or not payload:
            return _po_provision({}, 400, "payload is required")
        root, err = _po_root(base_url, auth_info)
        if err:
            return _po_provision({}, 400, err)
        resp, body, status, msg = _po_request("put", root + "/app/" + str(project_id).strip(), auth_info, json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _po_provision(body if isinstance(body, dict) else {}, status, msg)
        data = body if isinstance(body, dict) else {}
        return _po_provision(data, status, "ok", fallback_id=project_id)
    except Exception as e:
        return _po_provision({}, 500, str(e))


# Podio Platform API — Official docs: https://developers.podio.com/doc/


def _po_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("podio_url") or auth_info.get("base_url") or "https://api.podio.com").strip().rstrip("/")
    return root, None


def _po_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    t = str(token).strip()
    if t.lower().startswith("oauth2 "):
        auth_val = t
    else:
        auth_val = "OAuth2 " + t
    headers = {"Accept": "application/json", "Authorization": auth_val}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _po_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _po_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _po_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("app_id") or obj.get("task_id") or obj.get("item_id") or obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _po_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("error_description") or body.get("error")
        if err:
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _po_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("items", "tasks", "results"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        return [data]
    return []


def _po_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _po_auth(auth_info, json_body=(json_body is not None))
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
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _po_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _po_scope_params(auth_info):
    auth_info = auth_info or {}
    params = {}
    for key in ("org", "space", "app", "responsible", "reference", "created_by", "completed_by", "completed"):
        val = auth_info.get(key)
        if val is not None and val != "":
            params[key] = val
    extra = auth_info.get("filters") or auth_info.get("params")
    if isinstance(extra, dict):
        params.update(extra)
    return params


def _po_paginate_get(path, base_url, auth_info, limit, timeout, verify_ssl, base_params=None):
    root, err = _po_root(base_url, auth_info)
    if err:
        return [], 400, err
    cap = _po_cap(limit)
    records = []
    offset = 0
    status = 200
    msg = "ok"
    while len(records) < cap:
        params = dict(base_params or {})
        params["limit"] = min(100, cap - len(records))
        params["offset"] = offset
        resp, body, status, msg = _po_request("get", root + path, auth_info, params=params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return records[:cap], status, msg
        batch = _po_items(body)
        records.extend(batch)
        if len(batch) < params["limit"]:
            break
        offset += len(batch)
    return records[:cap], status, msg
