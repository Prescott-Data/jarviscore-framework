import requests
from typing import Any, Dict, List, Optional


def activecampaign_create_contact(auth_info: dict, payload: Dict[str, Any], account: Optional[str] = None, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create contact via POST /contacts with contact wrapper. Official: https://developers.activecampaign.com/reference/create-a-new-contact"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _ac_v3_provision([], 400, "payload must be a non-empty dict")
        api_root, err = _ac_v3_resolve_base(base_url, account, auth_info)
        if err:
            return _ac_v3_provision([], 400, err)
        headers, err = _ac_v3_headers(auth_info, json_body=True)
        if err:
            return _ac_v3_provision([], 401, err)
        body = _ac_v3_wrap_resource("contact", payload)
        resp = requests.post(
            f"{api_root}/contacts",
            headers=headers,
            json=body,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return _ac_v3_provision([], status, _ac_v3_err(resp))
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            return _ac_v3_provision([], status, "invalid JSON response")
        obj = data.get("contact") if isinstance(data, dict) else None
        records: List[Dict[str, Any]] = [obj] if isinstance(obj, dict) else []
        return _ac_v3_provision(records, status, "ok", _ac_v3_provision_ids(data, "contact"))
    except Exception as e:
        return _ac_v3_provision([], 500, str(e))


# POST /contacts — https://developers.activecampaign.com/reference/create-a-new-contact
# Auth: Api-Token header — https://developers.activecampaign.com/reference/authentication


def _ac_v3_resolve_base(base_url, account, auth_info):
    auth_info = auth_info or {}
    if base_url:
        root = str(base_url).strip().rstrip("/")
    elif auth_info.get("api_base"):
        root = str(auth_info.get("api_base")).strip().rstrip("/")
    elif account:
        region = auth_info.get("api_region") or auth_info.get("region") or "us1"
        root = f"https://{account}.api-{region}.com/api/3"
    else:
        return None, "base_url or account is required"
    if not root.endswith("/api/3"):
        return None, "base_url must be the v3 root ending in /api/3"
    return root, None


def _ac_v3_headers(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, "auth_info.api_token is required"
    headers = {"Accept": "application/json", "Api-Token": str(token).strip()}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _ac_v3_wrap_resource(resource_key, payload):
    if isinstance(payload, dict) and resource_key in payload:
        return payload
    return {resource_key: payload}


def _ac_v3_provision_ids(data, resource_key):
    if not isinstance(data, dict):
        return []
    obj = data.get(resource_key)
    if isinstance(obj, dict) and obj.get("id") not in (None, ""):
        return [str(obj["id"])]
    if data.get("id") not in (None, ""):
        return [str(data["id"])]
    return []


def _ac_v3_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {
        "records": recs,
        "data_count": len(recs),
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _ac_v3_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]
