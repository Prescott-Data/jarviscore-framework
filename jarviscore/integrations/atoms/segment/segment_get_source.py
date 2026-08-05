import requests
from typing import Any, Dict, List, Optional


def segment_get_source(auth_info: dict, source_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Segment Public API: get source. Official: https://segment.com/docs/api/public-api/#tag/Sources/operation/getSource"""
    try:
        if not source_id:
            return _sg_dataset([], 400, "source_id is required")
        root, _ = _sg_root(base_url, auth_info)
        headers, err = _sg_auth(auth_info)
        if err:
            return _sg_dataset([], 401, err)
        resp = requests.get(f"{root}/sources/{source_id}", headers=headers, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return _sg_dataset([], resp.status_code, _sg_err(resp))
        return _sg_dataset(_sg_single(data, "source"), resp.status_code, "ok")
    except Exception as e:
        return _sg_dataset([], 500, str(e))


# Segment Public API — Official docs: https://segment.com/docs/api/public-api/


def _sg_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("segment_url") or auth_info.get("base_url") or "https://api.segmentapis.com").strip().rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root, None


def _sg_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    headers = {"Accept": "application/json", "Authorization": "Bearer " + str(token).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


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


def _sg_single(data, key):
    if isinstance(data, dict):
        block = data.get("data")
        if isinstance(block, dict):
            inner = block.get(key)
            if isinstance(inner, dict):
                return [inner]
        inner = data.get(key)
        if isinstance(inner, dict):
            return [inner]
    return []
