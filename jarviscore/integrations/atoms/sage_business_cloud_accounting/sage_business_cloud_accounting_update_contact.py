import requests
from typing import Any, Dict, List, Optional

def sage_business_cloud_accounting_update_contact(auth_info: dict, contact_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update contact. Official: https://developer.sage.com/accounting/reference/"""
    try:
        if not contact_id:
            return _sage_provision({}, 400, "contact_id is required", "contact", contact_id)
        if not isinstance(payload, dict) or not payload:
            return _sage_provision({}, 400, "payload is required", "contact", contact_id)
        body_payload = _sage_wrap(payload, "contact")
        resp, body, status, msg = _sage_write("PUT", f"/contacts/{contact_id}", base_url, auth_info, body_payload, timeout, verify_ssl)
        if status >= 400:
            return _sage_provision(body if isinstance(body, dict) else {}, status, msg, "contact", contact_id)
        return _sage_provision(body if isinstance(body, dict) else {}, status, "ok", "contact", contact_id)
    except Exception as e:
        return _sage_provision({}, 500, str(e), "contact", contact_id)


# Sage Business Cloud Accounting API v3.1 — Official docs: https://developer.sage.com/accounting/reference/


def _sage_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("sage_url") or auth_info.get("accounting_url") or auth_info.get("base_url") or "https://api.accounting.sage.com/v3.1").strip().rstrip("/")
    if not root.endswith("/v3.1"):
        if "/v3.1/" in root:
            root = root.split("/v3.1/")[0] + "/v3.1"
        elif not root.endswith("v3.1"):
            root = root + "/v3.1"
    return root, None


def _sage_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    t = str(token).strip()
    headers = {"Accept": "application/json", "Authorization": t if t.lower().startswith("bearer ") else f"Bearer {t}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    business = auth_info.get("business_id") or auth_info.get("resource_owner_id")
    if business not in (None, ""):
        headers["X-Business"] = str(business)
    return headers, None


def _sage_cap(limit):
    return min(max(int(limit or 25), 1), 200)


def _sage_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sage_provision(data, status, msg, wrapper, fallback_id=None):
    obj = _sage_entity_obj(data, wrapper) or (data if isinstance(data, dict) else {})
    pid = (obj.get("id") if isinstance(obj, dict) else None) or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _sage_entity_obj(body, wrapper):
    if not isinstance(body, dict):
        return {}
    inner = body.get(wrapper)
    if isinstance(inner, dict):
        return inner
    if body.get("id"):
        return body
    return {}


def _sage_items(body, wrapper=None):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        items = body.get("$items")
        if isinstance(items, list):
            return items
        if wrapper:
            inner = body.get(wrapper)
            if isinstance(inner, dict):
                return [inner]
        if body.get("id"):
            return [body]
    return []


def _sage_err(resp, body=None):
    if isinstance(body, dict):
        for key in ("$message", "message", "error", "error_description"):
            if body.get(key):
                return str(body.get(key))[:1000]
        errors = body.get("$errors") or body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get("message") or first.get("$message") or first)[:1000]
            return str(first)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _sage_next_url(root, body):
    if not isinstance(body, dict):
        return None
    nxt = body.get("$next")
    if not nxt:
        return None
    nxt = str(nxt)
    if nxt.startswith("http"):
        return nxt
    host = root.split("/v3.1")[0]
    if nxt.startswith("/v3.1"):
        return host + nxt
    if nxt.startswith("/"):
        return root + nxt
    return root + "/" + nxt


def _sage_get(path, base_url, auth_info, params, timeout, verify_ssl):
    headers, err = _sage_auth(auth_info)
    if err:
        return None, None, 401, err
    root, _ = _sage_root(base_url, auth_info)
    resp = requests.get(root + path, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _sage_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _sage_write(method, path, base_url, auth_info, json_body, timeout, verify_ssl):
    headers, err = _sage_auth(auth_info, json_body=True)
    if err:
        return None, None, 401, err
    root, _ = _sage_root(base_url, auth_info)
    resp = requests.request(method, root + path, headers=headers, json=json_body, timeout=timeout, verify=verify_ssl)
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _sage_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _sage_wrap(payload, wrapper):
    payload = payload if isinstance(payload, dict) else {}
    if wrapper in payload:
        return payload
    return {wrapper: payload}


def _sage_list_collection(path, base_url, auth_info, limit, timeout, verify_ssl, extra_params=None):
    cap = _sage_cap(limit)
    records = []
    params = {"items_per_page": min(cap, 200), "page": 1}
    if extra_params:
        params.update(extra_params)
    root, _ = _sage_root(base_url, auth_info)
    status = 200
    msg = "ok"
    pages = 0
    next_url = None
    while pages < 50 and len(records) < cap:
        pages += 1
        if next_url:
            headers, err = _sage_auth(auth_info)
            if err:
                return records, 401, err
            resp = requests.get(next_url, headers=headers, timeout=timeout, verify=verify_ssl)
            try:
                body = resp.json() if resp.content else {}
            except Exception:
                body = {}
            status = resp.status_code
            if status >= 400:
                return records, status, _sage_err(resp, body)
        else:
            resp, body, status, msg = _sage_get(path, base_url, auth_info, params, timeout, verify_ssl)
            if status >= 400:
                return records, status, msg
        for item in _sage_items(body):
            records.append(item)
            if len(records) >= cap:
                break
        next_url = _sage_next_url(root, body) if len(records) < cap else None
        if not next_url:
            break
    return records[:cap], status, msg
