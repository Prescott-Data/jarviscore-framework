import requests
from typing import Any, Dict, List, Optional


def pipedrive_list_deals(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List deals with cursor pagination. Official: https://developers.pipedrive.com/docs/api/v1/Deals"""
    try:
        auth_info = auth_info or {}
        extra = auth_info.get("filters") or auth_info.get("params")
        if not isinstance(extra, dict):
            extra = {}
        records, status, msg = _pi_list("/deals", base_url, auth_info, limit, timeout, verify_ssl, extra_params=extra)
        return _pi_dataset(records, status, msg)
    except Exception as e:
        return _pi_dataset([], 500, str(e))


# Pipedrive REST API v2 — Official docs: https://developers.pipedrive.com/docs/api/v1/


def _pi_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("pipedrive_url") or auth_info.get("company_domain") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required (https://company.pipedrive.com)"
    if root.startswith("http") and ".pipedrive.com" in root and "/api/" not in root:
        root = root + "/api/v2"
    elif "/api/v1" in root:
        root = root.replace("/api/v1", "/api/v2")
    elif "/api/v" not in root:
        root = root + "/api/v2"
    return root, None


def _pi_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    access_token = auth_info.get("access_token")
    if not access_token:
        return None, "auth_info.access_token is required"
    headers["Authorization"] = "Bearer " + str(access_token).strip()
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _pi_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _pi_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _pi_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _pi_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("error") or body.get("error_info")
        if err:
            return str(err)[:1000]
    try:
        if resp is not None:
            data = resp.json()
            if isinstance(data, dict):
                err = data.get("error") or data.get("error_info")
                if err:
                    return str(err)[:1000]
    except Exception:
        pass
    return (resp.text if resp is not None else "request failed")[:1000]


def _pi_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _pi_search_items(data):
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            out = []
            for entry in items:
                if not isinstance(entry, dict):
                    continue
                item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
                row = dict(item)
                if entry.get("item_type"):
                    row["item_type"] = entry.get("item_type")
                if entry.get("result_score") is not None:
                    row["result_score"] = entry.get("result_score")
                out.append(row)
            return out
        return [data]
    return []


def _pi_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _pi_auth(auth_info, json_body=(json_body is not None))
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
        return resp, body, resp.status_code, _pi_err(resp, body)
    if isinstance(body, dict) and body.get("success") is False:
        return resp, body, 400, _pi_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _pi_list(path, base_url, auth_info, limit, timeout, verify_ssl, extra_params=None):
    root, err = _pi_root(base_url, auth_info)
    if err:
        return [], 400, err
    cap = _pi_cap(limit)
    records = []
    cursor = None
    status = 200
    msg = "ok"
    auth_info = auth_info or {}
    while len(records) < cap:
        params = dict(extra_params or {})
        params["limit"] = min(500, cap - len(records))
        if cursor:
            params["cursor"] = cursor
        resp, body, status, msg = _pi_request("get", root + path, auth_info, params=params, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return records[:cap], status, msg
        batch = _pi_items(body.get("data") if isinstance(body, dict) else None)
        records.extend(batch)
        add = body.get("additional_data") if isinstance(body, dict) else {}
        cursor = add.get("next_cursor") if isinstance(add, dict) else None
        if not cursor or not batch:
            break
    return records[:cap], status, msg


def _pi_get(path, base_url, auth_info, obj_id, timeout, verify_ssl):
    if not obj_id:
        return [], 400, "id is required"
    root, err = _pi_root(base_url, auth_info)
    if err:
        return [], 400, err
    resp, body, status, msg = _pi_request("get", root + path + "/" + str(obj_id).strip(), auth_info, timeout=timeout, verify_ssl=verify_ssl)
    if status >= 400:
        return [], status, msg
    return _pi_items(body.get("data") if isinstance(body, dict) else None), status, msg


def _pi_write(method, path, base_url, auth_info, payload, obj_id=None, timeout=30, verify_ssl=True):
    root, err = _pi_root(base_url, auth_info)
    if err:
        return {}, 400, err
    if not isinstance(payload, dict) or not payload:
        return {}, 400, "payload is required"
    url = root + path + ("/" + str(obj_id).strip() if obj_id else "")
    resp, body, status, msg = _pi_request(method, url, auth_info, json_body=payload, timeout=timeout, verify_ssl=verify_ssl)
    if status >= 400:
        return body if isinstance(body, dict) else {}, status, msg
    data = body.get("data") if isinstance(body, dict) else {}
    return data if isinstance(data, dict) else {}, status, "ok"
