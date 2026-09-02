import requests
from typing import Any, Dict, List, Optional

def shortcut_update_project(auth_info: dict, project_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Shortcut API v3: update project. Official: https://developer.shortcut.com/api/rest/v3#Projects/updateProject"""
    try:
        if not project_id: return _sc_provision({}, 400, "project_id is required")
        if not isinstance(payload, dict) or not payload: return _sc_provision({}, 400, "payload is required")
        root, _ = _sc_root(base_url, auth_info)
        headers, err = _sc_auth(auth_info, json_body=True)
        if err: return _sc_provision({}, 401, err)
        resp = requests.put(root + "/projects/" + str(project_id), headers=headers, json=payload, timeout=timeout, verify=verify_ssl)
        try: data = resp.json() if resp.content else {}
        except Exception: data = {}
        if resp.status_code >= 400: return _sc_provision(data if isinstance(data, dict) else {}, resp.status_code, _sc_err(resp))
        return _sc_provision(data if isinstance(data, dict) else {}, resp.status_code, "ok", fallback_id=project_id)
    except Exception as e: return _sc_provision({}, 500, str(e))


# Shortcut REST API v3 — Official docs: https://developer.shortcut.com/api/rest/v3


def _sc_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("shortcut_url") or auth_info.get("base_url") or "https://api.app.shortcut.com/api/v3").strip().rstrip("/")
    if not root.endswith("/v3"):
        if _host_is(root, "shortcut.com") and "/v3" not in root:
            root = root + "/api/v3" if "/api" not in root else root + "/v3"
    return root, None


def _sc_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.api_token is required"
    headers = {"Accept": "application/json", "Shortcut-Token": str(token).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _sc_cap(limit):
    return min(max(int(limit or 25), 1), 250)


def _sc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sc_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _sc_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error")
            if msg: return str(msg)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or "").strip()
    if "://" not in u:
        u = "https://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)
