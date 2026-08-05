import requests
from typing import Any, Dict, List, Optional

def proofhub_list_projects(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List all projects. Official: https://github.com/ProofHub/api_v3/blob/master/README.md"""
    try:
        root, err = _ph_root(base_url, auth_info)
        if err:
            return _ph_dataset([], 400, err)
        resp, body, status, msg = _ph_request("get", root + "/projects", auth_info, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _ph_dataset([], status, msg)
        return _ph_dataset(_ph_rows(body)[: _ph_cap(limit)], status, msg)
    except Exception as e:
        return _ph_dataset([], 500, str(e))


# ProofHub REST API v3 — Official docs: https://github.com/ProofHub/api_v3/blob/master/README.md


def _ph_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("proofhub_url") or auth_info.get("account_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://company.proofhub.com/api/v3)"
    if "/api/v3" not in root:
        root = root + "/api/v3"
    return root, None


def _ph_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info.api_key or x_api_key is required"
    ua = auth_info.get("user_agent") or auth_info.get("app_name") or "jarviscoreIntegration (integration@jarviscore.io)"
    headers = {"X-API-KEY": str(key).strip(), "User-Agent": str(ua).strip(), "Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _ph_cap(limit):
    return min(max(int(limit or 25), 1), 100)


def _ph_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _ph_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _ph_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("message") or body.get("error")
        if err:
            return str(err)[:1000]
    try:
        if resp is not None and resp.content:
            data = resp.json()
            if isinstance(data, dict) and data.get("message"):
                return str(data.get("message"))[:1000]
    except Exception:
        pass
    return (resp.text if resp is not None else "request failed")[:1000]


def _ph_rows(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for key in ("todos", "results", "data", "items"):
            val = body.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        return [body]
    return []


def _ph_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _ph_auth(auth_info, json_body=(json_body is not None))
    if err:
        return None, None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, json=json_body, **kwargs)
    elif method == "put":
        resp = requests.put(url, params=params, json=json_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _ph_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _ph_ids(auth_info, payload=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    project_id = payload.get("project_id") or auth_info.get("project_id")
    todolist_id = payload.get("todolist_id") or payload.get("list_id") or auth_info.get("todolist_id") or auth_info.get("list_id")
    task_id = payload.get("task_id") or auth_info.get("task_id")
    return project_id, todolist_id, task_id


def _ph_match(record, query):
    q = str(query).lower()
    for key in ("id", "title", "description", "ticket", "name"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False


def _ph_fetch_list_tasks(root, auth_info, project_id, todolist_id, cap, timeout, verify_ssl):
    url = root + f"/projects/{project_id}/todolists/{todolist_id}/tasks"
    resp, body, status, msg = _ph_request("get", url, auth_info, timeout=timeout, verify_ssl=verify_ssl)
    if status >= 400:
        return [], status, msg
    rows = _ph_rows(body)
    for row in rows:
        row.setdefault("project_id", project_id)
        row.setdefault("todolist_id", todolist_id)
    return rows[:cap], status, msg


def _ph_collect_tasks(root, auth_info, cap, timeout, verify_ssl, project_id=None):
    records = []
    status = 200
    msg = "ok"
    if project_id:
        resp, body, status, msg = _ph_request("get", root + f"/projects/{project_id}/todolists", auth_info, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return [], status, msg
        lists = _ph_rows(body)
    else:
        start = 0
        lists = []
        while len(lists) < cap:
            page = min(100, cap)
            resp, body, status, msg = _ph_request("get", root + "/alltodo", auth_info, params={"start": start, "limit": page}, timeout=timeout, verify_ssl=verify_ssl)
            if status >= 400:
                return [], status, msg
            batch = _ph_rows(body)
            if not batch:
                break
            lists.extend(batch)
            if len(batch) < page:
                break
            start += page
    for lst in lists:
        if len(records) >= cap:
            break
        lid = lst.get("id")
        pid = project_id or (lst.get("project") or {}).get("id")
        if not pid or not lid:
            continue
        batch, status, msg = _ph_fetch_list_tasks(root, auth_info, pid, lid, cap - len(records), timeout, verify_ssl)
        if status >= 400 and not records:
            return [], status, msg
        records.extend(batch)
    return records[:cap], status, msg
