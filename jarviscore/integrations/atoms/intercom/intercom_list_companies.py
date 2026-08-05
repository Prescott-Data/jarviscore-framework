import requests
from typing import Any, Dict, List, Optional

# Intercom REST API — https://developers.intercom.com/docs/references/rest-api/api.intercom.io/contacts
INTERCOM_API = "https://api.intercom.io"


def intercom_list_companies(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List Intercom companies. Official: https://developers.intercom.com/docs/references/rest-api/api.intercom.io/companies"""
    try:
        api, err = _ic_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _ic_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        records, status, message = _ic_paginate(f"{api}/companies", headers, limit, timeout, verify_ssl)
        return {"records": records, "data_count": len(records), "status": status, "message": message}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _ic_api_root(base_url):
    root = (base_url or INTERCOM_API).rstrip("/")
    if "intercom.io" not in root:
        return None, "base_url must be https://api.intercom.io"
    return root, None


def _ic_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "Intercom-Version": "2.11"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _ic_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _ic_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _ic_put(url, headers, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _ic_paginate(url, headers, limit, timeout, verify_ssl):
    records = []
    starting_after = None
    status = 0
    cap = min(max(int(limit or 25), 1), 150)
    pages = 0
    while len(records) < cap and pages < 100:
        pages += 1
        params = {"per_page": min(cap - len(records), 150)}
        if starting_after:
            params["starting_after"] = starting_after
        resp = _ic_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = data.get("data") if isinstance(data, dict) else []
        if not isinstance(batch, list):
            batch = []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        pages_obj = data.get("pages") if isinstance(data, dict) else {}
        nxt = pages_obj.get("next") if isinstance(pages_obj, dict) else {}
        starting_after = nxt.get("starting_after") if isinstance(nxt, dict) else None
        if not starting_after or not batch:
            break
    return records[:cap], status, "ok"


def _ic_single(data):
    if isinstance(data, dict) and data.get("id") is not None:
        return [data]
    return []


def _ic_provision_id(data):
    recs = _ic_single(data)
    if recs:
        return [recs[0]["id"]]
    return []
