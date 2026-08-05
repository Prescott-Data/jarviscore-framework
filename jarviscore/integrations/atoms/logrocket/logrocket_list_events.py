import requests
from typing import Any, Dict, List, Optional

# LogRocket REST APIs — Official docs:
# User Identification https://docs.logrocket.com/docs/user-identification-api
# Audit Log https://docs.logrocket.com/docs/audit-log-api
# Highlights https://docs.logrocket.com/docs/session-highlights-api
# Data Export https://docs.logrocket.com/docs/data-export
LOGROCKET_API = "https://api.logrocket.com/v1"


def logrocket_list_events(auth_info: dict, org_id: str, app_id: str, limit: int = 25, cursor: str = "", timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List audit log entries. Official: https://docs.logrocket.com/docs/audit-log-api"""
    try:
        app_base, err = _lr_app_base(base_url, org_id, app_id, auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, aerr = _lr_headers(auth_info)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        params = {"limit": min(max(int(limit or 25), 1), 100)}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{app_base}/audit/logs/", headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        try:
            data = resp.json() if resp.text else {}
        except Exception:
            data = {}
        records = _lr_cap(_lr_records(data.get("logs") if isinstance(data, dict) else None), limit)
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _lr_org_app(org_id, app_id, auth_info):
    auth_info = auth_info or {}
    org = org_id or auth_info.get("org_id")
    app = app_id or auth_info.get("app_id")
    if not org or not app:
        return None, None, "org_id and app_id are required"
    return str(org), str(app), None


def _lr_app_base(base_url, org_id, app_id, auth_info):
    org, app, err = _lr_org_app(org_id, app_id, auth_info)
    if err:
        return None, err
    root = (base_url or LOGROCKET_API).rstrip("/")
    if "/orgs/" in root and "/apps/" in root:
        return root, None
    return f"{root}/orgs/{org}/apps/{app}", None


def _lr_headers(auth_info, json_body=False):
    auth_info = auth_info or {}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info.api_key is required"
    val = str(key).strip()
    if val.lower().startswith("bearer "):
        val = val[7:].strip()
    prefix = "token "
    auth = val if val.lower().startswith(prefix) else prefix + val
    headers = {"Accept": "application/json", "Authorization": auth}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _lr_records(items):
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    if isinstance(items, dict) and items.get("id") is not None:
        return [items]
    return []


def _lr_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 100)
    return records[:cap]


def _lr_provision(data, status, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    obj_id = obj.get("id") or obj.get("requestID") or obj.get("userID") or fallback_id
    ids = [obj_id] if obj_id not in (None, "") else []
    records = [obj] if obj else ([{"id": obj_id}] if obj_id else [])
    return {
        "records": records,
        "data_count": len(records),
        "status": status,
        "message": "ok" if status < 400 else str(obj)[:1000],
        "provision_ids": ids,
    }
