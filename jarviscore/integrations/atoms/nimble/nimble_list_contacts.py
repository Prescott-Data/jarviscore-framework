import requests
from typing import Any, Dict, List, Optional

# Nimble REST API — Official docs: https://www.nimble.com/developers/docs/


NIMBLE_V1 = "https://api.nimble.com/api/v1"
NIMBLE_V2 = "https://api.nimble.com/api/v2"



# Contact list — GET /api/v1/contacts (page, per_page, meta.resources). Official: https://www.nimble.com/developers/docs/


def nimble_list_contacts(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List contacts (page/per_page, resources). Official: https://www.nimble.com/developers/docs/"""
    try:
        root, err = _nb_v1_root(base_url)
        if err:
            return _nb_dataset([], 400, err)
        headers, aerr = _nb_auth(auth_info)
        if aerr:
            return _nb_dataset([], 401, aerr)
        auth_info = auth_info or {}
        params = {"record_type": str(auth_info.get("record_type") or "all")}
        if auth_info.get("keyword"):
            params["keyword"] = str(auth_info.get("keyword"))
        if auth_info.get("tags") is not None:
            params["tags"] = auth_info.get("tags")
        records, status, msg = _nb_paginate(f"{root}/contacts", headers, params, limit, timeout, verify_ssl)
        return _nb_dataset(records, status, msg)
    except Exception as e:
        return _nb_dataset([], 500, str(e))



def _nb_v1_root(base_url):
    root = (base_url or NIMBLE_V1).rstrip("/")
    if "nimble.com" not in root:
        return None, "base_url must be https://api.nimble.com/api/v1 or https://app.nimble.com/api/v1"
    if root.endswith("nimble.com"):
        root = root + "/api/v1"
    elif "/api/v2" in root:
        root = root.replace("/api/v2", "/api/v1")
    elif not root.endswith("/api/v1"):
        if "/api/" not in root:
            root = root + "/api/v1"
    return root, None


def _nb_v2_root(base_url):
    v1, err = _nb_v1_root(base_url)
    if err:
        return None, err
    return v1.replace("/api/v1", "/api/v2"), None


def _nb_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {str(token).strip()}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _nb_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _nb_error(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error") or data.get("status")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _nb_dataset(records, status, msg):
    return {"records": records, "data_count": len(records), "status": status, "message": msg}


def _nb_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("deal_id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    records = [obj] if obj else ([{"id": pid}] if ids else [])
    return {"records": records, "data_count": len(records), "status": status, "message": msg, "provision_ids": ids}


def _nb_resources(data):
    if isinstance(data, dict):
        res = data.get("resources")
        if isinstance(res, list):
            if res and isinstance(res[0], dict):
                return [x for x in res if isinstance(x, dict)]
            return [{"id": x} for x in res if x not in (None, "")]
        if data.get("id") or data.get("deal_id"):
            return [data]
    return []


def _nb_paginate(url, headers, base_params, limit, timeout, verify_ssl):
    cap = _nb_cap(limit)
    page = int((base_params or {}).get("page") or 1)
    records = []
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        params = dict(base_params or {})
        params["page"] = page
        params["per_page"] = min(int(params.get("per_page") or 30), cap - len(records), 100)
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, _nb_error(resp)
        try:
            data = resp.json()
        except Exception:
            return records, status, resp.text[:1000]
        batch = _nb_resources(data)
        records.extend(batch)
        meta = data.get("meta") if isinstance(data, dict) else {}
        total_pages = meta.get("pages") if isinstance(meta, dict) else None
        cur = meta.get("page") if isinstance(meta, dict) else page
        if not batch or (total_pages is not None and cur >= total_pages):
            break
        page = int(cur) + 1 if isinstance(cur, int) else page + 1
    return records[:cap], status, "ok"


def _nb_paginate_deals(url, headers, base_params, limit, timeout, verify_ssl):
    cap = _nb_cap(limit)
    page = int((base_params or {}).get("page") or 1)
    records = []
    status = 200
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        params = dict(base_params or {})
        params["limit"] = min(int(params.get("limit") or 30), cap - len(records), 100)
        if (base_params or {}).get("sort"):
            params["sort"] = base_params["sort"]
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, _nb_error(resp)
        try:
            data = resp.json()
        except Exception:
            return records, status, resp.text[:1000]
        batch = _nb_resources(data)
        records.extend(batch)
        meta = data.get("meta") if isinstance(data, dict) else {}
        total_pages = meta.get("pages") if isinstance(meta, dict) else None
        cur = meta.get("page") if isinstance(meta, dict) else page
        if not batch or (total_pages is not None and cur >= total_pages):
            break
        page = int(cur) + 1 if isinstance(cur, int) else page + 1
    return records[:cap], status, "ok"


def _nb_get_one(url, headers, timeout, verify_ssl):
    resp = requests.get(url, headers=headers, timeout=timeout, verify=verify_ssl)
    status = resp.status_code
    if status >= 400:
        return [], status, _nb_error(resp)
    try:
        data = resp.json()
    except Exception:
        return [], status, resp.text[:1000]
    recs = _nb_resources(data)
    if not recs and isinstance(data, dict) and (data.get("deal_id") or data.get("id")):
        recs = [data]
    return recs, status, "ok"
