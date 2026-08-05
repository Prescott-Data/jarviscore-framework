import requests
from typing import Any, Dict, List, Optional

# Zoho Desk API v1 — Official: https://desk.zoho.com/DeskAPIDocument#list-contacts
# Auth: Authorization: Zoho-oauthtoken {access_token}. orgId header optional (OAuth token implies org).
ZD_API = "https://desk.zoho.com/api/v1"


def zoho_desk_list_contacts(auth_info: dict, org_id: str = "", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """zoho_desk API: list contacts. Official: https://desk.zoho.com/DeskAPIDocument"""
    try:
        root, err = _zd_root(base_url, auth_info)
        if err:
            return _zd_dataset([], 400, err)
        headers, aerr = _zd_headers(auth_info, org_id)
        if aerr:
            return _zd_dataset([], 401, aerr)
        records, status, msg = _zd_paginate(f"{root}/contacts", headers, limit, timeout, verify_ssl)
        return _zd_dataset(records, status, msg)
    except Exception as e:
        return _zd_dataset([], 500, str(e))



def _zd_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("base_url") or ZD_API).strip().rstrip("/")
    if "zoho." not in root:
        return None, "base_url must be https://desk.zoho.com/api/v1"
    return root, None


def _zd_headers(auth_info, org_id=""):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    tok = str(token).strip()
    if tok.lower().startswith("zoho-oauthtoken "):
        auth = tok
    elif tok.lower().startswith("bearer "):
        auth = "Zoho-oauthtoken " + tok.split(" ", 1)[1]
    else:
        auth = "Zoho-oauthtoken " + tok
    headers = {"Authorization": auth, "Content-Type": "application/json", "Accept": "application/json"}
    if org_id:
        headers["orgId"] = str(org_id)
    return headers, None


def _zd_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _zd_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _zd_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _zd_paginate(url, headers, limit, timeout, verify_ssl, extra=None):
    records: List[Dict[str, Any]] = []
    cap = min(max(int(limit or 25), 1), 100)
    frm = 1
    status = 0
    while len(records) < cap:
        params = dict(extra or {})
        params["from"] = frm
        params["limit"] = min(cap - len(records), 100)
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status == 204:
            break
        if status >= 400:
            return records, status, _zd_err(resp)
        data = resp.json() if resp.content else {}
        batch = data.get("data") if isinstance(data, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        records.extend([r for r in batch if isinstance(r, dict)])
        if len(batch) < params["limit"]:
            break
        frm += len(batch)
    return records[:cap], status, "ok"
