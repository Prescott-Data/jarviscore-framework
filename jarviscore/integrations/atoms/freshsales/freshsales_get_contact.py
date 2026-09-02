import requests
from typing import Any, Dict, List, Optional

# Freshsales CRM API — https://developers.freshworks.com/crm/api/
_FS_API_SUFFIX = "/crm/sales/api"
_FS_AUTH_PREFIX = "Token "
_FS_AUTH_KV = "token" + "="


def freshsales_get_contact(auth_info: dict, contact_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """View a contact (GET .../contacts/{id}). response.contact. Freshworks Token auth scheme (Token + token= + api_key from Profile Settings > API Settings). Official: https://developers.freshworks.com/docs/api/crm/sales/"""
    try:
        if not contact_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "contact_id is required"}
        api, err = _fs_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _fs_sales_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        url = f"{api}/contacts/{str(contact_id).strip()}"
        resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _fs_entity_records(data, "contact")
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _fs_api_root(base_url: str):
    root = (base_url or "").rstrip("/")
    if not root:
        return None, "base_url is required (https://{domain}.myfreshworks.com/crm/sales/api)"
    if _FS_API_SUFFIX in root:
        return root, None
    if root.endswith("/api") and (_host_is(root, "freshsales.io", "myfreshworks.com")):
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
