import requests
from typing import Any, Dict, List, Optional

# Asana REST API — https://developers.asana.com/reference/rest-api-reference
_ASANA_API_SUFFIX = "/api/1.0"


def asana_list_projects(auth_info: dict, workspace: Optional[str] = None, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List projects in a workspace (GET /projects?workspace=). Asana REST API v1.0. Official: https://developers.asana.com/reference/rest-api-reference"""
    try:
        if not base_url:
            return {"records": [], "data_count": 0, "status": 400, "message": "base_url is required"}
        api_root, root_err = _asana_api_root(base_url)
        if root_err:
            return {"records": [], "data_count": 0, "status": 400, "message": root_err}
        workspace_gid = _asana_workspace(auth_info, workspace)
        if not workspace_gid:
            return {
                "records": [],
                "data_count": 0,
                "status": 400,
                "message": "workspace (or workspace_gid in auth_info) is required",
            }
        headers, auth_err = _asana_headers(auth_info)

        if auth_err:

            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        records, status, message = _asana_paginate(
            f"{api_root}/projects",
            headers,
            limit,
            timeout,
            verify_ssl,
            {"workspace": str(workspace_gid)},
        )
        if message != "ok":
            return {"records": records, "data_count": len(records), "status": status, "message": message}
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


def _asana_workspace(auth_info, workspace=None):
    auth_info = auth_info or {}
    return (
        workspace
        or auth_info.get("workspace")
        or auth_info.get("workspace_gid")
        or auth_info.get("workspace_id")
    )


def _asana_paginate(url, headers, limit, timeout, verify_ssl, extra_params=None):
    records: List[Dict[str, Any]] = []
    offset = None
    page_size = min(max(limit, 1), 100)
    status = 0
    extra_params = dict(extra_params or {})
    while len(records) < limit:
        params = dict(extra_params)
        params["limit"] = min(page_size, limit - len(records))
        if offset:
            params["offset"] = offset
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        body = resp.json()
        if not isinstance(body, dict):
            return records, status, "Unexpected response format"
        batch = body.get("data") or []
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        next_page = body.get("next_page")
        if not isinstance(next_page, dict) or not next_page.get("offset") or len(records) >= limit:
            break
        offset = next_page.get("offset")
    return records[:limit], status, "ok"


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
