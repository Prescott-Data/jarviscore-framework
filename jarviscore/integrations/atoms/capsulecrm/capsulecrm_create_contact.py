import requests
from typing import Any, Dict, List, Optional

# Capsule CRM REST API v2 — https://developer.capsulecrm.com/
CAPSULE_API = "https://api.capsulecrm.com"


def capsulecrm_create_contact(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create Contact via Capsule CRM API. Official: https://developer.capsulecrm.com/v2/operations/Party"""
    try:
        if not payload:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        api = _capsule_api_root(base_url)
        headers, auth_err = _capsule_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        body = _capsule_party_body(payload, default_type="person")
        resp = _capsule_post_json(f"{api}/parties", headers, body, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _capsule_records_from(data, "parties", "party")
        prov = [_capsule_provision_id(records[0])] if records else []
        prov = [x for x in prov if x is not None]
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok", "provision_ids": prov}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _capsule_api_root(base_url):
    root = (base_url or CAPSULE_API).rstrip("/")
    if root.endswith("/api/v2"):
        return root
    if root.endswith("/api"):
        return root + "/v2"
    if "/api/v2" not in root:
        return root + "/api/v2"
    return root


def _capsule_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _capsule_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _capsule_post_json(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _capsule_put_json(url, headers, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _capsule_wrap(kind, payload):
    if not isinstance(payload, dict):
        return {kind: payload}
    if kind in payload:
        return payload
    return {kind: payload}


def _capsule_records_from(data, list_key, single_key):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    if single_key and isinstance(data.get(single_key), dict):
        return [data[single_key]]
    items = data.get(list_key)
    if isinstance(items, list):
        return items
    return [data]


def _capsule_batch_from(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("parties", "opportunities", "results"):
        if isinstance(data.get(key), list):
            return data[key]
    if isinstance(data.get("party"), dict):
        return [data["party"]]
    if isinstance(data.get("opportunity"), dict):
        return [data["opportunity"]]
    return []


def _capsule_paginate(url, headers, limit, timeout, verify_ssl, extra=None, party_type=None):
    records = []
    page = 1
    status = 0
    extra = extra or {}
    per_page = min(max(int(limit), 1), 100)
    want = party_type.lower() if party_type else None
    while len(records) < limit:
        params = {"page": page, "perPage": per_page}
        params.update(extra)
        resp = _capsule_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _capsule_batch_from(data)
        if not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                continue
            if want and (item.get("type") or "").lower() != want:
                continue
            records.append(item)
            if len(records) >= limit:
                break
        if len(batch) < params["perPage"]:
            break
        page += 1
        if page > 500:
            break
    return records[:limit], status, "ok"


def _capsule_party_body(payload, default_type=None):
    body = _capsule_wrap("party", payload)
    party = body.get("party")
    if isinstance(party, dict) and default_type and not party.get("type"):
        party = dict(party)
        party["type"] = default_type
        body["party"] = party
    return body


def _capsule_search(url, headers, query, limit, timeout, verify_ssl):
    records = []
    page = 1
    status = 0
    per_page = min(max(int(limit), 1), 100)
    while len(records) < limit:
        params = {"q": query, "page": page, "perPage": min(per_page, limit - len(records))}
        resp = _capsule_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = []
        if isinstance(data, dict):
            batch = data.get("parties") or data.get("results") or []
        elif isinstance(data, list):
            batch = data
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(batch) < params["perPage"]:
            break
        page += 1
        if page > 500:
            break
    return records[:limit], status, "ok"


def _capsule_provision_id(record):
    if not isinstance(record, dict):
        return None
    if record.get("id") is not None:
        return record.get("id")
    for key in ("party", "organisation", "opportunity"):
        val = record.get(key)
        if isinstance(val, dict) and val.get("id") is not None:
            return val.get("id")
    return None
