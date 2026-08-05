import requests
from typing import Any, Dict, List, Optional


def segment_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Segment Public API: search records. Official: https://segment.com/docs/api/public-api/"""
    try:
        if not query:
            return _sg_dataset([], 400, "query is required")
        root, _ = _sg_root(base_url, auth_info)
        cap = _sg_cap(limit)
        records = []
        for path, key in (("/sources", "sources"), ("/destinations", "destinations")):
            batch, status, msg = _sg_fetch_all(root + path, auth_info, key, cap, timeout, verify_ssl)
            if status == 401:
                return _sg_dataset([], 401, msg)
            for item in batch:
                row = dict(item)
                row["_segment_type"] = key[:-1]
                if _sg_match(row, query):
                    records.append(row)
                    if len(records) >= cap:
                        return _sg_dataset(records[:cap], 200, "ok")
        return _sg_dataset(records[:cap], 200, "ok")
    except Exception as e:
        return _sg_dataset([], 500, str(e))


# Segment Public API — Official docs: https://segment.com/docs/api/public-api/


def _sg_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("segment_url") or auth_info.get("base_url") or "https://api.segmentapis.com").strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root, None


def _sg_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    return {"Accept": "application/json", "Authorization": "Bearer " + str(token).strip()}, None


def _sg_cap(limit):
    return min(max(int(limit or 25), 1), 200)


def _sg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sg_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error")
            if msg:
                return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _sg_items(data, key):
    if isinstance(data, dict):
        block = data.get("data")
        if isinstance(block, dict):
            items = block.get(key)
            if isinstance(items, list):
                return [x for x in items if isinstance(x, dict)]
    return []


def _sg_fetch_all(url, auth_info, collection_key, limit, timeout, verify_ssl):
    cap = _sg_cap(limit)
    records = []
    next_url = url
    params = {"pagination[count]": min(cap, 200)}
    pages = 0
    while len(records) < cap and pages < 50:
        pages += 1
        headers, err = _sg_auth(auth_info)
        if err:
            return records, 401, err
        resp = requests.get(next_url, headers=headers, params=params if pages == 1 else None, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return records, resp.status_code, _sg_err(resp)
        batch = _sg_items(data, collection_key)
        records.extend(batch)
        pagination = data.get("pagination") if isinstance(data, dict) else {}
        nxt = pagination.get("next") if isinstance(pagination, dict) else None
        if not nxt or not batch:
            break
        next_url = nxt if str(nxt).startswith("http") else url
        params = None
    return records[:cap], 200, "ok"


def _sg_match(record, query):
    q = str(query).lower()
    for key in ("id", "name", "slug", "description", "enabled", "type"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
