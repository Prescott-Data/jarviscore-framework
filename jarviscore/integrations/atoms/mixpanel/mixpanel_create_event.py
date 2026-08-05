import requests
from typing import Any, Dict, List, Optional

# Mixpanel API — Official docs:
# https://developer.mixpanel.com/reference/track-event


MP_INGEST = "https://api.mixpanel.com"
MP_QUERY = "https://mixpanel.com/api/query"
MP_EXPORT = "https://data.mixpanel.com/api/2.0"



def mixpanel_create_event(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Track an event via Ingestion API /track. Official: https://developer.mixpanel.com/reference/track-event"""
    try:
        root, _ = _mp_ingest_root(base_url)
        tok, terr = _mp_project_token(auth_info, payload)
        if terr:
            return {"records": [], "data_count": 0, "status": 401, "message": terr, "provision_ids": []}
        body = payload if isinstance(payload, dict) else {}
        event_name = body.get("event") or body.get("name")
        if not event_name:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload.event is required", "provision_ids": []}
        props = dict(body.get("properties") if isinstance(body.get("properties"), dict) else body)
        props.pop("event", None)
        props.pop("name", None)
        props["token"] = tok
        if body.get("distinct_id") and "distinct_id" not in props:
            props["distinct_id"] = body.get("distinct_id")
        track = [{"event": str(event_name), "properties": props}]
        resp = requests.post(f"{root}/track", params={"verbose": "1"}, json=track, timeout=timeout, verify=verify_ssl)
        insert_id = props.get("$insert_id") or props.get("insert_id")
        fallback = insert_id or f"{event_name}|{props.get('distinct_id', '')}"
        return _mp_provision(resp, fallback_id=fallback)
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _mp_ingest_root(base_url):
    return (base_url or MP_INGEST).rstrip("/"), None


def _mp_query_root(base_url):
    root = (base_url or MP_QUERY).rstrip("/")
    if not root.endswith("/api/query"):
        if "mixpanel.com" in root and "/api/query" not in root:
            root = root + "/api/query"
    return root, None


def _mp_export_root(base_url):
    root = (base_url or MP_EXPORT).rstrip("/")
    if not root.endswith("/api/2.0"):
        if "mixpanel.com" in root and "/api/2.0" not in root:
            root = root + "/api/2.0"
    return root, None


def _mp_project_id(auth_info, project_id=""):
    auth_info = auth_info or {}
    pid = project_id or auth_info.get("project_id")
    if pid in (None, ""):
        return None, "project_id is required (param or auth_info.project_id)"
    return str(pid), None


def _mp_project_token(auth_info, payload=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    tok = auth_info.get("project_token") or auth_info.get("token") or payload.get("token") or payload.get("$token")
    if not tok:
        return None, "auth_info.project_token is required"
    return str(tok), None


def _mp_basic_headers(auth_info):
    auth_info = auth_info or {}
    username = auth_info.get("username")
    password = auth_info.get("password")
    if not username or password is None:
        return None, "auth_info requires username and password"
    import base64
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": "Basic " + encoded, "Accept": "application/json"}, None


def _mp_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _mp_jsonl(text):
    rows = []
    import json
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def _mp_error_text(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            if data.get("error"):
                return str(data.get("error"))[:1000]
            if data.get("status") == "error":
                return str(data.get("error") or data)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _mp_provision_ids_from_body(body, fallback=None):
    if isinstance(body, dict):
        props = body.get("properties") if isinstance(body.get("properties"), dict) else {}
        for key in ("$insert_id", "insert_id", "id", "$distinct_id", "distinct_id"):
            val = body.get(key) or props.get(key)
            if val not in (None, ""):
                return [val]
    return [fallback] if fallback not in (None, "") else []


def _mp_provision(resp, fallback_id=None):
    status = resp.status_code
    if status >= 400:
        return {"records": [], "data_count": 0, "status": status, "message": _mp_error_text(resp), "provision_ids": []}
    body = {}
    try:
        if resp.text:
            body = resp.json()
    except Exception:
        body = {"raw": resp.text[:200]}
    if isinstance(body, int):
        if body != 1:
            return {"records": [], "data_count": 0, "status": 400, "message": "Mixpanel rejected payload", "provision_ids": []}
        ids = [fallback_id] if fallback_id not in (None, "") else []
        rec = {"id": fallback_id} if ids else []
        return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": "ok", "provision_ids": ids}
    ids = _mp_provision_ids_from_body(body, fallback_id)
    records = [body] if isinstance(body, dict) and body else ([{"id": ids[0]}] if ids else [])
    return {"records": records, "data_count": len(records), "status": status, "message": "ok", "provision_ids": ids}


def _mp_engage_query(base_url, auth_info, project_id, form_data, timeout, verify_ssl):
    root, _ = _mp_query_root(base_url)
    pid, perr = _mp_project_id(auth_info, project_id)
    if perr:
        return None, 400, perr
    headers, aerr = _mp_basic_headers(auth_info)
    if aerr:
        return None, 400, aerr
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    resp = requests.post(f"{root}/engage", params={"project_id": pid}, headers=headers, data=form_data or {}, timeout=timeout, verify=verify_ssl)
    if resp.status_code >= 400:
        return None, resp.status_code, _mp_error_text(resp)
    try:
        return resp.json(), resp.status_code, "ok"
    except Exception:
        return None, resp.status_code, resp.text[:1000]
