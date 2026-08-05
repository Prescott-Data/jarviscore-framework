import requests
from typing import Any, Dict, List, Optional

# Assembla Developer API — https://api-docs.assembla.cc/
_ASSEMBLA_V1_SUFFIX = "/v1"


def assembla_list_pipelines(auth_info: dict, space_id: Optional[str] = None, space_tool_id: Optional[str] = None, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List merge requests in a repo tool (GET ./merge_requests.json). Mapped from pipeline catalog op. Official: https://api-docs.assembla.cc"""
    try:
        if not base_url:
            return {"records": [], "data_count": 0, "status": 400, "message": "base_url is required"}
        api_root, root_err = _assembla_api_root(base_url)
        if root_err:
            return {"records": [], "data_count": 0, "status": 400, "message": root_err}
        sid = _assembla_space_id(auth_info, space_id)
        tool_id = _assembla_space_tool_id(auth_info, space_tool_id)
        if not sid or not tool_id:
            return {
                "records": [],
                "data_count": 0,
                "status": 400,
                "message": "space_id and space_tool_id are required (repo tool with merge requests)",
            }
        headers, auth_err = _assembla_headers(auth_info)

        if auth_err:

            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        url = _assembla_json_path(f"{api_root}/spaces/{sid}/space_tools/{tool_id}/merge_requests")
        records, status, message = _assembla_paginate_page(url, headers, limit, timeout, verify_ssl, per_page_default=10)
        if message != "ok":
            return {"records": records, "data_count": len(records), "status": status, "message": message}
        return {"records": records, "data_count": len(records), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _assembla_api_root(base_url: str):
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        return root, None
    if root.endswith("/api"):
        return root + "/v1", None
    if root == "https://api.assembla.com" or root.endswith("api.assembla.com"):
        return root + "/v1", None
    return None, "base_url must be https://api.assembla.com/v1"


def _assembla_headers(auth_info, json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    username = auth_info.get("username")
    password = auth_info.get("password")
    if username and password:
        headers["X-Api-Key"] = str(username)
        headers["X-Api-Secret"] = str(password)
        return headers, None
    return None, "auth_info requires username and password"


def _assembla_json_path(path: str) -> str:
    return path if path.endswith(".json") else f"{path}.json"


def _assembla_space_id(auth_info, space_id=None):
    auth_info = auth_info or {}
    return space_id or auth_info.get("space_id") or auth_info.get("project_id") or auth_info.get("space")


def _assembla_space_tool_id(auth_info, space_tool_id=None):
    auth_info = auth_info or {}
    return (
        space_tool_id
        or auth_info.get("space_tool_id")
        or auth_info.get("pipeline_id")
        or auth_info.get("repo_tool_id")
    )


def _assembla_wrap_namespace(namespace: str, payload: Dict[str, Any]):
    if isinstance(payload, dict) and isinstance(payload.get(namespace), dict):
        return payload
    return {namespace: payload or {}}


def _assembla_provision_id(body, keys=("id", "number")):
    if not isinstance(body, dict):
        return []
    for key in keys:
        if body.get(key) not in (None, ""):
            return [body[key]]
    return []


def _assembla_paginate_page(
    url,
    headers,
    limit,
    timeout,
    verify_ssl,
    extra_params=None,
    per_page_default=25,
):
    records: List[Dict[str, Any]] = []
    page = 1
    status = 0
    extra_params = dict(extra_params or {})
    per_page = min(max(limit, 1), 100)
    while len(records) < limit:
        params = dict(extra_params)
        params["page"] = page
        params["per_page"] = min(per_page, limit - len(records)) if "per_page" not in params else params["per_page"]
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        try:
            data = resp.json()
        except Exception:
            return records, status, "Unexpected response format"
        batch = data if isinstance(data, list) else []
        if not batch:
            break
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(batch) < params.get("per_page", per_page):
            break
        page += 1
        if page > 200:
            break
    return records[:limit], status, "ok"
