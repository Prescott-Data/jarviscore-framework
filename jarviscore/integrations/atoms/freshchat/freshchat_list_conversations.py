import requests
from typing import Any, Dict, List, Optional


def freshchat_list_conversations(auth_info: dict, user_id: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List conversations for a user (GET .../users/{userId}/conversations). Response.conversations[]. Bearer API token from Admin > API Tokens. Base URL: https://{domain}.freshchat.com/v2. Official: https://developers.freshchat.com/api/"""
    try:
        if not user_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "user_id is required"}
        api, err = _fc_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _fc_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        url = f"{api}/users/{str(user_id).strip()}/conversations"
        resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _fc_list_batch(data, "conversations")
        cap = min(max(int(limit or 25), 1), 1000)
        records = records[:cap]
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}


# Freshchat API v2 — https://developers.freshchat.com/api/


def _fc_api_root(base_url: str):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required (https://{domain}.freshchat.com/v2)"
    if "freshchat.com" not in root:
        return None, "base_url must be the Freshchat API v2 root (https://{domain}.freshchat.com/v2)"
    if not root.endswith("/v2"):
        root = root + "/v2"
    return root, None


def _fc_auth(auth_info, json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info requires access_token or api_key"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _fc_entity_record(data):
    if isinstance(data, dict):
        if data.get("conversation_id") not in (None, ""):
            return [data]
        if data.get("id") not in (None, ""):
            return [data]
    return []


def _fc_provision_id(data):
    if not isinstance(data, dict):
        return []
    for key in ("conversation_id", "id"):
        if data.get(key) not in (None, ""):
            return [str(data[key])]
    return []


def _fc_list_batch(data, collection_key):
    if not isinstance(data, dict):
        return []
    batch = data.get(collection_key)
    if not isinstance(batch, list):
        return []
    return [item for item in batch if isinstance(item, dict)]


def _fc_paginate(url, headers, collection_key, limit, timeout, verify_ssl, extra_params=None):
    records = []
    cap = min(max(int(limit or 25), 1), 1000)
    page = 1
    total_pages = 1
    status = 0
    while len(records) < cap and page <= total_pages and page <= 100:
        per_page = min(cap - len(records), 50)
        params = dict(extra_params or {})
        params["page"] = page
        params["items_per_page"] = per_page
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _fc_list_batch(data, collection_key)
        for item in batch:
            records.append(item)
            if len(records) >= cap:
                return records[:cap], status, "ok"
        pagination = data.get("pagination") if isinstance(data, dict) else {}
        if isinstance(pagination, dict) and pagination.get("total_pages"):
            total_pages = int(pagination.get("total_pages") or page)
        else:
            total_pages = page
        if len(batch) < per_page or page >= total_pages:
            break
        page += 1
    return records[:cap], status, "ok"
