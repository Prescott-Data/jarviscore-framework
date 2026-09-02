import requests
from typing import Any, Dict, List, Optional

# Nifty REST API — Official docs:
# https://developers.niftypm.com/operation/operation-projectapicontroller_getprojectbyid


NIFTY_API = "https://openapi.niftypm.com/api/v1.0"



def nifty_get_project(auth_info: dict, project_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get project by ID. Official: https://developers.niftypm.com/operation/operation-projectapicontroller_getprojectbyid"""
    try:
        if not project_id:
            return _nf_dataset([], 400, "project_id is required")
        root, err = _nf_root(base_url)
        if err:
            return _nf_dataset([], 400, err)
        headers, aerr = _nf_auth(auth_info)
        if aerr:
            return _nf_dataset([], 401, aerr)
        resp = requests.get(f"{root}/projects/{project_id}", headers=headers, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return _nf_dataset([], resp.status_code, _nf_error(resp))
        try:
            data = resp.json()
        except Exception:
            return _nf_dataset([], resp.status_code, resp.text[:1000])
        records = [data] if isinstance(data, dict) else []
        return _nf_dataset(records, resp.status_code, "ok")
    except Exception as e:
        return _nf_dataset([], 500, str(e))



def _nf_root(base_url):
    root = (base_url or NIFTY_API).rstrip("/")
    if not _host_is(root, "niftypm.com"):
        return None, "base_url must be https://openapi.niftypm.com/api/v1.0"
    if not root.endswith("/api/v1.0"):
        if "/" not in root.split("://", 1)[-1]:
            root = root + "/api/v1.0"
    return root, None


def _nf_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {str(token).strip()}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _nf_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _nf_error(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error") or data.get("detail")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _nf_form_payload(payload):
    body = payload if isinstance(payload, dict) else {}
    form = {}
    for key, val in body.items():
        if val in (None, ""):
            continue
        if isinstance(val, bool):
            form[key] = "true" if val else "false"
        elif isinstance(val, (list, dict)):
            import json
            form[key] = json.dumps(val)
        else:
            form[key] = str(val)
    return form


def _nf_provision_id(data, fallback=None):
    if isinstance(data, dict):
        for key in ("id", "task_id", "project_id"):
            if data.get(key) not in (None, ""):
                return data.get(key)
    return fallback


def _nf_dataset(records, status, msg):
    return {"records": records, "data_count": len(records), "status": status, "message": msg}


def _nf_provision(records, status, msg, provision_ids):
    return {"records": records, "data_count": len(records), "status": status, "message": msg, "provision_ids": provision_ids or []}


def _nf_paginate(url, headers, base_params, items_key, limit, timeout, verify_ssl):
    cap = _nf_cap(limit)
    offset = int((base_params or {}).get("offset") or 0)
    records = []
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        params = dict(base_params or {})
        params["limit"] = min(cap - len(records), 100)
        params["offset"] = offset
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, _nf_error(resp)
        try:
            data = resp.json()
        except Exception:
            return records, status, resp.text[:1000]
        batch = []
        if isinstance(data, dict):
            val = data.get(items_key)
            if isinstance(val, list):
                batch = [x for x in val if isinstance(x, dict)]
        records.extend(batch)
        if not batch or not (isinstance(data, dict) and data.get("hasMore")):
            break
        offset += len(batch)
    return records[:cap], status, "ok"


def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or "").strip()
    if "://" not in u:
        u = "https://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)
