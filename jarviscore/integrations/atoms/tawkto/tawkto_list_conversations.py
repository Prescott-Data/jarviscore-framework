import requests
from typing import Any, Dict, List, Optional


def tawkto_list_conversations(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Tawk.to REST: list chats. Official: https://developer.tawk.to/rest-api/"""
    try:
        root, _ = _tk_root(base_url, auth_info)
        pid, err = _tk_property(auth_info)
        if err: return _tk_dataset([], 400, err)
        headers, aerr = _tk_auth(auth_info)
        if aerr: return _tk_dataset([], 401, aerr)
        key = str((auth_info or {}).get("api_key") or "").strip()
        resp = requests.post(f"{root}/v1/chat.list", headers=headers, auth=(key, ""), json={"propertyId": pid, "size": limit}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _tk_dataset([], resp.status_code, _tk_err(resp))
        data = resp.json() if resp.content else {}
        records = data if isinstance(data, list) else (data.get("data") or data.get("chats") or [])
        if not isinstance(records, list): records = [records] if records else []
        return _tk_dataset(records[:limit], resp.status_code, "ok")
    except Exception as e: return _tk_dataset([], 500, str(e))


# Tawk.to REST API — Official: https://docs.tawk.to/ (RPC-style POST, HTTP Basic auth)


def _tk_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("tawkto_url") or "https://api.tawk.to").strip().rstrip("/")
    return root, None


def _tk_auth(auth_info):
    auth_info = auth_info or {}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info.api_key is required"
    # tawk.to REST API uses HTTP Basic auth: API key as username, empty password.
    return {"Accept": "application/json", "Content-Type": "application/json"}, None


def _tk_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _tk_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _tk_property(auth_info):
    auth_info = auth_info or {}
    pid = auth_info.get("property_id") or auth_info.get("propertyId")
    if not pid:
        return None, "auth_info.property_id is required"
    return str(pid), None
