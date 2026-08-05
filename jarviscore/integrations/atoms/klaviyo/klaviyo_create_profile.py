import requests
from typing import Any, Dict, Optional

# Klaviyo API — https://developers.klaviyo.com/en/reference/create_profile
KLAVIYO_API = "https://a.klaviyo.com"
KL_REVISION = "2024-10-15"


def klaviyo_create_profile(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create profile in klaviyo. Official: https://developers.klaviyo.com/en/reference/profiles_api_overview"""
    try:
        if not payload:
            return {"records": [], "data_count": 0, "status": 400, "message": "payload is required", "provision_ids": []}
        api, err = _kv_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        headers, auth_err = _kv_auth(auth_info, json_body=True)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err, "provision_ids": []}
        body = payload if isinstance(payload.get("data"), dict) else {"data": {"type": "profile", "attributes": payload}}
        resp = _kv_post(f"{api}/api/profiles/", headers, body, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000], "provision_ids": []}
        data = resp.json() if resp.text else {}
        records = _kv_jsonapi_records(data)
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok", "provision_ids": _kv_provision_id(data)}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _kv_api_root(base_url):
    root = (base_url or KLAVIYO_API).rstrip("/")
    if "klaviyo.com" not in root:
        return None, "base_url must be https://a.klaviyo.com"
    return root, None


def _kv_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "revision": KL_REVISION}
    if json_body:
        headers["Content-Type"] = "application/json"
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info requires api_key"
    k = str(key).strip()
    headers["Authorization"] = k if k.lower().startswith("klaviyo-api-key ") else f"Klaviyo-API-Key {k}"
    return headers, None


def _kv_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _kv_jsonapi_records(data):
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, list):
            return d
        if isinstance(d, dict):
            return [d]
    return []


def _kv_provision_id(data):
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, dict) and d.get("id"):
            return [d["id"]]
    return []
