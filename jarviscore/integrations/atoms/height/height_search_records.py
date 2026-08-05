import requests
from typing import Any, Dict, List, Optional

# Height REST API — https://height.app/api-docs
HEIGHT_API = "https://api.height.app"


def height_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search Height tasks via GET /tasks query filter. Official: https://height.app/api-docs"""
    try:
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
        api, err = _height_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _height_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        records, status, message = _height_paginate(f"{api}/tasks", headers, min(limit * 5, 100), timeout, verify_ssl, {"query": query})
        if message != "ok":
            return {"records": records, "data_count": len(records), "status": status, "message": message}
        needle = query.lower()
        matched = [r for r in records if isinstance(r, dict) and needle in str(r.get("name", r.get("title", ""))).lower()][:limit]
        return {"records": matched, "data_count": len(matched), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _height_api_root(base_url):
    root = (base_url or HEIGHT_API).rstrip("/")
    if "height.app" not in root:
        return None, "base_url must be https://api.height.app"
    return root, None


def _height_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    api_key = auth_info.get("api_key")
    if not api_key:
        return None, "auth_info requires api_key"
    key = str(api_key).strip()
    if key.lower().startswith("api-key "):
        headers["Authorization"] = key
    else:
        headers["Authorization"] = f"api-key {key}"
    return headers, None


def _height_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _height_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _height_patch(url, headers, body, timeout, verify_ssl):
    return requests.patch(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _height_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "data", "items", "results"):
            batch = data.get(key)
            if isinstance(batch, list):
                return batch
    return []


def _height_paginate(url, headers, limit, timeout, verify_ssl, extra_params=None):
    params = dict(extra_params or {})
    cap = min(max(int(limit or 25), 1), 100)
    params.setdefault("limit", cap)
    resp = _height_get(url, headers, params, timeout, verify_ssl)
    status = resp.status_code
    if status >= 400:
        return [], status, resp.text[:1000]
    batch = _height_items(resp.json() if resp.text else {})
    records = [item for item in batch if isinstance(item, dict)][:cap]
    return records, status, "ok"


def _height_single(data):
    if isinstance(data, dict):
        if isinstance(data.get("data"), dict):
            return [data["data"]]
        if data.get("id") is not None:
            return [data]
    return []


def _height_provision_id(data):
    recs = _height_single(data)
    if recs and recs[0].get("id") not in (None, ""):
        return [recs[0]["id"]]
    return []


def _height_list_id(auth_info, payload, project_id=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    lid = (
        project_id
        or payload.get("project_id")
        or payload.get("list_id")
        or auth_info.get("project_id")
        or auth_info.get("list_id")
    )
    return str(lid).strip() if lid not in (None, "") else None
