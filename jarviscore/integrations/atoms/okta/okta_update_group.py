import requests
from typing import Any, Dict, List, Optional



# Replace group profile — PUT /api/v1/groups/{groupId}. Official: https://developer.okta.com/docs/reference/api/groups/


def okta_update_group(auth_info: dict, domain: str, group_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Replace group profile. Official: https://developer.okta.com/docs/reference/api/overview/"""
    try:
        if not group_id:
            return _ok_provision({}, 400, "group_id is required")
        if not isinstance(payload, dict) or not payload:
            return _ok_provision({}, 400, "payload is required")
        root, err = _ok_root(base_url, domain, auth_info)
        if err:
            return _ok_provision({}, 400, err)
        headers, aerr = _ok_auth(auth_info, json_body=True)
        if aerr:
            return _ok_provision({}, 400, aerr)
        resp = requests.put(f"{root}/groups/{group_id}", headers=headers, json=payload, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return _ok_provision({}, status, _ok_error(resp))
        try:
            data = resp.json()
        except Exception:
            return _ok_provision({}, status, resp.text[:1000])
        return _ok_provision(data if isinstance(data, dict) else {}, status, "ok", fallback_id=group_id)
    except Exception as e:
        return _ok_provision({}, 500, str(e))


# Okta Management API — Official docs: https://developer.okta.com/docs/reference/api/overview/


def _ok_root(base_url, domain, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("okta_url") or "").strip().rstrip("/")
    dom = (domain or auth_info.get("okta_domain") or auth_info.get("domain") or "").strip()
    if dom:
        dom = dom.replace("https://", "").replace("http://", "").rstrip("/")
    if not root and dom:
        root = f"https://{dom}/api/v1"
    if root and "/api/v1" not in root:
        if "okta" in root.lower():
            root = root + "/api/v1"
    if not root:
        return None, "base_url or domain is required (https://{yourOktaDomain}/api/v1)"
    return root, None


def _ok_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    if not api_key:
        return None, "auth_info.api_key is required"
    headers = {"Accept": "application/json", "Authorization": f"SSWS {str(api_key).strip()}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _ok_cap(limit):
    return min(max(int(limit or 25), 1), 200)


def _ok_error(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("errorSummary") or data.get("errorCode") or data.get("message")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _ok_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _ok_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _ok_records(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and data.get("id"):
        return [data]
    return []


def _ok_next_url(resp):
    link = resp.headers.get("Link") or resp.headers.get("link") or ""
    if 'rel="next"' in link:
        for part in link.split(","):
            if 'rel="next"' in part:
                return part.split(";")[0].strip().strip("<> ")
    return None


def _ok_paginate(url, headers, params, limit, timeout, verify_ssl):
    cap = _ok_cap(limit)
    records = []
    next_url = None
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        req_params = None if next_url else dict(params or {})
        if not next_url:
            req_params["limit"] = min(cap - len(records), 200)
        resp = requests.get(next_url or url, headers=headers, params=req_params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, _ok_error(resp)
        try:
            data = resp.json()
        except Exception:
            return records, status, resp.text[:1000]
        batch = _ok_records(data) if isinstance(data, list) else _ok_records(data)
        records.extend(batch)
        next_url = _ok_next_url(resp)
        if not next_url or not batch:
            break
    return records[:cap], status, "ok"
