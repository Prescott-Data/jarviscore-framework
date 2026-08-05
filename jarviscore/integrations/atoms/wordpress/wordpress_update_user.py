import requests
from typing import Any, Dict, List, Optional

def wordpress_update_user(auth_info: dict, user_id: str, title: str = '', limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """wordpress REST: update user. Official: https://developer.wordpress.org/rest-api/"""
    try:
        root, err = _root(base_url, auth_info)
        if err: return _provision({}, 400, err)
        if not user_id: return _provision({}, 400, 'user_id is required')
        headers, aerr = _auth(auth_info)
        if isinstance(headers, str) or aerr: return _provision({}, 401, aerr or headers)
        auth = headers if isinstance(headers, tuple) else None
        hdrs = headers if isinstance(headers, dict) else {'Accept':'application/json'}
        payload = {'title': title} if title else {}
        resp = requests.put(root + "/users/" + str(user_id), headers=hdrs, auth=auth, json=payload, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _provision({}, resp.status_code, _err(resp))
        data = resp.json() if resp.content else {}
        return _provision(data if isinstance(data, dict) else {}, resp.status_code, 'ok', fallback_id=user_id)
    except Exception as e: return _provision({}, 500, str(e))


# wordpress REST API — Official: https://developer.wordpress.org/rest-api/


def _root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("base_url") or "https://example.com/wp-json/wp/v2").strip().rstrip("/")
    if not root:
        return None, "base_url is required"
    return root, None


def _auth(auth_info):
    auth_info = auth_info or {}
    username = auth_info.get("username")
    password = auth_info.get("password")
    if username and password:
        return (str(username), str(password)), None
    return None, "auth_info requires username and password"


def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _err(resp):
    return (resp.text or ("HTTP " + str(resp.status_code)))[:1000]
