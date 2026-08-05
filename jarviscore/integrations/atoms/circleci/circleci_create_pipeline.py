import requests
from typing import Any, Dict, List, Optional

# CircleCI API v2 — https://circleci.com/docs/api/v2/
CIRCLECI_API = "https://circleci.com/api/v2"


def circleci_create_pipeline(auth_info: dict, timeout: int = 30, verify_ssl: bool = True, payload: Optional[Dict[str, Any]] = None, base_url: str = None) -> dict:
    """Create Pipeline via CircleCI API v2. Circle-Token auth. Official: https://circleci.com/docs/api/v2/operations/triggerPipeline.md"""
    try:
        api = _circleci_api_root(base_url)
        headers, auth_err = _circleci_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        payload = payload or {}
        slug = payload.get("project_slug") or payload.get("project_id")
        if not slug:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload.project_slug or payload.project_id is required"}
        url, err = _circleci_project_path(api, slug)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        body = _circleci_pipeline_body(payload)
        resp = _circleci_post(f"{url}/pipeline", headers, body, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        prov = _circleci_provision_id(data)
        records = [data] if isinstance(data, dict) else []
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok", "provision_ids": prov}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _circleci_api_root(base_url):
    root = (base_url or CIRCLECI_API).rstrip("/")
    if "circleci.com" in root and "/api/v2" not in root:
        root = root + "/api/v2" if not root.endswith("/api") else root + "/v2"
    return root


def _circleci_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info requires personal_api_token"
    headers = {"Accept": "application/json", "Circle-Token": str(token).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _circleci_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _circleci_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _circleci_records(data, list_keys):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in list_keys:
            items = data.get(key)
            if isinstance(items, list):
                return items
        return [data]
    return []


def _circleci_project_path(api, project_slug):
    slug = (project_slug or "").strip().lstrip("/")
    if not slug:
        return None, "project_slug is required (e.g. gh/org/repo)"
    return f"{api}/project/{slug}", None


def _circleci_paginate_items(url, headers, limit, timeout, verify_ssl, list_keys=("items",)):
    records = []
    page_token = None
    status = 0
    pages = 0
    while len(records) < limit and pages < 50:
        pages += 1
        params = {"page-token": page_token} if page_token else None
        resp = _circleci_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _circleci_records(data, list_keys)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        if len(records) >= limit:
            break
        if isinstance(data, dict):
            page_token = data.get("next_page_token")
        else:
            page_token = None
        if not page_token:
            break
    return records[:limit], status, "ok"


def _circleci_provision_id(data):
    if not isinstance(data, dict):
        return []
    for key in ("id", "number", "pipeline_number", "pipeline_id"):
        if data.get(key) not in (None, ""):
            return [data.get(key)]
    return []


def _circleci_not_supported(message):
    return {"records": [], "data_count": 0, "status": 501, "message": message}


def _circleci_pipeline_body(payload, branch=None, parameters=None):
    body = dict(payload) if isinstance(payload, dict) else {}
    for key in ("project_slug", "project_id"):
        body.pop(key, None)
    if branch is not None:
        body["branch"] = branch
    if parameters is not None:
        body["parameters"] = parameters
    return body
