import requests
from typing import Any, Dict, List, Optional


def agilecrm_create_deal(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create deal via POST /opportunity. Official: https://github.com/agilecrm/rest-api#33-create-deal"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _ac_provision([], 400, "payload must be a non-empty dict")
        api_root, err = _ac_resolve_base(base_url, auth_info)
        if err:
            return _ac_provision([], 400, err)
        auth, err = _ac_auth_tuple(auth_info)
        if err:
            return _ac_provision([], 401, err)
        resp = requests.post(
            f"{api_root}/opportunity",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=dict(payload),
            auth=auth,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return _ac_provision([], status, _ac_err(resp))
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            return _ac_provision([], status, "invalid JSON response")
        records: List[Dict[str, Any]] = [data] if isinstance(data, dict) else []
        return _ac_provision(records, status, "ok", _ac_provision_ids(data))
    except Exception as e:
        return _ac_provision([], 500, str(e))


# POST /opportunity — https://github.com/agilecrm/rest-api#33-create-deal
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


def _ac_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {
        "records": recs,
        "data_count": len(recs),
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _ac_provision_ids(data):
    if isinstance(data, dict) and data.get("id") not in (None, ""):
        return [str(data["id"])]
    return []


def _ac_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]
