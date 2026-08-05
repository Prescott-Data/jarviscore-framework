import requests
from typing import Any, Dict, List, Optional

# Insightly API v3.1 — https://api.na1.insightly.com/v3.1/Help
INSIGHTLY_API = "https://api.na1.insightly.com/v3.1"


def insightly_search_records(auth_info: dict, query: str, field_name: str = "EMAIL_ADDRESS", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search Insightly contacts via Contacts/Search. Official: https://api.na1.insightly.com/v3.1/Help"""
    try:
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
        api, err = _in_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _in_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        params = {"field_name": field_name, "field_value": query, "top": min(max(limit, 1), 500)}
        resp = _in_get(f"{api}/Contacts/Search", headers, basic, params, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        batch = resp.json() if resp.text else []
        records = [item for item in (batch if isinstance(batch, list) else [batch]) if isinstance(item, dict)][:limit]
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _in_api_root(base_url):
    root = (base_url or INSIGHTLY_API).rstrip("/")
    if "/v3.1" not in root:
        if "insightly.com" in root:
            root = root + "/v3.1" if not root.endswith("/v3") else root + ".1"
        else:
            return None, "base_url must be https://api.{pod}.insightly.com/v3.1"
    return root, None


def _in_auth(auth_info):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if not api_key:
        return headers, None, "auth_info requires api_key"
    return headers, (str(api_key).strip(), ""), None


def _in_get(url, headers, basic, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, auth=basic, params=params, timeout=timeout, verify=verify_ssl)


def _in_post(url, headers, basic, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _in_put(url, headers, basic, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _in_paginate(url, headers, basic, limit, timeout, verify_ssl):
    records = []
    skip = 0
    status = 0
    cap = min(max(int(limit or 25), 1), 500)
    while len(records) < cap:
        top = min(cap - len(records), 500)
        resp = _in_get(url, headers, basic, {"top": top, "skip": skip}, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        batch = resp.json() if resp.text else []
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        if len(batch) < top:
            break
        skip += len(batch)
        if skip > 50000:
            break
    return records[:cap], status, "ok"


def _in_single(data):
    if isinstance(data, dict) and data.get("RECORD_ID") is not None:
        return [data]
    if isinstance(data, dict) and data.get("CONTACT_ID") is not None:
        return [data]
    if isinstance(data, dict) and data.get("ORGANISATION_ID") is not None:
        return [data]
    if isinstance(data, dict) and data.get("OPPORTUNITY_ID") is not None:
        return [data]
    return []


def _in_provision_id(data):
    if not isinstance(data, dict):
        return []
    for key in ("CONTACT_ID", "ORGANISATION_ID", "OPPORTUNITY_ID", "RECORD_ID"):
        if data.get(key) not in (None, ""):
            return [data[key]]
    return []
