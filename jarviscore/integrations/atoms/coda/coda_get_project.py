import requests
from typing import Any, Dict, List, Optional

CODA_API = "https://coda.io/apis/v1"


def coda_get_project(auth_info: dict, project_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get a Coda doc (catalog project) by doc id. Bearer API token in Authorization header. Official: https://coda.io/apis/v1"""
    try:
        if not project_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "project_id is required"}
        api = _coda_api_root(base_url)
        headers, auth_err = _coda_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = _coda_get(f"{api}/docs/{project_id}", headers, None, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        return {"records": [data] if isinstance(data, dict) else [], "data_count": 1 if isinstance(data, dict) else 0, "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}


# Coda API v1 — https://coda.io/apis/v1
def _coda_api_root(base_url):
    root = (base_url or CODA_API).rstrip("/")
    if "coda.io" in root and "/apis/v1" not in root:
        if root.endswith("/apis"):
            root = root + "/v1"
        else:
            root = root + "/apis/v1"
    return root


def _coda_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    if token:
        t = str(token).strip()
        headers["Authorization"] = t if t.lower().startswith("bearer ") else f"Bearer {t}"
        return headers, None
    return None, "auth_info requires api_key or access_token (Bearer)"


def _coda_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _coda_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _coda_put(url, headers, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _coda_patch(url, headers, body, timeout, verify_ssl):
    return requests.patch(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _coda_items(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return items
    return []


def _coda_paginate(url, headers, limit, timeout, verify_ssl):
    records = []
    page_token = None
    status = 0
    page_size = min(max(int(limit or 25), 1), 100)
    while len(records) < limit:
        params = {"pageSize": min(page_size, limit - len(records))}
        if page_token:
            params["pageToken"] = page_token
        resp = _coda_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = _coda_items(data)
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        page_token = data.get("nextPageToken") if isinstance(data, dict) else None
        if not batch or not page_token:
            break
    return records[:limit], status, "ok"


def _coda_row_context(auth_info, payload=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    doc_id = (
        payload.get("doc_id")
        or payload.get("docId")
        or payload.get("project_id")
        or auth_info.get("doc_id")
        or auth_info.get("docId")
        or auth_info.get("project_id")
    )
    table_id = (
        payload.get("table_id")
        or payload.get("tableId")
        or payload.get("table_name")
        or auth_info.get("table_id")
        or auth_info.get("tableId")
        or auth_info.get("table_name")
    )
    if not doc_id or not table_id:
        return None, None, (
            "Coda table rows require doc_id (catalog project_id) and table_id in auth_info "
            "or on payload. Endpoint: GET /docs/{docId}/tables/{tableIdOrName}/rows."
        )
    return str(doc_id), str(table_id), None


def _coda_filter_docs(docs, query):
    q = (query or "").strip().lower()
    if not q:
        return docs
    out = []
    for row in docs:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("title") or "").lower()
        did = str(row.get("id") or row.get("docId") or "").lower()
        if q in name or q == did:
            out.append(row)
    return out


def _coda_provision_ids(data):
    if not isinstance(data, dict):
        return []
    for key in ("id", "docId", "addedRowIds", "requestId"):
        val = data.get(key)
        if isinstance(val, list) and val:
            return [str(v) for v in val]
        if val not in (None, ""):
            return [str(val)]
    return []


def _coda_row_post_body(payload):
    if not isinstance(payload, dict) or not payload:
        return None
    if "rows" in payload:
        return payload
    cells = payload.get("cells") if isinstance(payload.get("cells"), dict) else payload
    return {"rows": [{"cells": cells}]}


def _coda_row_put_body(payload):
    if not isinstance(payload, dict) or not payload:
        return None
    if "row" in payload:
        return payload
    cells = payload.get("cells") if isinstance(payload.get("cells"), dict) else payload
    return {"row": {"cells": cells}}


def _coda_not_supported(catalog_path, real_hint):
    return {
        "records": [],
        "data_count": 0,
        "status": 501,
        "message": (
            f"Coda public API has no {catalog_path}. {real_hint} "
            "See https://coda.io/developers/apis/v1."
        ),
    }
