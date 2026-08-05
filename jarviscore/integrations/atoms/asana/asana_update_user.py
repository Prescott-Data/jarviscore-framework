import requests
from typing import Any, Dict, List, Optional


def asana_update_user(auth_info: dict, user_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Update user via PUT /users/{user_gid}. Official: https://developers.asana.com/reference/updateuser"""
    try:
        if not user_id:
            return _asana_provision([], 400, "user_id is required")
        api_root, err = _asana_api_root(base_url)
        if err:
            return _asana_provision([], 400, err)
        headers, err = _asana_headers(auth_info, json_body=True)
        if err:
            return _asana_provision([], 401, err)
        resp = requests.put(
            f"{api_root}/users/{user_id}",
            headers=headers,
            json=_asana_wrap_data(payload),
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return _asana_provision([], status, _asana_err(resp))
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            return _asana_provision([], status, "invalid JSON response")
        obj = body.get("data") if isinstance(body, dict) else None
        records: List[Dict[str, Any]] = [obj] if isinstance(obj, dict) else []
        return _asana_provision(records, status, "ok", _asana_provision_ids(body, user_id))
    except Exception as e:
        return _asana_provision([], 500, str(e))


# PUT /users/{user_gid} — https://developers.asana.com/reference/updateuser
# Auth: Bearer token — https://developers.asana.com/docs/personal-access-token


def _asana_api_root(base_url):
    root = str(base_url or "").strip().rstrip("/")
    if root.endswith("/api/1.0"):
        return root, None
    if root.endswith("/api"):
        return root + "/1.0", None
    if root == "https://app.asana.com" or root.endswith("app.asana.com"):
        return root + "/api/1.0", None
    return None, "base_url must be https://app.asana.com/api/1.0"


def _asana_headers(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _asana_wrap_data(payload):
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload
    return {"data": payload or {}}


def _asana_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {
        "records": recs,
        "data_count": len(recs),
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _asana_provision_ids(body, fallback_id=None):
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        gid = body["data"].get("gid")
        if gid not in (None, ""):
            return [str(gid)]
    if fallback_id not in (None, ""):
        return [str(fallback_id)]
    return []


def _asana_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]
