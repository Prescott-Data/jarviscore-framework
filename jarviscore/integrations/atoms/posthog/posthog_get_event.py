import requests
from typing import Any, Dict, List, Optional


def posthog_get_event(auth_info: dict, event_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Retrieve single event by UUID (legacy events endpoint). Official: https://posthog.com/docs/api/events"""
    try:
        if not event_id:
            return _pg_dataset([], 400, "event_id is required")
        project_id = _pg_project_id(auth_info)
        if not project_id:
            return _pg_dataset([], 400, "auth_info.project_id is required")
        host = _pg_app_host(base_url, auth_info)
        resp, body, status, msg = _pg_request(
            "get",
            host + f"/api/projects/{project_id}/events/{str(event_id).strip()}/",
            auth_info,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
        if status >= 400:
            return _pg_dataset([], status, msg)
        return _pg_dataset(_pg_items(body), status, msg)
    except Exception as e:
        return _pg_dataset([], 500, str(e))


# PostHog API — Official docs: https://posthog.com/docs/api


def _pg_app_host(base_url, auth_info):
    auth_info = auth_info or {}
    host = (base_url or auth_info.get("posthog_host") or auth_info.get("base_url") or "https://us.posthog.com").strip().rstrip("/")
    if host.endswith("/api"):
        host = host[:-4]
    return host.rstrip("/")


def _pg_ingest_host(base_url, auth_info):
    auth_info = auth_info or {}
    ingest = auth_info.get("ingest_host") or auth_info.get("capture_host")
    if ingest:
        return str(ingest).strip().rstrip("/")
    app = _pg_app_host(base_url, auth_info)
    if "eu.posthog.com" in app:
        return "https://eu.i.posthog.com"
    if "posthog.com" in app:
        return "https://us.i.posthog.com"
    return app


def _pg_project_id(auth_info):
    auth_info = auth_info or {}
    return auth_info.get("project_id") or auth_info.get("posthog_project_id")


def _pg_private_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info.personal_api_key or api_key is required"
    t = str(key).strip()
    headers = {"Authorization": t if t.lower().startswith("bearer ") else f"Bearer {t}", "Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _pg_cap(limit):
    return min(max(int(limit or 25), 1), 10000)


def _pg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pg_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("uuid") or obj.get("short_id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pg_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("detail") or body.get("error") or body.get("message")
        if err:
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _pg_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return [x for x in data["results"] if isinstance(x, dict)]
        inner = data.get("result")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        if isinstance(inner, dict):
            rows = inner.get("results") or inner.get("rows")
            if isinstance(rows, list):
                return [x for x in rows if isinstance(x, dict)]
        return [data]
    return []


def _pg_query_rows(data):
    rows = []
    if not isinstance(data, dict):
        return rows
    result = data.get("results") or data.get("result")
    if isinstance(result, list):
        for item in result:
            if isinstance(item, list):
                rows.append({"values": item})
            elif isinstance(item, dict):
                rows.append(item)
    elif isinstance(result, dict):
        inner = result.get("results") or result.get("rows")
        if isinstance(inner, list):
            for item in inner:
                if isinstance(item, list):
                    rows.append({"values": item})
                elif isinstance(item, dict):
                    rows.append(item)
    columns = None
    if isinstance(data.get("columns"), list):
        columns = data.get("columns")
    elif isinstance(result, dict) and isinstance(result.get("columns"), list):
        columns = result.get("columns")
    if columns and rows and isinstance(rows[0].get("values"), list):
        fixed = []
        for row in rows:
            vals = row.get("values") or []
            obj = {}
            for i, col in enumerate(columns):
                if i < len(vals):
                    obj[str(col)] = vals[i]
            fixed.append(obj)
        return fixed
    return rows


def _pg_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True, private=True):
    if private:
        headers, err = _pg_private_auth(auth_info, json_body=(json_body is not None))
    else:
        headers = {"Accept": "application/json"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        err = None
    if err:
        return None, None, 401, err
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, json=json_body, **kwargs)
    elif method == "patch":
        resp = requests.patch(url, params=params, json=json_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _pg_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _pg_query(base_url, auth_info, hogql, timeout=30, verify_ssl=True):
    project_id = _pg_project_id(auth_info)
    if not project_id:
        return None, None, 400, "auth_info.project_id is required"
    host = _pg_app_host(base_url, auth_info)
    body = {"query": {"kind": "HogQLQuery", "query": hogql}}
    return _pg_request("post", host + f"/api/projects/{project_id}/query/", auth_info, json_body=body, timeout=timeout, verify_ssl=verify_ssl)
