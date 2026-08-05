import requests
from typing import Any, Dict, List, Optional


def beanstalk_get_pipeline(auth_info: dict, pipeline_id: str, repository_id: str, account: Optional[str] = None, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get server environment. GET /api/{repository_id}/server_environments/{id}.json. Official: https://api.beanstalkapp.com/server_environment"""
    try:
        if not pipeline_id or not repository_id: return {"records": [], "data_count": 0, "status": 400, "message": "pipeline_id and repository_id are required"}
        api_root, err = _beanstalk_api_root(base_url, account)
        if err: return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _beanstalk_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = _beanstalk_get(api_root, f"/{repository_id}/server_environments/{pipeline_id}.json", headers, basic, None, timeout, verify_ssl)
        if resp.status_code >= 400: return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        env = data.get("server_environment") if isinstance(data, dict) else data
        return {"records": [env] if env else [], "data_count": 1 if env else 0, "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}


# Beanstalk API — https://api.beanstalkapp.com/introduction
def _beanstalk_api_root(base_url, account=None):
    root = (base_url or "").rstrip("/")
    if not root and account:
        root = f"https://{account}.beanstalkapp.com"
    if not root:
        return None, "base_url or account is required (https://{account}.beanstalkapp.com)"
    if not root.endswith("/api"):
        if ".beanstalkapp.com" in root and not root.endswith("/api"):
            root = root + "/api"
    return root, None


def _beanstalk_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "User-Agent": "jarviscore/1.0"}
    if json_body:
        headers["Content-Type"] = "application/json"
    username = auth_info.get("username")
    password = auth_info.get("password")
    if username and password:
        return headers, (str(username), str(password)), None
    return None, None, "auth_info requires username and password"


def _beanstalk_get(api_root, path, headers, basic, params, timeout, verify_ssl):
    return requests.get(f"{api_root}{path}", headers=headers, auth=basic, params=params, timeout=timeout, verify=verify_ssl)


def _beanstalk_post(api_root, path, headers, basic, body, params, timeout, verify_ssl):
    return requests.post(f"{api_root}{path}", headers=headers, auth=basic, json=body, params=params, timeout=timeout, verify=verify_ssl)


def _beanstalk_put(api_root, path, headers, basic, body, params, timeout, verify_ssl):
    return requests.put(f"{api_root}{path}", headers=headers, auth=basic, json=body, params=params, timeout=timeout, verify=verify_ssl)


def _beanstalk_unwrap_list(data):
    if isinstance(data, list):
        out = []
        for item in data:
            if isinstance(item, dict) and len(item) == 1:
                out.append(next(iter(item.values())))
            else:
                out.append(item)
        return out
    if isinstance(data, dict):
        return [data]
    return []


def _beanstalk_paginate(api_root, path, headers, basic, limit, timeout, verify_ssl, extra=None):
    records = []
    page = 1
    status = 0
    extra = extra or {}
    while len(records) < limit:
        params = {"page": page, "per_page": min(50, limit - len(records))}
        params.update(extra)
        resp = _beanstalk_get(api_root, path, headers, basic, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        batch = _beanstalk_unwrap_list(resp.json() if resp.text else [])
        if not batch:
            break
        for item in batch:
            records.append(item)
            if len(records) >= limit:
                break
        if len(batch) < params["per_page"]:
            break
        page += 1
        if page > 200:
            break
    return records[:limit], status, "ok"
