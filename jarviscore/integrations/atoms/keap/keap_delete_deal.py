import requests
from typing import Any, Dict, Optional

# Keap REST API v2 — https://developer.keap.com/docs/restv2/
KEAP_API = "https://api.infusionsoft.com/crm/rest/v2"


def keap_delete_deal(auth_info: dict, deal_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Delete a deal in keap. Official: https://developer.keap.com/docs/restv2/"""
    try:
        if not deal_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "deal_id is required", "provision_ids": []}
        api, err = _kp_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        headers, auth_err = _kp_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err, "provision_ids": []}
        resp = _kp_delete(f"{api}/opportunities/{deal_id}", headers, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000], "provision_ids": []}
        return {"records": [], "data_count": 0, "status": resp.status_code, "message": "ok", "provision_ids": [deal_id]}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _kp_api_root(base_url):
    root = (base_url or KEAP_API).rstrip("/")
    if "/rest/v2" not in root:
        if "infusionsoft.com" in root or "keap.com" in root:
            root = root + "/crm/rest/v2" if "/crm" not in root else root + "/rest/v2" if not root.endswith("/v2") else root
        else:
            return None, "base_url must be https://api.infusionsoft.com/crm/rest/v2"
    return root, None


def _kp_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _kp_delete(url, headers, timeout, verify_ssl):
    return requests.delete(url, headers=headers, timeout=timeout, verify=verify_ssl)
