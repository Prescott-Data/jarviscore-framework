import requests
from typing import Any, Dict, List, Optional

_ASANA_API_SUFFIX = "/api/1.0"
_TYPEAHEAD_RESOURCES = {
    "task",
    "project",
    "user",
    "tag",
    "team",
    "portfolio",
    "goal",
    "custom_field",
    "project_template",
}


def asana_search_records(auth_info: dict, query: str, workspace: Optional[str] = None, resource_type: str = "task", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Workspace typeahead search (GET /workspaces/{workspace_gid}/typeahead). Asana REST API v1.0. Official: https://developers.asana.com/reference/rest-api-reference"""
    try:
        if not base_url:
            return {"records": [], "data_count": 0, "status": 400, "message": "base_url is required"}
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
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
        resource = str(resource_type or "task").lower()
        if resource not in _TYPEAHEAD_RESOURCES:
            return {
                "records": [],
                "data_count": 0,
                "status": 400,
                "message": f"resource_type must be one of: {sorted(_TYPEAHEAD_RESOURCES)}",
            }
        headers, auth_err = _asana_headers(auth_info)

        if auth_err:

            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        params = {
            "resource_type": resource,
            "query": query,
            "count": min(max(limit, 1), 100),
        }
        resp = requests.get(
            f"{api_root}/workspaces/{workspace_gid}/typeahead",
            headers=headers,
            params=params,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return {"records": [], "data_count": 0, "status": status, "message": resp.text[:1000]}
        body = resp.json()
        batch = body.get("data") if isinstance(body, dict) else []
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        records: List[Dict[str, Any]] = [item for item in batch if isinstance(item, dict)][:limit]
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _asana_api_root(base_url: str):
    root = base_url.rstrip("/")
    if root.endswith("/api/1.0"):
        return root, None
    if root.endswith("/api"):
        return root + "/1.0", None
    if root == "https://app.asana.com" or root.endswith("app.asana.com"):
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
