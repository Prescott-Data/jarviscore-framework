import requests
from typing import Any, Dict, List, Optional



def perforce_get_project(auth_info: dict, project_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get Swarm project by id. Official: https://help.perforce.com/helix-core/helix-swarm/swarm/current/Content/Swarm/swarm-apidoc_endpoint_projects.html"""
    try:
        root, err = _pf_root(base_url, auth_info)
        if err:
            return _pf_dataset([], 400, err)
        if not project_id:
            return _pf_dataset([], 400, "project_id is required")
        auth_info = auth_info or {}
        params = {}
        fields = auth_info.get("fields")
        if fields:
            params["fields"] = fields
        resp, data, status, err = _pf_request("get", root + f"/projects/{project_id}", auth_info, params=params, timeout=timeout, verify_ssl=verify_ssl)
        if err:
            return _pf_dataset([], 401, err)
        if status >= 400:
            return _pf_dataset([], status, _pf_err(resp))
        return _pf_dataset(_pf_projects(data), status, "ok")

    except Exception as e:
        return _pf_dataset([], 500, str(e))


# Helix Swarm REST API — Official docs: https://help.perforce.com/helix-core/helix-swarm/swarm/current/Content/Swarm/swarm-apidoc_endpoint_projects.html


def _pf_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("swarm_url") or auth_info.get("perforce_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    version = str(auth_info.get("api_version") or "v11")
    if not root:
        return None, "base_url is required (https://my-swarm-host/api/v11)"
    if "/api/v" not in root:
        root = root + f"/api/{version}"
    return root, None


def _pf_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    user = auth_info.get("username")
    pwd = auth_info.get("password")
    if not user or pwd is None:
        return None, None, "auth_info requires username and password"
    return headers, requests.auth.HTTPBasicAuth(str(user), str(pwd)), None


def _pf_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _pf_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error")
            if isinstance(msg, list):
                msg = "; ".join(str(x) for x in msg)
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _pf_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pf_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get("project") if isinstance(obj.get("project"), dict) else obj
    pid = inner.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = inner if inner else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pf_projects(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get("projects")
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
        proj = data.get("project")
        if isinstance(proj, dict):
            return [proj]
    return []


def _pf_request(method, url, auth_info, params=None, json_body=None, data=None, timeout=30, verify_ssl=True):
    headers, basic, err = _pf_auth(auth_info, json_body=(json_body is not None))
    if err:
        return None, None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if basic is not None:
        kwargs["auth"] = basic
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        if json_body is not None:
            resp = requests.post(url, params=params, json=json_body, **kwargs)
        else:
            resp = requests.post(url, params=params, data=data, **kwargs)
    elif method == "patch":
        resp = requests.patch(url, params=params, json=json_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    return resp, body, resp.status_code, None


def _pf_match(record, query):
    q = str(query).lower()
    for key in ("id", "name", "description"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
