import requests
from typing import Any, Dict, List, Optional

# Freedcamp Public API — https://freedcamp.com/help_/tutorials/wiki/wiki_public/view/DFaab
_FC_API_ROOT = "https://freedcamp.com/api/v1"


def freedcamp_list_tasks(auth_info: dict, project_id: Optional[str] = None, limit: int = 200, offset: int = 0, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List tasks (optional project_id, limit/offset max 200). Official: https://freedcamp.com/help_/tutorials/wiki/wiki_public/view/DFaab#/tasks"""
    try:
        api, err = _fc_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth, auth_err = _fc_auth_params(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        params = dict(auth)
        params.update({"limit": min(max(int(limit or 200), 1), 200), "offset": max(int(offset or 0), 0)})
        if project_id:
            params["project_id"] = project_id
        resp = requests.get(f"{api}/tasks", headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        body = resp.json() if resp.text else {}
        records = body.get("tasks") if isinstance(body, dict) and isinstance(body.get("tasks"), list) else _fc_records(body)
        records = [x for x in records if isinstance(x, dict)]
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _fc_api_root(base_url: str):
    root = (base_url or _FC_API_ROOT).rstrip("/")
    if not root.endswith("/api/v1"):
        if _host_is(root, "freedcamp.com"):
            root = root if root.endswith("/api/v1") else f"{root.rstrip('/')}/api/v1"
        else:
            return None, "base_url must be Freedcamp API root (https://freedcamp.com/api/v1)"
    return root, None


def _fc_auth_params(auth_info: Optional[Dict[str, Any]]) -> tuple:
    auth_info = auth_info or {}
    headers: Dict[str, str] = {"Accept": "application/json"}
    params: Dict[str, Any] = {}
    api_key = auth_info.get("username")
    api_secret = auth_info.get("password")
    if not api_key:
        return None, None, "auth_info requires username (api_key)"
    params["api_key"] = str(api_key).strip()
    headers["X-API-KEY"] = str(api_key).strip()
    if api_secret:
        import time as _time
        import hmac as _hmac
        import hashlib as _hashlib
        ts = str(int(_time.time()))
        raw = str(api_key).strip() + ts
        digest = _hmac.new(str(api_secret).encode("utf-8"), raw.encode("utf-8"), _hashlib.sha1).hexdigest()
        params["timestamp"] = ts
        params["hash"] = digest
    return headers, params, None


def _fc_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if isinstance(inner, dict):
            return [inner]
        if any(k in data for k in ("id", "project_id", "task_id", "title")):
            return [data]
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    return []


def _fc_provision(data: Any, status: int) -> Dict[str, Any]:
    records = _fc_records(data if isinstance(data, dict) else {"data": data})
    pid = None
    if records:
        pid = records[0].get("id") or records[0].get("project_id") or records[0].get("task_id")
    provision_ids = [pid] if pid not in (None, "") else []
    return {"records": records, "data_count": len(records), "status": status, "message": "ok", "provision_ids": provision_ids}


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
