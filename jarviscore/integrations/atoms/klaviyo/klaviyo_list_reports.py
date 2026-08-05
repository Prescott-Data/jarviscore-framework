import requests
from typing import Any, Dict, List, Optional

# Klaviyo API — https://developers.klaviyo.com/en/reference/get_events
KLAVIYO_API = "https://a.klaviyo.com"
KL_REVISION = "2024-10-15"


def klaviyo_list_reports(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List Klaviyo metrics (catalog report maps to metric). Official: https://developers.klaviyo.com/en/reference/get_metrics"""
    try:
        api, err = _kv_api_root(base_url)
        if err: return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _kv_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        records, status, message = _kv_paginate(f"{api}/api/metrics/", headers, limit, timeout, verify_ssl)
        return {"records": records, "data_count": len(records), "status": status, "message": message}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _kv_api_root(base_url):
    root = (base_url or KLAVIYO_API).rstrip("/")
    if "klaviyo.com" not in root:
        return None, "base_url must be https://a.klaviyo.com"
    return root, None


def _kv_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "revision": KL_REVISION}
    if json_body:
        headers["Content-Type"] = "application/json"
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info requires api_key"
    k = str(key).strip()
    headers["Authorization"] = k if k.lower().startswith("klaviyo-api-key ") else f"Klaviyo-API-Key {k}"
    return headers, None


def _kv_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _kv_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _kv_jsonapi_records(data):
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            return [d]
    return []


def _kv_next_url(data):
    if isinstance(data, dict):
        links = data.get("links") or {}
        nxt = links.get("next") if isinstance(links, dict) else None
        if isinstance(nxt, str) and nxt.startswith("http"):
            return nxt
    return None


def _kv_paginate(url, headers, limit, timeout, verify_ssl):
    records = []
    status = 0
    cap = min(max(int(limit or 25), 1), 200)
    next_url = url
    pages = 0
    while len(records) < cap and next_url and pages < 100:
        pages += 1
        resp = _kv_get(next_url, headers, None if pages > 1 else {"page[size]": min(cap - len(records), 200)}, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        for item in _kv_jsonapi_records(data):
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        next_url = _kv_next_url(data)
    return records[:cap], status, "ok"


def _kv_provision_id(data):
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, dict) and d.get("id"):
            return [d["id"]]
    return []
