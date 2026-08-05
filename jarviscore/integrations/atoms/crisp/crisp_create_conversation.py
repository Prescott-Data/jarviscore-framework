import requests
from typing import Any, Dict, List, Optional

# Crisp REST API v1 — https://api.crisp.chat/v1
CRISP_API = "https://api.crisp.chat/v1"


def crisp_create_conversation(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create a conversation in crisp. HTTP Basic site_id:api_key. Official: https://docs.crisp.chat/references/rest-api/v1/"""
    try:
        if not payload:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        headers, basic, site_id = _crisp_auth(auth_info, json_body=True)
        if not site_id or not basic:
            return {"records": [], "data_count": 0, "status": 401, "message": "auth_info requires site_id and api_key for Basic auth"}
        api = _crisp_api_root(base_url)
        url = f"{api}/website/{site_id}/conversation"
        resp = _crisp_post(url, headers, basic, payload, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data, message = _crisp_parse(resp)
        records = _crisp_records(data, single=True)
        prov = _crisp_provision_ids(records[0]) if records else []
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": message, "provision_ids": prov}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _crisp_api_root(base_url):
    root = (base_url or CRISP_API).rstrip("/")
    if root.endswith("/v1"):
        return root
    if "crisp.chat" in root and "/v1" not in root:
        return root + "/v1"
    return root


def _crisp_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "X-Crisp-Tier": "plugin"}
    if json_body:
        headers["Content-Type"] = "application/json"
    site_id = auth_info.get("site_id") or auth_info.get("website_id")
    username = auth_info.get("username")
    password = auth_info.get("password")
    basic = None
    if username and password:
        basic = (str(username).strip(), str(password).strip())
    return headers, basic, site_id


def _crisp_get(url, headers, basic, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, auth=basic, params=params, timeout=timeout, verify=verify_ssl)


def _crisp_post(url, headers, basic, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _crisp_patch(url, headers, basic, body, timeout, verify_ssl):
    return requests.patch(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _crisp_parse(resp):
    try:
        payload = resp.json() if resp.text else {}
    except Exception:
        return None, resp.text[:1000]
    if isinstance(payload, dict) and payload.get("error"):
        reason = payload.get("reason") or payload.get("message") or "Crisp API error"
        return None, str(reason)
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data"), "ok"
    return payload, "ok"


def _crisp_records(data, single=False):
    if single:
        if isinstance(data, dict):
            return [data]
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _crisp_session_id(auth_info, payload=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    sid = (
        payload.get("conversation_id")
        or payload.get("session_id")
        or auth_info.get("conversation_id")
        or auth_info.get("session_id")
    )
    if sid:
        return str(sid), None
    return None, (
        "Crisp messages require conversation_id (session_id) in auth_info or payload."
    )


def _crisp_list_conversations(api, site_id, headers, basic, limit, timeout, verify_ssl, search_query=None):
    records = []
    page = 1
    status = 0
    per_page = min(max(int(limit or 25), 20), 50)
    while len(records) < limit:
        params = {"per_page": min(per_page, limit - len(records))}
        if search_query:
            params["search_query"] = search_query
        url = f"{api}/website/{site_id}/conversations/{page}"
        resp = _crisp_get(url, headers, basic, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data, _ = _crisp_parse(resp)
        batch = _crisp_records(data)
        if not batch:
            break
        for item in batch:
            records.append(item)
            if len(records) >= limit:
                break
        if len(batch) < params["per_page"]:
            break
        page += 1
        if page > 500:
            break
    return records[:limit], status, "ok"


def _crisp_list_messages(api, site_id, session_id, headers, basic, limit, timeout, verify_ssl):
    records = []
    timestamp_before = None
    status = 0
    while len(records) < limit:
        params = {}
        if timestamp_before is not None:
            params["timestamp_before"] = timestamp_before
        url = f"{api}/website/{site_id}/conversation/{session_id}/messages"
        resp = _crisp_get(url, headers, basic, params or None, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data, _ = _crisp_parse(resp)
        batch = _crisp_records(data)
        if not batch:
            break
        for item in batch:
            records.append(item)
            if len(records) >= limit:
                break
        if len(batch) < 40:
            break
        last = batch[-1]
        ts = last.get("timestamp") if isinstance(last, dict) else None
        if ts is None or ts == timestamp_before:
            break
        timestamp_before = ts
    return records[:limit], status, "ok"


def _crisp_provision_ids(data):
    if not isinstance(data, dict):
        return []
    for key in ("session_id", "fingerprint", "id"):
        val = data.get(key)
        if val not in (None, ""):
            return [str(val)]
    return []
