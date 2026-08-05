import requests
from typing import Any, Dict, List, Optional


def pivotal_tracker_update_project(auth_info: dict, project_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update project. Official: https://www.pivotaltracker.com/help/api/rest/v5"""
    try:
        if not project_id:
            return _pt_provision({}, 400, "project_id is required")
        if not isinstance(payload, dict) or not payload:
            return _pt_provision({}, 400, "payload is required")
        root, err = _pt_root(base_url, auth_info)
        if err:
            return _pt_provision({}, 400, err)
        resp, body, status, msg = _pt_request("put", root + "/projects/" + str(project_id).strip(), auth_info, json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _pt_provision(body if isinstance(body, dict) else {}, status, msg)
        data = body if isinstance(body, dict) else {}
        return _pt_provision(data, status, "ok", fallback_id=project_id)
    except Exception as e:
        return _pt_provision({}, 500, str(e))


# Pivotal Tracker REST API v5 — Official docs: https://www.pivotaltracker.com/help/api/rest/v5


def _pt_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (
        base_url
        or auth_info.get("tracker_url")
        or auth_info.get("pivotal_tracker_url")
        or auth_info.get("base_url")
        or "https://www.pivotaltracker.com/services/v5"
    ).strip().rstrip("/")
    if "/services/v" not in root:
        root = root + "/services/v5"
    return root, None


def _pt_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.tracker_token or api_token is required"
    headers = {"X-TrackerToken": str(token).strip(), "Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _pt_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _pt_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pt_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pt_project_id(auth_info, payload=None):
    auth_info = auth_info or {}
    pid = auth_info.get("project_id") or auth_info.get("projectId")
    if isinstance(payload, dict):
        pid = payload.get("project_id") or payload.get("projectId") or pid
    return pid


def _pt_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("error") or body.get("message")
        if err:
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _pt_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if inner is not None:
            return [inner] if isinstance(inner, dict) else []
        return [data]
    return []


def _pt_search_items(data):
    if not isinstance(data, dict):
        return []
    out = []
    stories = data.get("stories")
    if isinstance(stories, dict):
        for item in stories.get("stories") or []:
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("kind", "story")
                out.append(row)
    epics = data.get("epics")
    if isinstance(epics, dict):
        for item in epics.get("epics") or []:
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("kind", "epic")
                out.append(row)
    return out


def _pt_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _pt_auth(auth_info, json_body=(json_body is not None))
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
        return resp, body, resp.status_code, _pt_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _pt_paginate(path, base_url, auth_info, limit, timeout, verify_ssl, extra_params=None):
    root, err = _pt_root(base_url, auth_info)
    if err:
        return [], 400, err
    cap = _pt_cap(limit)
    records = []
    offset = 0
    status = 200
    msg = "ok"
    while len(records) < cap:
        params = dict(extra_params or {})
        params["limit"] = min(200, cap - len(records))
        params["offset"] = offset
        resp, body, status, msg = _pt_request("get", root + path, auth_info, params=params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return records[:cap], status, msg
        batch = _pt_items(body)
        records.extend(batch)
        returned_hdr = resp.headers.get("X-Tracker-Pagination-Returned") if resp is not None else None
        total_hdr = resp.headers.get("X-Tracker-Pagination-Total") if resp is not None else None
        returned = int(returned_hdr) if returned_hdr not in (None, "") else len(batch)
        total = int(total_hdr) if total_hdr not in (None, "") else (offset + returned)
        offset += returned
        if returned == 0 or offset >= total:
            break
    return records[:cap], status, msg
