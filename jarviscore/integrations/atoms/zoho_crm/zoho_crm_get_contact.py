import requests
from typing import Any, Dict, List, Optional


def zoho_crm_get_contact(auth_info: dict, contact_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """zoho_crm REST: get contact. Official: https://www.zoho.com/crm/developer/docs/api/v2/"""
    try:
        if not contact_id:
            return _dataset([], 400, "contact_id is required")
        root, err = _root(base_url, auth_info)
        if err:
            return _dataset([], 400, err)
        headers, aerr = _auth(auth_info)
        if aerr:
            return _dataset([], 401, aerr)
        resp = requests.get(root + "/Contacts/" + str(contact_id), headers=headers, timeout=timeout, verify=verify_ssl)
        if resp.status_code == 204:
            return _dataset([], 200, "ok")
        if resp.status_code >= 400:
            return _dataset([], resp.status_code, _err(resp))
        data = resp.json() if resp.content else {}
        return _dataset(_records(data), resp.status_code, "ok")
    except Exception as e:
        return _dataset([], 500, str(e))


# Zoho CRM REST API v2 — Official: https://www.zoho.com/crm/developer/docs/api/v2/


def _root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("base_url") or "https://www.zohoapis.com/crm/v2").strip().rstrip("/")
    if not root:
        return None, "base_url is required"
    return root, None


def _auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    headers = {"Authorization": "Zoho-oauthtoken " + str(token).strip(), "Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("code")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or "HTTP " + str(resp.status_code))[:1000]


def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _records(data):
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list):
            return [x for x in rows if isinstance(x, dict)]
    return []
