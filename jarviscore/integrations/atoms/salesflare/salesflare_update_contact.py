import requests
from typing import Any, Dict, List, Optional

def salesflare_update_contact(auth_info: dict, contact_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update contact. Official: https://api.salesflare.com/docs"""
    try:
        if not contact_id:
            return _sf_provision({}, 400, "contact_id is required")
        if not isinstance(payload, dict) or not payload:
            return _sf_provision({}, 400, "payload is required", contact_id)
        resp, body, status, msg = _sf_request("PUT", f"/contacts/{contact_id}", base_url, auth_info, None, payload, timeout, verify_ssl)
        if status >= 400:
            return _sf_provision(body if isinstance(body, dict) else {}, status, msg, contact_id)
        return _sf_provision(body if isinstance(body, dict) else {}, status, "ok", contact_id)
    except Exception as e:
        return _sf_provision({}, 500, str(e), contact_id)


# Salesflare REST API — Official docs: https://api.salesflare.com/docs


def _sf_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("salesflare_url") or auth_info.get("base_url") or "https://api.salesflare.com").strip().rstrip("/")
    return root, None


def _sf_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.api_key or access_token is required"
    t = str(token).strip()
    headers = {"Accept": "application/json", "Authorization": t if t.lower().startswith("bearer ") else f"Bearer {t}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _sf_cap(limit):
    return min(max(int(limit or 25), 1), 200)


def _sf_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sf_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("ID") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _sf_items(body, collection_key):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        val = body.get(collection_key)
        if isinstance(val, list):
            return val
        if body.get("id") is not None:
            return [body]
    return []


def _sf_err(resp, body=None):
    if isinstance(body, dict):
        for key in ("message", "error", "errorMessage", "detail"):
            if body.get(key):
                return str(body.get(key))[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _sf_request(method, path, base_url, auth_info, params, json_body, timeout, verify_ssl):
    headers, err = _sf_auth(auth_info, json_body=json_body is not None)
    if err:
        return None, None, 401, err
    root, _ = _sf_root(base_url, auth_info)
    resp = requests.request(method, root + path, headers=headers, params=params, json=json_body, timeout=timeout, verify=verify_ssl)
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _sf_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _sf_list(path, collection_key, base_url, auth_info, limit, timeout, verify_ssl, extra_params=None):
    cap = _sf_cap(limit)
    records = []
    offset = 0
    page_size = min(cap, 100)
    status = 200
    msg = "ok"
    while len(records) < cap:
        params = {"limit": min(page_size, cap - len(records)), "offset": offset}
        if extra_params:
            params.update(extra_params)
        resp, body, status, msg = _sf_request("GET", path, base_url, auth_info, params, None, timeout, verify_ssl)
        if status >= 400:
            return records, status, msg
        chunk = _sf_items(body, collection_key)
        if not chunk:
            break
        for item in chunk:
            records.append(item)
            if len(records) >= cap:
                break
        if len(chunk) < min(page_size, cap - len(records) + len(chunk)):
            break
        offset += len(chunk)
        if offset > 10000:
            break
    return records[:cap], status, msg
