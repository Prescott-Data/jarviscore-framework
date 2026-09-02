import requests
from typing import Any, Dict, List, Optional

_ASANA_API_SUFFIX = "/api/1.0"


def asana_get_task(auth_info: dict, task_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get a task by GID (GET /tasks/{task_gid}). Asana REST API v1.0. Official: https://developers.asana.com/reference/rest-api-reference"""
    try:
        if not base_url:
            return {"records": [], "data_count": 0, "status": 400, "message": "base_url is required"}
        if not task_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "task_id is required"}
        api_root, root_err = _asana_api_root(base_url)
        if root_err:
            return {"records": [], "data_count": 0, "status": 400, "message": root_err}
        headers, auth_err = _asana_headers(auth_info)

        if auth_err:

            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = requests.get(
            f"{api_root}/tasks/{task_id}",
            headers=headers,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        body = resp.json()
        item = body.get("data") if isinstance(body, dict) else None
        records: List[Dict[str, Any]] = [item] if isinstance(item, dict) else []
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _asana_api_root(base_url: str):
    root = base_url.rstrip("/")
    if root.endswith("/api/1.0"):
        return root, None
    if root.endswith("/api"):
        return root + "/1.0", None
    if root == "https://app.asana.com" or (_host_is(root, "app.asana.com") and "/" not in root.split("://", 1)[-1]):
        return root + "/api/1.0", None
    return None, "base_url must be https://app.asana.com/api/1.0"


def _asana_headers(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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
