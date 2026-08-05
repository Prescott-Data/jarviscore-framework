import requests
from typing import Any, Dict, List, Optional


def zoho_crm_create_deal(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """zoho_crm REST: create deal. Official: https://www.zoho.com/crm/developer/docs/api/v2/"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _provision({}, 400, "payload is required (Deal_Name and Stage are mandatory for Zoho CRM Deals)")
        root, err = _root(base_url, auth_info)
        if err:
            return _provision({}, 400, err)
        headers, aerr = _auth(auth_info, json_body=True)
        if aerr:
            return _provision({}, 401, aerr)
        resp = requests.post(root + "/Deals", headers=headers, json={"data": [payload]}, timeout=timeout, verify=verify_ssl)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            return _provision({}, resp.status_code, _err(resp))
        return _provision(data if isinstance(data, dict) else {}, resp.status_code, "ok")
    except Exception as e:
        return _provision({}, 500, str(e))


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


def _cap(limit):
    return min(max(int(limit or 25), 1), 200)


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


def _provision(data, status, msg, fallback_id=None):
    rec = {}
    pid = fallback_id
    if isinstance(data, dict):
        rows = data.get("data")
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            row = rows[0]
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            pid = (details.get("id") if isinstance(details, dict) else None) or row.get("id") or fallback_id
            rec = details or row
    ids = [pid] if pid not in (None, "") else []
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}
