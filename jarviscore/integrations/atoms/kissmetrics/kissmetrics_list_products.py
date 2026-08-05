import requests
from typing import Any, Dict, List, Optional

# Kissmetrics REST API v3 — https://support.kissmetrics.io/reference/fetch-products
KM_API = "https://query.kissmetrics.io/v3"


def kissmetrics_list_products(auth_info: dict, limit: int = 25, offset: int = 0, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List product in kissmetrics. Official: https://www.kissmetrics.io/product/workflows/api"""
    try:
        api, err = _km_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, basic, auth_err = _km_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        params = {"limit": min(max(int(limit or 25), 1), 50), "offset": int(offset or 0)}
        resp = _km_get(f"{api}/products", headers, basic, params, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        records = _km_records(resp.json() if resp.text else {})[: params["limit"]]
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _km_api_root(base_url):
    root = (base_url or KM_API).rstrip("/")
    if "kissmetrics.io" not in root:
        return None, "base_url must be https://query.kissmetrics.io/v3"
    if not root.endswith("/v3"):
        if root.endswith("/v3.0"):
            root = root[:-2]
        elif "/v3" not in root:
            root = f"{root}/v3"
    return root, None


def _km_auth(auth_info):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    if not api_key:
        return {"Accept": "application/json"}, None, "auth_info requires api_key"
    return {"Accept": "application/json"}, (str(api_key).strip(), ""), None


def _km_get(url, headers, basic, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, auth=basic, params=params, timeout=timeout, verify=verify_ssl)


def _km_records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("products", "data", "results"):
            batch = data.get(key)
            if isinstance(batch, list):
                return batch
    return []
