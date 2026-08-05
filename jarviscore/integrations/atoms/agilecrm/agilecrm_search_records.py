import requests
from typing import Any, Dict, List, Optional


def agilecrm_search_records(auth_info: dict, query: str, record_type: str = "PERSON", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search contacts/companies via GET /search. Official: https://github.com/agilecrm/rest-api#111-search-contactscompanies"""
    try:
        if not query:
            return _ac_dataset([], 400, "query is required")
        api_root, err = _ac_resolve_base(base_url, auth_info)
        if err:
            return _ac_dataset([], 400, err)
        auth, err = _ac_auth_tuple(auth_info)
        if err:
            return _ac_dataset([], 401, err)
        search_type = record_type if record_type in ("PERSON", "COMPANY") else "PERSON"
        page_size = min(max(int(limit or 25), 1), 100)
        resp = requests.get(
            f"{api_root}/search",
            headers={"Accept": "application/json"},
            params={"q": query, "page_size": page_size, "type": search_type},
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
        if isinstance(data, list):
            records = [r for r in data if isinstance(r, dict)][:page_size]
        elif isinstance(data, dict):
            raw = data.get("results")
            records = [r for r in raw if isinstance(r, dict)][:page_size] if isinstance(raw, list) else []
        else:
            records = []
        return _ac_dataset(records, status, "ok")
    except Exception as e:
        return _ac_dataset([], 500, str(e))


# GET /search?q=&page_size=&type= — https://github.com/agilecrm/rest-api#111-search-contactscompanies
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
