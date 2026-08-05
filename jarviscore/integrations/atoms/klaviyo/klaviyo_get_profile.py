import requests
from typing import Any, Dict, Optional

# Klaviyo API — https://developers.klaviyo.com/en/reference/get_profile
KLAVIYO_API = "https://a.klaviyo.com"
KL_REVISION = "2024-10-15"


def klaviyo_get_profile(auth_info: dict, profile_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get profile in klaviyo. Official: https://developers.klaviyo.com/en/reference/profiles_api_overview"""
    try:
        if not profile_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "profile_id is required"}
        api, err = _kv_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _kv_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = _kv_get(f"{api}/api/profiles/{profile_id}/", headers, None, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        records = _kv_jsonapi_records(resp.json() if resp.text else {})
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _kv_api_root(base_url):
    root = (base_url or KLAVIYO_API).rstrip("/")
    if "klaviyo.com" not in root:
        return None, "base_url must be https://a.klaviyo.com"
    return root, None


def _kv_auth(auth_info):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "revision": KL_REVISION}
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info requires api_key"
    k = str(key).strip()
    headers["Authorization"] = k if k.lower().startswith("klaviyo-api-key ") else f"Klaviyo-API-Key {k}"
    return headers, None


def _kv_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _kv_jsonapi_records(data):
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            return [d]
    return []
