import requests
from typing import Any, Dict, List, Optional

def sage_pastel_list_contacts(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List customers (contacts). Official: https://accounting.sageone.co.za/api/2.0.0/Help"""
    try:
        records, status, msg = _pt_list("Customer", base_url, auth_info, limit, timeout, verify_ssl)
        return _pt_dataset(records, status, msg)
    except Exception as e:
        return _pt_dataset([], 500, str(e))


# Sage Business Cloud Accounting South Africa (Sage One) API v2.0.0 — Official: https://accounting.sageone.co.za/api/2.0.0/Help


def _pt_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("sageone_url") or auth_info.get("pastel_url") or auth_info.get("base_url") or "https://accounting.sageone.co.za/api/2.0.0").strip().rstrip("/")
    if "/api/" in root and not root.endswith("2.0.0"):
        if "2.0.0" not in root:
            root = root.split("/api/")[0] + "/api/2.0.0"
    elif "accounting.sageone.co.za" in root and "/api/" not in root:
        root = root + "/api/2.0.0"
    return root, None


def _pt_query(auth_info, extra=None):
    auth_info = auth_info or {}
    params = {}
    apikey = auth_info.get("api_key")
    company = auth_info.get("company_id")
    if not apikey:
        return None, "auth_info.api_key is required"
    params["apikey"] = str(apikey)
    if company not in (None, ""):
        params["companyid"] = str(company)
    if extra:
        params.update(extra)
    return params, None


def _pt_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    user = auth_info.get("username")
    password = auth_info.get("password")
    if not user or password is None:
        return None, "auth_info requires username and password"
    import base64
    creds = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    headers["Authorization"] = f"Basic {creds}"
    return headers, None


def _pt_cap(limit):
    return min(max(int(limit or 25), 1), 100)


def _pt_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pt_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("ID") or obj.get("Id") or obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"ID": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pt_items(body):
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("Results", "results", "Items", "items", "Data", "data"):
            val = body.get(key)
            if isinstance(val, list):
                return val
        if body.get("ID") is not None or body.get("Id") is not None:
            return [body]
    return []


def _pt_err(resp, body=None):
    if isinstance(body, dict):
        for key in ("Message", "message", "Error", "error", "ErrorMessage"):
            if body.get(key):
                return str(body.get(key))[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _pt_get(service, base_url, auth_info, path_suffix, extra_params, timeout, verify_ssl):
    headers, err = _pt_auth(auth_info)
    if err:
        return None, None, 401, err
    params, err = _pt_query(auth_info, extra_params)
    if err:
        return None, None, 401, err
    root, _ = _pt_root(base_url, auth_info)
    path = f"/{service}/Get"
    if path_suffix:
        path += f"/{path_suffix}"
    resp = requests.get(root + path, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _pt_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _pt_save(service, base_url, auth_info, payload, timeout, verify_ssl, extra_params=None):
    headers, err = _pt_auth(auth_info, json_body=True)
    if err:
        return None, None, 401, err
    params, err = _pt_query(auth_info, extra_params)
    if err:
        return None, None, 401, err
    root, _ = _pt_root(base_url, auth_info)
    resp = requests.post(root + f"/{service}/Save", headers=headers, params=params, json=payload, timeout=timeout, verify=verify_ssl)
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _pt_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _pt_list(service, base_url, auth_info, limit, timeout, verify_ssl, extra_params=None):
    cap = _pt_cap(limit)
    records = []
    skip = 0
    page_size = min(cap, 100)
    status = 200
    msg = "ok"
    while len(records) < cap:
        params = {"$skip": skip, "$top": min(page_size, cap - len(records)), "$orderby": "ID"}
        if extra_params:
            params.update(extra_params)
        resp, body, status, msg = _pt_get(service, base_url, auth_info, None, params, timeout, verify_ssl)
        if status >= 400:
            return records, status, msg
        chunk = _pt_items(body)
        if not chunk:
            break
        for item in chunk:
            records.append(item)
            if len(records) >= cap:
                break
        if len(chunk) < min(page_size, cap - len(records) + len(chunk)):
            break
        skip += len(chunk)
        if skip > 5000:
            break
    return records[:cap], status, msg


def _pt_match(record, query):
    if not isinstance(record, dict):
        return False
    q = str(query).lower()
    for field in ("Name", "DocumentNumber", "Reference", "Email", "ContactName", "Payee", "Description"):
        val = record.get(field)
        if val is not None and q in str(val).lower():
            return True
    rid = record.get("ID") or record.get("Id")
    if rid is not None and q == str(rid).lower():
        return True
    return False
