import requests
from typing import Any, Dict, List, Optional


def agilecrm_list_contacts(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """List contacts via GET /contacts with page_size and cursor. Official: https://github.com/agilecrm/rest-api#11-listing-contacts-"""
    try:
        api_root, err = _ac_resolve_base(base_url, auth_info)
        if err:
            return _ac_dataset([], 400, err)
        auth, err = _ac_auth_tuple(auth_info)
        if err:
            return _ac_dataset([], 401, err)
        cap = min(max(int(limit or 25), 1), 100)
        records: List[Dict[str, Any]] = []
        cursor = None
        status = 200
        pages = 0
        while len(records) < cap and pages < 50:
            pages += 1
            params: Dict[str, Any] = {"page_size": cap}
            if cursor:
                params["cursor"] = cursor
            resp = requests.get(
                f"{api_root}/contacts",
                headers={"Accept": "application/json"},
                params=params,
                auth=auth,
                timeout=timeout,
                verify=verify_ssl,
            )
            status = resp.status_code
            if status >= 400:
                return _ac_dataset(records, status, _ac_err(resp))
            try:
                batch = resp.json()
            except Exception:
                return _ac_dataset(records, status, "invalid JSON response")
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
            next_cursor = _ac_cursor(batch)
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        return _ac_dataset(records[:cap], status, "ok")
    except Exception as e:
        return _ac_dataset([], 500, str(e))


# GET /contacts — https://github.com/agilecrm/rest-api#11-listing-contacts-
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


def _ac_cursor(batch):
    if not isinstance(batch, list) or not batch:
        return None
    last = batch[-1]
    if isinstance(last, dict):
        cur = last.get("cursor")
        if isinstance(cur, str) and cur.strip():
            return cur.strip()
    return None
