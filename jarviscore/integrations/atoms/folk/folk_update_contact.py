import requests
from typing import Any, Dict, List, Optional

# Folk External API — https://developer.folk.app/api-reference/overview
_FOLK_API_HOST = "https://api.folk.app"


def folk_update_contact(auth_info: dict, contact_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update person (PATCH /v1/people/{personId} JSON body). Bearer API key in Authorization header per Folk External API. Official: https://developer.folk.app/"""
    try:
        if not contact_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "contact_id (personId) is required"}
        if not payload or not isinstance(payload, dict):
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required"}
        api, err = _folk_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _folk_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        person_id = str(contact_id).strip()
        resp = requests.patch(
            f"{api}/people/{person_id}",
            headers=headers,
            json=payload,
            timeout=timeout,
            verify=verify_ssl,
        )
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        records = _folk_single_record(data)
        return {
            "records": records,
            "data_count": len(records),
            "status": resp.status_code,
            "message": "ok",
            "provision_ids": _folk_provision_id(data),
        }
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _folk_api_root(base_url: str):
    root = (base_url or _FOLK_API_HOST).rstrip("/")
    if not root:
        return None, "base_url is required (https://api.folk.app)"
    if root.endswith("/v1"):
        root = root[:-3]
    if not root.endswith("folk.app"):
        return None, "base_url must be the Folk API root (https://api.folk.app)"
    return f"{root}/v1", None


def _folk_auth(auth_info, json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info requires access_token or api_key"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _folk_deal_scope(group_id, object_type, auth_info):
    auth_info = auth_info or {}
    gid = group_id or auth_info.get("group_id")
    otype = object_type or auth_info.get("object_type") or "Deals"
    if not gid:
        return None, None, "group_id is required for deals (or auth_info.group_id)"
    return str(gid).strip(), str(otype).strip(), None


def _folk_list_items(data):
    if not isinstance(data, dict):
        return [], None
    inner = data.get("data")
    if not isinstance(inner, dict):
        return [], None
    items = inner.get("items")
    batch = items if isinstance(items, list) else []
    pag = inner.get("pagination") if isinstance(inner.get("pagination"), dict) else {}
    nxt = pag.get("nextLink")
    return batch, nxt if isinstance(nxt, str) and nxt.startswith("http") else None


def _folk_single_record(data):
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return [data["data"]]
    return []


def _folk_paginate(url, headers, params, limit, timeout, verify_ssl):
    records = []
    cap = min(max(int(limit or 25), 1), 100)
    next_url = None
    status = 0
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        page_limit = min(cap - len(records), 100)
        req_params = None if next_url else dict(params or {})
        if req_params is not None:
            req_params["limit"] = page_limit
        resp = requests.get(
            next_url or url,
            headers=headers,
            params=req_params,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch, next_url = _folk_list_items(data)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= cap:
                    return records[:cap], status, "ok"
        if not next_url or len(batch) < page_limit:
            break
    return records[:cap], status, "ok"


def _folk_provision_id(data):
    recs = _folk_single_record(data)
    if recs and recs[0].get("id") not in (None, ""):
        return [str(recs[0]["id"])]
    return []
