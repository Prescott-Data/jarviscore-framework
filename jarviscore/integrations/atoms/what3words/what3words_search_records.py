import requests
from typing import Any, Dict, List, Optional

# what3words Public API — Official: https://developer.what3words.com/public-api/docs

_W3W_ROOT = "https://api.what3words.com/v3"


def what3words_search_records(auth_info: dict, query: str, limit: int = 5, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """what3words Public API: Search via autosuggest. Official: https://developer.what3words.com/public-api/docs"""
    try:
        root, _ = _w3w_root(base_url, auth_info)
        key, err = _w3w_key(auth_info)
        if err: return _w3w_dataset([], 401, err)
        if not query: return _w3w_dataset([], 400, "query is required")
        resp = requests.get(f"{root}/autosuggest", params={"input": query, "n-results": limit, "key": key}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _w3w_dataset([], resp.status_code, _w3w_err(resp))
        data = resp.json() if resp.content else {}
        suggestions = data.get("suggestions") if isinstance(data, dict) else []
        return _w3w_dataset(suggestions if isinstance(suggestions, list) else [], resp.status_code, "ok")
    except Exception as e: return _w3w_dataset([], 500, str(e))



def _w3w_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("what3words_url") or _W3W_ROOT).strip().rstrip("/")
    return root, None


def _w3w_key(auth_info):
    auth_info = auth_info or {}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info.api_key is required"
    return str(key).strip(), None


def _w3w_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _w3w_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
