import requests
from typing import Any, Dict, List, Optional

# Keap REST API v2 — https://developer.keap.com/docs/restv2/
KEAP_API = "https://api.infusionsoft.com/crm/rest/v2"


def keap_create_deal(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create Keap deal. Official: https://developer.keap.com/docs/restv2/"""
    try:
        if not payload: return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        api, err = _kp_api_root(base_url)
        if err: return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _kp_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err, "provision_ids": []}
        resp = _kp_post(f"{api}/opportunities", headers, payload, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _kp_single(data)
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok", "provision_ids": _kp_provision_id(data)}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _kp_api_root(base_url):
    root = (base_url or KEAP_API).rstrip("/")
    if "/rest/v2" not in root:
        if _host_is(root, "infusionsoft.com", "keap.com"):
            root = root + "/crm/rest/v2" if "/crm" not in root else root + "/rest/v2" if not root.endswith("/v2") else root
        else:
            return None, "base_url must be https://api.infusionsoft.com/crm/rest/v2"
    return root, None


def _kp_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _kp_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _kp_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _kp_patch(url, headers, body, timeout, verify_ssl):
    return requests.patch(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _kp_paginate(url, headers, limit, timeout, verify_ssl, extra=None):
    records = []
    token = None
    status = 0
    cap = min(max(int(limit or 25), 1), 1000)
    extra = dict(extra or {})
    pages = 0
    while len(records) < cap and pages < 100:
        pages += 1
        params = {"page_size": min(cap - len(records), 1000)}
        params.update(extra)
        if token:
            params["page_token"] = token
        resp = _kp_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = data.get("contacts") or data.get("companies") or data.get("opportunities") or data.get("records") or []
        if isinstance(data, list):
            batch = data
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        token = data.get("next_page_token") if isinstance(data, dict) else None
        if not token or not batch:
            break
    return records[:cap], status, "ok"


def _kp_single(data):
    if isinstance(data, dict) and data.get("id") is not None:
        return [data]
    return []


def _kp_provision_id(data):
    recs = _kp_single(data)
    if recs:
        return [recs[0]["id"]]
    return []


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
