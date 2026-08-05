import requests
from typing import Any, Dict, List, Optional


def segment_create_destination(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Segment Public API: create destination. Official: https://segment.com/docs/api/public-api/#tag/Destinations/operation/createDestination"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _sg_provision({}, 400, "payload is required", "destination")
        root, _ = _sg_root(base_url, auth_info)
        headers, err = _sg_auth(auth_info, json_body=True)
        if err:
            return _sg_provision({}, 401, err, "destination")
        body = payload if "destination" in payload else {"destination": payload}
        resp = requests.post(f"{root}/destinations", headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            data = {}
        if resp.status_code >= 400:
            return _sg_provision(data, resp.status_code, _sg_err(resp), "destination")
        return _sg_provision(data, resp.status_code, "ok", "destination")
    except Exception as e:
        return _sg_provision({}, 500, str(e), "destination")


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


def _sg_provision(data, status, msg, wrap_key, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    inner = obj.get(wrap_key) if isinstance(obj.get(wrap_key), dict) else obj
    if not isinstance(inner, dict):
        inner = {}
    pid = inner.get("id") or inner.get("name") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = inner if inner else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


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
