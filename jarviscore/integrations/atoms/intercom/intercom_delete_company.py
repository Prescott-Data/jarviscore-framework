import requests
from typing import Any, Dict, Optional

# Intercom REST API — https://developers.intercom.com/docs/references/2.11/rest-api/api.intercom.io/companies/deletecompany
INTERCOM_API = "https://api.intercom.io"


def intercom_delete_company(auth_info: dict, company_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Delete a company in intercom. Official: https://developers.intercom.com/docs/references/2.11/rest-api/api.intercom.io"""
    try:
        if not company_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "company_id is required", "provision_ids": []}
        api, err = _ic_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err, "provision_ids": []}
        headers, auth_err = _ic_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err, "provision_ids": []}
        resp = _ic_delete(f"{api}/companies/{company_id}", headers, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000], "provision_ids": []}
        data = resp.json() if resp.text else {}
        records = [data] if isinstance(data, dict) and data else []
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok", "provision_ids": [company_id]}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}



def _ic_api_root(base_url):
    root = (base_url or INTERCOM_API).rstrip("/")
    if "intercom.io" not in root:
        return None, "base_url must be https://api.intercom.io"
    return root, None


def _ic_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json", "Intercom-Version": "2.11"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _ic_delete(url, headers, timeout, verify_ssl):
    return requests.delete(url, headers=headers, timeout=timeout, verify=verify_ssl)
