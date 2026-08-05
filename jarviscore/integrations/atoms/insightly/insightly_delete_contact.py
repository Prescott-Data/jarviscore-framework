import requests
from typing import Any, Dict, Optional

# Insightly API v3.1 — https://api.na1.insightly.com/v3.1/Help
INSIGHTLY_API = "https://api.na1.insightly.com/v3.1"


def insightly_delete_contact(auth_info: dict, contact_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Delete a contact in insightly. Official: https://api.na1.insightly.com/v3.1/Help"""
    try:
        if not contact_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "contact_id is required", "provision_ids": []}
        api, err = _in_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        headers, basic, auth_err = _in_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err, "provision_ids": []}
        resp = _in_delete(f"{api}/Contacts/{contact_id}", headers, basic, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000], "provision_ids": []}
        return {"records": [], "data_count": 0, "status": resp.status_code, "message": "ok", "provision_ids": [contact_id]}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _in_api_root(base_url):
    root = (base_url or INSIGHTLY_API).rstrip("/")
    if "/v3.1" not in root:
        if "insightly.com" in root:
            root = root + "/v3.1" if not root.endswith("/v3") else root + ".1"
        else:
            return None, "base_url must be https://api.{pod}.insightly.com/v3.1"
    return root, None


def _in_auth(auth_info):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if not api_key:
        return headers, None, "auth_info requires api_key"
    return headers, (str(api_key).strip(), ""), None


def _in_delete(url, headers, basic, timeout, verify_ssl):
    return requests.delete(url, headers=headers, auth=basic, timeout=timeout, verify=verify_ssl)
