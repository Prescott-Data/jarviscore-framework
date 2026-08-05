import requests
from typing import Any, Dict, List, Optional

# Zoho Desk API v1 — Official: https://desk.zoho.com/DeskAPIDocument#update-department
# Auth: Authorization: Zoho-oauthtoken {access_token}. orgId header optional (OAuth token implies org).
ZD_API = "https://desk.zoho.com/api/v1"


def zoho_desk_update_department(auth_info: dict, department_id: str, name: str = "", description: str = "", org_id: str = "", timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """zoho_desk API: update department. Official: https://desk.zoho.com/DeskAPIDocument"""
    try:
        if not department_id:
            return _zd_provision({}, 400, "department_id is required")
        root, err = _zd_root(base_url, auth_info)
        if err:
            return _zd_provision({}, 400, err)
        headers, aerr = _zd_headers(auth_info, org_id)
        if aerr:
            return _zd_provision({}, 401, aerr)
        body: Dict[str, Any] = {}
        if name:
            body["name"] = name
        if description:
            body["description"] = description
        resp = requests.patch(f"{root}/departments/{department_id}", headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return _zd_provision({}, resp.status_code, _zd_err(resp))
        data = resp.json() if resp.content else {}
        return _zd_provision(data if isinstance(data, dict) else {}, resp.status_code, "ok", fallback_id=department_id)
    except Exception as e:
        return _zd_provision({}, 500, str(e))



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
