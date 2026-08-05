import requests
from typing import Any, Dict, List, Optional

# Freshsales CRM API — https://developers.freshworks.com/crm/api/
_FS_API_SUFFIX = "/crm/sales/api"
_FS_AUTH_PREFIX = "Token "
_FS_AUTH_KV = "token" + "="


def freshsales_search_records(auth_info: dict, query: str, include: str = "contact,sales_account,deal", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search CRM records (GET /api/search?q=&include=). Returns array of {id,type,name,...}. Freshworks Token auth scheme (Token + token= + api_key from Profile Settings > API Settings). Official: https://developers.freshworks.com/docs/api/crm/sales/"""
    try:
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
        api, err = _fs_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _fs_sales_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        per_page = min(max(int(limit or 25), 1), 100)
        params = {"q": query, "include": include or "contact,sales_account,deal", "per_page": per_page}
        resp = requests.get(f"{api}/search", headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        data = resp.json() if resp.text else []
        records = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        return {"records": records[:per_page], "data_count": len(records[:per_page]), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _fs_api_root(base_url: str):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required (https://{domain}.myfreshworks.com/crm/sales/api)"
    if _FS_API_SUFFIX in root:
        return root, None
    if root.endswith("/api") and ("freshsales.io" in root or "myfreshworks.com" in root):
        return root, None
    return None, "base_url must be the Freshsales API root (https://{domain}.myfreshworks.com/crm/sales/api)"


def _fs_sales_auth(auth_info, json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info requires api_key or access_token"
    tok = str(token).strip()
    _prefix = "Token "
    _kv = "token" + "="
    if tok.lower().startswith(_prefix.lower() + _kv):
        headers["Authorization"] = tok
    elif tok.lower().startswith("bearer "):
        headers["Authorization"] = _prefix + _kv + tok[7:].strip()
    else:
        headers["Authorization"] = _prefix + _kv + tok
    return headers, None


def _fs_entity_records(data, entity_key):
    if isinstance(data, dict):
        entity = data.get(entity_key)
        if isinstance(entity, dict):
            return [entity]
        if isinstance(entity, list):
            return [item for item in entity if isinstance(item, dict)]
    return []


def _fs_list_batch(data, collection_key):
    if isinstance(data, dict):
        batch = data.get(collection_key)
        if isinstance(batch, list):
            return [item for item in batch if isinstance(item, dict)]
    return []


def _fs_provision_id(data, entity_key):
    recs = _fs_entity_records(data, entity_key)
    if recs and recs[0].get("id") not in (None, ""):
        return [str(recs[0]["id"])]
    return []


def _fs_paginate_view(url, headers, collection_key, limit, timeout, verify_ssl):
    records = []
    cap = min(max(int(limit or 25), 1), 1000)
    page = 1
    status = 0
    while len(records) < cap and page <= 100:
        per_page = min(cap - len(records), 100)
        params = {"page": page, "per_page": per_page}
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _fs_list_batch(data, collection_key)
        for item in batch:
            records.append(item)
            if len(records) >= cap:
                return records[:cap], status, "ok"
        if not batch or len(batch) < per_page:
            break
        page += 1
    return records[:cap], status, "ok"
