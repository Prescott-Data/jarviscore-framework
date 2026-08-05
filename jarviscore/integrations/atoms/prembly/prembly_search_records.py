import requests
from typing import Any, Dict, List, Optional


def prembly_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search check types by country with client-side name filter. Official: https://docs.prembly.com/reference/list-check-types-by-country"""
    try:
        if not query:
            return _pm_dataset([], 400, "query is required")
        root, err = _pm_root(base_url, auth_info)
        if err:
            return _pm_dataset([], 400, err)
        auth_info = auth_info or {}
        cap = _pm_cap(limit)
        records = []
        country = auth_info.get("country") or auth_info.get("country_code")
        if country:
            resp, body, status, msg = _pm_request(
                "get",
                root + "/api/v1/api/bgc/country/check-types/",
                auth_info,
                params={"country_code": country},
                timeout=timeout,
                verify_ssl=verify_ssl,
            )
            if status < 400:
                records.extend(_pm_rows(body))
        resp, body, status, msg = _pm_request("get", root + "/api/v1/api/bgc/check-types/", auth_info, timeout=timeout, verify_ssl=verify_ssl)
        if status < 400:
            records.extend(_pm_rows(body))
        filtered = [r for r in records if _pm_match(r, query)]
        return _pm_dataset(filtered[:cap], 200 if filtered else status, "ok" if filtered else msg)
    except Exception as e:
        return _pm_dataset([], 500, str(e))


# Prembly Identity Verification API — Official docs: https://docs.prembly.com/doc/


def _pm_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("prembly_url") or auth_info.get("base_url") or "https://api.prembly.com").strip().rstrip("/")
    return root, None


def _pm_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info.api_key is required"
    headers = {"x-api-key": str(key).strip(), "Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _pm_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _pm_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pm_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    ver = obj.get("verification") if isinstance(obj.get("verification"), dict) else {}
    pid = (
        ver.get("verification_id")
        or ver.get("reference")
        or obj.get("id")
        or (obj.get("data") or {}).get("id") if isinstance(obj.get("data"), dict) else None
        or fallback_id
    )
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pm_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("message") or body.get("detail") or body.get("error")
        if err and not isinstance(err, (list, dict)):
            return str(err)[:1000]
        if isinstance(err, list):
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _pm_rows(body):
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if isinstance(body, dict):
        for key in ("detail", "data", "results"):
            val = body.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        if isinstance(body.get("data"), dict):
            return [body["data"]]
        return [body]
    return []


def _pm_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _pm_auth(auth_info, json_body=(json_body is not None))
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
        return resp, body, resp.status_code, _pm_err(resp, body)
    if isinstance(body, dict) and body.get("status") is False:
        return resp, body, 400, _pm_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _pm_verification_path(auth_info, payload=None):
    auth_info = auth_info or {}
    path = auth_info.get("verification_path") or auth_info.get("endpoint")
    if isinstance(payload, dict):
        path = payload.get("verification_path") or payload.get("endpoint") or path
    path = (path or "verification/nin-level-2").strip().lstrip("/")
    return path


def _pm_match(record, query):
    q = str(query).lower()
    for key in ("id", "name", "endpoint", "check_type", "reference", "verification_status"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
