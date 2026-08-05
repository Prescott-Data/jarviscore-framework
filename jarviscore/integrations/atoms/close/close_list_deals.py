import requests
from typing import Any, Dict, List, Optional

# Close CRM REST API v1 — https://developer.close.com/
CLOSE_API = "https://api.close.com/api/v1"


def close_list_deals(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List opportunities (deals) from Close CRM. HTTP Basic API key (username, empty password). Official: https://developer.close.com/"""
    try:
        api = _close_api_root(base_url)
        headers, basic, auth_err = _close_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        records, status, message = _close_paginate(f"{api}/opportunity/", headers, basic, limit, timeout, verify_ssl)
        return {"records": records, "data_count": len(records), "status": status, "message": message}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _close_api_root(base_url):
    root = (base_url or CLOSE_API).rstrip("/")
    if root.endswith("/api/v1"):
        return root
    if root.endswith("/api"):
        return root + "/v1"
    if "api.close.com" in root and "/api/v1" not in root:
        return root + "/api/v1" if not root.endswith("/v1") else root
    if "/api/v1" not in root:
        return root + "/api/v1"
    return root


def _close_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    api_key = auth_info.get("api_key")
    if api_key:
        token = str(api_key).strip()
        if token.lower().startswith("bearer "):
            headers["Authorization"] = token
            return headers, None, None
        return headers, (token, ""), None
    return None, None, "auth_info requires api_key (HTTP Basic, empty password)"


def _close_get(url, headers, basic, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, auth=basic, params=params, timeout=timeout, verify=verify_ssl)


def _close_post_json(url, headers, basic, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _close_put_json(url, headers, basic, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _close_records_from(data, single=False):
    if single:
        if isinstance(data, dict):
            if isinstance(data.get("data"), dict):
                return [data["data"]]
            if data.get("id") is not None:
                return [data]
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("data")
        if isinstance(items, list):
            return items
    return []


def _close_paginate(url, headers, basic, limit, timeout, verify_ssl, extra=None):
    records = []
    skip = 0
    status = 0
    extra = extra or {}
    page_size = min(max(int(limit), 1), 100)
    while len(records) < limit:
        params = {"_limit": min(page_size, limit - len(records)), "_skip": skip}
        params.update(extra)
        resp = _close_get(url, headers, basic, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _close_records_from(data)
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        has_more = isinstance(data, dict) and data.get("has_more")
        skip += len(batch)
        if not has_more or len(batch) < params["_limit"]:
            break
        if skip > 50000:
            break
    return records[:limit], status, "ok"


def _close_provision_id(record):
    if isinstance(record, dict) and record.get("id") is not None:
        return record.get("id")
    return None


def _close_search_query(query, limit):
    return {
        "query": {
            "type": "and",
            "queries": [
                {"type": "object_type", "object_type": "lead"},
                {"type": "text", "value": query, "mode": "full_words"},
            ],
        },
        "_limit": min(max(int(limit), 1), 100),
    }
