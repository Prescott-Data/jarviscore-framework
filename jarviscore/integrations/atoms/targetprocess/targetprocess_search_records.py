import requests
from typing import Any, Dict, List, Optional

# Targetprocess REST API — Official: https://dev.targetprocess.com/docs/REST%20API

_TP_ROOT = "https://example.tpondemand.com/api/v1"


def targetprocess_search_records(auth_info: dict, query: str, resource: str = "projects", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Targetprocess REST: search projects or user stories. Official: https://dev.targetprocess.com/docs/REST%20API"""
    try:
        root, err = _tp_root(base_url, auth_info)
        if err:
            return _tp_dataset([], 400, err)
        if not query:
            return _tp_dataset([], 400, "query is required")
        path = "Projects" if resource in ("projects", "project") else "UserStories"
        params = {"where": f"Name.Contains('{query.replace(chr(39), '')}')"}
        records, status, msg = _tp_paginate(f"{root}/{path}", auth_info, params, limit, timeout, verify_ssl)
        if status == 401:
            return _tp_dataset([], status, msg)
        matched = [r for r in records if _tp_match(r, query)]
        return _tp_dataset(matched, status, "ok")
    except Exception as e:
        return _tp_dataset([], 500, str(e))



def _tp_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("targetprocess_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://{account}.tpondemand.com/api/v1)"
    if not root.endswith("/api/v1"):
        root = root + "/api/v1" if "/api/" not in root else root
    return root, None


def _tp_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    # Targetprocess auth = access_token query param (not a Bearer header); appended at call sites.
    return headers, None


def _tp_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _tp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _tp_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("Id") or obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _tp_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            return str(data.get("ErrorMessage") or data)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _tp_items(data):
    if isinstance(data, dict):
        items = data.get("Items")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _tp_paginate(url, auth_info, params, limit, timeout, verify_ssl):
    headers, err = _tp_auth(auth_info)
    if err:
        return [], 401, err
    cap = _tp_cap(limit)
    records = []
    req_params = dict(params or {})
    req_params.setdefault("take", min(cap, 1000))
    req_params["access_token"] = str((auth_info or {}).get("access_token") or "").strip()
    req_params.setdefault("format", "json")
    skip = 0
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        req_params["skip"] = skip
        resp = requests.get(url, headers=headers, params=req_params, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return records, resp.status_code, _tp_err(resp)
        data = resp.json() if resp.content else {}
        batch = _tp_items(data)
        records.extend(batch)
        if len(batch) < req_params.get("take", 25):
            break
        skip += len(batch)
    return records[:cap], 200, "ok"


def _tp_match(record, query):
    q = str(query).lower()
    for key in ("Id", "id", "Name", "name"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
