import requests
from typing import Any, Dict, Optional

# Less Annoying CRM API v2 — https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Contacts
LACRM_API = "https://api.lessannoyingcrm.com/v2"


def less_annoying_crm_delete_contact(auth_info: dict, contact_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Delete a contact in less_annoying_crm (DeleteContact). Official: https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Contacts"""
    try:
        if not contact_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "contact_id is required", "provision_ids": []}
        base, err = _lacrm_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        headers, auth_err = _lacrm_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err, "provision_ids": []}
        resp = _lacrm_call(base, headers, "DeleteContact", {"ContactId": str(contact_id)}, timeout, verify_ssl)
        data = _lacrm_data(resp)
        emsg = _lacrm_err(resp, data)
        if emsg:
            return {"records": [], "data_count": 0, "status": resp.status_code if resp.status_code >= 400 else 400, "message": emsg, "provision_ids": []}
        return {"records": [], "data_count": 0, "status": resp.status_code, "message": "ok", "provision_ids": [contact_id]}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _lacrm_root(base_url):
    root = (base_url or LACRM_API).rstrip("/")
    if not root.endswith("/v2"):
        if "lessannoyingcrm.com" in root:
            root = root + "/v2" if not root.endswith("/v2") else root
        else:
            return None, "base_url must be https://api.lessannoyingcrm.com/v2"
    return root + "/", None


def _lacrm_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.api_key is required"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else tok
    return headers, None


def _lacrm_call(base, headers, function, parameters, timeout, verify_ssl):
    body = {"Function": function, "Parameters": parameters or {}}
    return requests.post(base, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _lacrm_data(resp):
    try:
        return resp.json() if resp.text else {}
    except Exception:
        return {}


def _lacrm_err(resp, data):
    if resp.status_code >= 400:
        if isinstance(data, dict):
            msg = data.get("ErrorDescription") or data.get("Error") or data.get("message")
            if msg:
                return str(msg)
        return resp.text[:1000]
    if isinstance(data, dict) and (data.get("ErrorCode") or data.get("Error")):
        return str(data.get("ErrorDescription") or data.get("Error"))
    return None
