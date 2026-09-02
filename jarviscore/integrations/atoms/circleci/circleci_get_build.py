import requests
from typing import Any, Dict, List, Optional

# CircleCI API v2 — https://circleci.com/docs/api/v2/
CIRCLECI_API = "https://circleci.com/api/v2"


def circleci_get_build(auth_info: dict, project_slug: str, build_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get job details by job number (GET /project/{project-slug}/job/{job-number}). Circle-Token auth. Official: https://circleci.com/docs/api/v2/operations/getJobDetails.md"""
    try:
        if not project_slug:
            return {"records": [], "data_count": 0, "status": 400, "message": "project_slug is required (e.g. gh/org/repo)"}
        if not build_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "build_id (job number) is required"}
        api = _circleci_api_root(base_url)
        headers, auth_err = _circleci_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        base, err = _circleci_project_path(api, project_slug)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        resp = _circleci_get(f"{base}/job/{build_id}", headers, None, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = [data] if isinstance(data, dict) else []
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _circleci_api_root(base_url):
    root = (base_url or CIRCLECI_API).rstrip("/")
    if _host_is(root, "circleci.com") and "/api/v2" not in root:
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
