import requests
from typing import Any, Dict, List, Optional

# Gorgias REST API — https://developers.gorgias.com/reference/list-tickets
GORGIAS_API = "https://your-domain.gorgias.com/api"


def gorgias_update_conversation(auth_info: dict, conversation_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update a Gorgias ticket. Official: https://developers.gorgias.com/reference/update-ticket"""
    try:
        if not conversation_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "conversation_id is required"}
        if not payload:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        api, err = _gorgias_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _gorgias_require_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = _gorgias_put(f"{api}/tickets/{conversation_id}", headers, basic, payload, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        records = _gorgias_single_record(resp.json() if resp.text else {})
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _gorgias_api_root(base_url):
    root = (base_url or GORGIAS_API).rstrip("/")
    if not root.endswith("/api"):
        if ".gorgias.com" in root:
            root = root + "/api"
        else:
            return None, "base_url must be https://{domain}.gorgias.com/api"
    return root, None


def _gorgias_require_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    username = auth_info.get("username")
    password = auth_info.get("password")
    if username and password:
        return headers, (str(username), str(password)), None
    return None, None, "auth_info requires username and password"


def _gorgias_get(url, headers, basic, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, auth=basic, params=params, timeout=timeout, verify=verify_ssl)


def _gorgias_post(url, headers, basic, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _gorgias_put(url, headers, basic, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, auth=basic, json=body, timeout=timeout, verify=verify_ssl)


def _gorgias_cursor_paginate(url, headers, basic, limit, timeout, verify_ssl, extra_params=None):
    records = []
    cursor = None
    status = 0
    cap = min(max(int(limit or 25), 1), 100)
    extra_params = dict(extra_params or {})
    pages = 0
    while len(records) < cap and pages < 100:
        pages += 1
        params = {"limit": min(cap - len(records), 100)}
        params.update(extra_params)
        if cursor:
            params["cursor"] = cursor
        resp = _gorgias_get(url, headers, basic, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = data.get("data") if isinstance(data, dict) else []
        if not isinstance(batch, list):
            batch = [batch] if isinstance(batch, dict) else []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    break
        meta = data.get("meta") if isinstance(data, dict) else {}
        cursor = meta.get("next_cursor") if isinstance(meta, dict) else None
        if not cursor or not batch:
            break
    return records[:cap], status, "ok"


def _gorgias_single_record(data):
    if isinstance(data, dict):
        if isinstance(data.get("data"), dict):
            return [data["data"]]
        if data.get("id") is not None:
            return [data]
    return []


def _gorgias_provision_id(data):
    recs = _gorgias_single_record(data)
    if recs and recs[0].get("id") not in (None, ""):
        return [recs[0]["id"]]
    return []


def _gorgias_ticket_id(auth_info, payload, conversation_id=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    tid = (
        conversation_id
        or payload.get("conversation_id")
        or payload.get("ticket_id")
        or auth_info.get("conversation_id")
        or auth_info.get("ticket_id")
    )
    return str(tid).strip() if tid not in (None, "") else None
