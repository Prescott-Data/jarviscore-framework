import requests
from typing import Any, Dict, List, Optional

def workfront_update_task(auth_info: dict, task_id: str, name: str = '', limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """workfront REST: update task. Official: https://developer.adobe.com/workfront/api-explorer/"""
    try:
        root, err = _root(base_url, auth_info)
        if err: return _provision({}, 400, err)
        if not task_id: return _provision({}, 400, 'task_id is required')
        headers, aerr = _auth(auth_info)
        if aerr: return _provision({}, 401, aerr)
        headers['Content-Type'] = 'application/json'
        resp = requests.put(root + "/task/" + str(task_id), headers=headers, json={'name': name} if name else {}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _provision({}, resp.status_code, _err(resp))
        data = resp.json() if resp.content else {}
        obj = data.get("data") if isinstance(data, dict) else {}
        return _provision(obj if isinstance(obj, dict) else {}, resp.status_code, 'ok', fallback_id=task_id)
    except Exception as e: return _provision({}, 500, str(e))


# workfront REST API — Official: https://developer.adobe.com/workfront/api-explorer/


def _root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("base_url") or "https://example.my.workfront.com/attask/api/v15.0").strip().rstrip("/")
    if not root:
        return None, "base_url is required"
    return root, None


def _auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.api_key is required"
    tok = str(token).strip()
    return {"apiKey": tok, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}, None


def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("ID") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
