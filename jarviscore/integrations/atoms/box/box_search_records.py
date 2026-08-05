import requests
from typing import Any, Dict, List, Optional


def box_search_records(auth_info: dict, query: str, timeout: int = 30, verify_ssl: bool = True, limit: int = 25, base_url: str = None) -> dict:
    """Search for files and folders (GET /search). Official: https://developer.box.com/reference/get-search/"""
    try:
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
        headers, auth_err = _box_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        api = _box_api_root(base_url)
        records, status, message = _box_paginate_items(f"{api}/search", headers, limit, timeout, verify_ssl, {"query": query})
        return {"records": records, "data_count": len(records), "status": status, "message": message}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}


def _pct_enc(text, safe=""):
    out = []
    for ch in str(text):
        o = ord(ch)
        if ch in safe or (o < 128 and (ch.isalnum() or ch in "-_.~")):
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append(f"%{b:02X}")
    return "".join(out)


def _parse_url(url):
    scheme, rest = ("", url)
    if "://" in url:
        scheme, rest = url.split("://", 1)
    fragment = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    if "/" in rest:
        netloc, path = rest.split("/", 1)
        path = "/" + path
    else:
        netloc, path = rest, "/"
    return scheme, netloc, path, query, fragment


def _build_url(scheme, netloc, path, query="", fragment=""):
    url = f"{scheme}://{netloc}{path or '/'}"
    if query:
        url += "?" + query
    if fragment:
        url += "#" + fragment
    return url


def _query_pairs(query):
    pairs = []
    for part in (query or "").split("&"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
        else:
            k, v = part, ""
        pairs.append((k, v))
    return pairs


def _query_get(url, name):
    _, _, _, query, _ = _parse_url(url)
    for k, v in _query_pairs(query):
        if k == name:
            return v
    return None


def _urlencode(params):
    return "&".join(f"{_pct_enc(str(k))}={_pct_enc(str(v))}" for k, v in params.items())


def _json_escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _json_dumps(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{_json_escape(value)}"'
    if isinstance(value, dict):
        parts = [f'"{_json_escape(k)}": {_json_dumps(v)}' for k, v in value.items()]
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_json_dumps(v) for v in value) + "]"
    return f'"{_json_escape(str(value))}"'


def _basename(path):
    p = str(path).replace("\\", "/")
    return p.rsplit("/", 1)[-1] if p else ""


def _guess_mime(path):
    ext = _basename(path).rsplit(".", 1)[-1].lower() if "." in _basename(path) else ""
    return {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "txt": "text/plain",
        "csv": "text/csv",
        "json": "application/json",
        "html": "text/html",
        "xml": "application/xml",
        "zip": "application/zip",
    }.get(ext, "application/octet-stream")

# Box API v2 — https://developer.box.com/reference/
BOX_API = "https://api.box.com/2.0"
BOX_UPLOAD = "https://upload.box.com/api/2.0"


def _box_api_root(base_url):
    root = (base_url or BOX_API).rstrip("/")
    if not root.endswith("/2.0"):
        if root.endswith("/2"):
            root = root + ".0"
        elif not root.endswith("/2.0"):
            root = root + "/2.0" if "box.com" in root else BOX_API
    return root


def _box_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _box_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _box_post_json(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _box_put_json(url, headers, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _box_paginate_items(url, headers, limit, timeout, verify_ssl, extra=None):
    records = []
    offset = 0
    status = 0
    extra = extra or {}
    page_size = min(max(limit, 1), 1000)
    while len(records) < limit:
        params = {"limit": min(page_size, limit - len(records)), "offset": offset}
        params.update(extra)
        resp = _box_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = data.get("entries") or []
        for item in batch:
            if isinstance(item, dict):
                records.append(item)
                if len(records) >= limit:
                    break
        total = data.get("total_count")
        offset += len(batch)
        if not batch or (total is not None and offset >= total):
            break
        if offset > 100000:
            break
    return records[:limit], status, "ok"


def _box_paginate_typed_items(url, headers, limit, timeout, verify_ssl, item_type, extra=None):
    records = []
    offset = 0
    status = 0
    extra = extra or {}
    page_size = min(max(limit, 1), 1000)
    while len(records) < limit:
        params = {"limit": min(page_size, max(limit * 2, 25)), "offset": offset}
        params.update(extra)
        resp = _box_get(url, headers, params, timeout, verify_ssl)
        status = resp.status_code
        if status >= 400:
            return records, status, resp.text[:1000]
        data = resp.json() if resp.text else {}
        batch = data.get("entries") or []
        for item in batch:
            if isinstance(item, dict) and item.get("type") == item_type:
                records.append(item)
                if len(records) >= limit:
                    break
        total = data.get("total_count")
        offset += len(batch)
        if not batch or (total is not None and offset >= total):
            break
        if offset > 100000:
            break
    return records[:limit], status, "ok"
