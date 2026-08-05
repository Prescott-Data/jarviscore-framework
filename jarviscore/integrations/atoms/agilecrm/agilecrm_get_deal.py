import requests
from typing import Any, Dict, Optional


def agilecrm_get_deal(auth_info: dict, deal_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get deal via GET /opportunity/{id}. Official: https://github.com/agilecrm/rest-api#32-get-deal-by-its-id"""
    try:
        if not deal_id:
            return _ac_dataset([], 400, "deal_id is required")
        api_root, err = _ac_resolve_base(base_url, auth_info)
        if err:
            return _ac_dataset([], 400, err)
        auth, err = _ac_auth_tuple(auth_info)
        if err:
            return _ac_dataset([], 401, err)
        resp = requests.get(
            f"{api_root}/opportunity/{deal_id}",
            headers={"Accept": "application/json"},
            auth=auth,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return _ac_dataset([], status, _ac_err(resp))
        try:
            data = resp.json()
        except Exception:
            return _ac_dataset([], status, "invalid JSON response")
        if isinstance(data, dict) and data:
            return _ac_dataset([data], status, "ok")
        return _ac_dataset([], status, "empty response")
    except Exception as e:
        return _ac_dataset([], 500, str(e))


# GET /opportunity/{id} — https://github.com/agilecrm/rest-api#32-get-deal-by-its-id
# Auth: HTTP Basic (email + API key) — https://www.agilecrm.com/api


def _ac_resolve_base(base_url, auth_info):
    auth_info = auth_info or {}
    if base_url:
        root = str(base_url).strip().rstrip("/")
    elif auth_info.get("domain"):
        root = f"https://{auth_info['domain']}.agilecrm.com/dev/api"
    else:
        return None, "base_url or auth_info.domain is required"
    if not root.endswith("/dev/api"):
        return None, "base_url must end with /dev/api"
    return root, None


def _ac_auth_tuple(auth_info):
    auth_info = auth_info or {}
    username = auth_info.get("username")
    password = auth_info.get("password")
    if not username or not password:
        return None, "auth_info requires username and password"
    return (str(username), str(password)), None


def _ac_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _ac_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]
