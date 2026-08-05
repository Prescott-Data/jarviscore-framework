import requests
from typing import Any, Dict, List, Optional

def zendesk_chat_create_agent(auth_info: dict, name: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """zendesk_chat REST: create agent. Official: https://developer.zendesk.com/api-reference/live-chat/introduction/"""
    try:
        root, err = _root(base_url, auth_info)
        if err: return _provision({}, 400, err)
        headers, aerr = _auth(auth_info)
        if aerr: return _provision({}, 401, aerr)
        headers["Content-Type"] = "application/json"
        email = (auth_info or {}).get("email")
        password = (auth_info or {}).get("password")
        if not email or not password:
            return _provision({}, 400, "auth_info.email and auth_info.password are required to create an agent")
        body = {"display_name": name, "email": email, "password": password}
        resp = requests.post(root + "/agents", headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _provision({}, resp.status_code, _err(resp))
        data = resp.json() if resp.content else {}
        return _provision(data if isinstance(data, dict) else {}, resp.status_code, 'ok')
    except Exception as e: return _provision({}, 500, str(e))


# zendesk_chat REST API — Official: https://developer.zendesk.com/api-reference/live-chat/introduction/


def _root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        sub = auth_info.get("subdomain") or auth_info.get("account")
        if sub:
            root = "https://" + str(sub).strip() + ".zendesk.com/api/v2/chat"
    if not root:
        return None, "base_url or auth_info.subdomain is required"
    return root, None


def _auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    tok = str(token).strip()
    return {"Authorization": tok if tok.lower().startswith("bearer ") else f"Bearer {tok}", "Accept": "application/json"}, None


def _dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("Id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
