import requests
from typing import Any, Dict, List, Optional


def matomo_create_event(auth_info: dict, id_site: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Track a custom event via the Tracking HTTP API (matomo.php). Official: https://developer.matomo.org/api-reference/tracking-api"""
    try:
        site, serr = _mt_id_site(id_site, auth_info)
        if serr:
            return {"records": [], "data_count": 0, "status": 400, "message": serr, "provision_ids": []}
        category, action, name, value, url = _mt_event_fields(payload)
        if not category or not action:
            return {
                "records": [],
                "data_count": 0,
                "status": 400,
                "message": "payload must include event_category (e_c) and event_action (e_a)",
                "provision_ids": [],
            }
        tracker, terr = _mt_tracker_url(base_url, auth_info)
        if terr:
            return {"records": [], "data_count": 0, "status": 401, "message": terr, "provision_ids": []}
        params = {"rec": "1", "ca": "1", "idsite": site, "e_c": category, "e_a": action}
        if name not in (None, ""):
            params["e_n"] = str(name)
        if value not in (None, ""):
            params["e_v"] = value
        if url:
            params["url"] = url
        else:
            root, _ = _mt_root(base_url)
            if root:
                params["url"] = root + "/"
        tok = _mt_token(auth_info)
        if tok:
            params["token_auth"] = tok
        resp = requests.get(tracker, params=params, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400:
            return {
                "records": [],
                "data_count": 0,
                "status": resp.status_code,
                "message": resp.text[:1000],
                "provision_ids": [],
            }
        return _mt_provision(category, action, name, resp.status_code)
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e), "provision_ids": []}


# Matomo Tracking HTTP API — Official docs:
# Tracking API https://developer.matomo.org/api-reference/tracking-api


def _mt_root(base_url):
    if not base_url:
        return None, "base_url is required"
    return base_url.rstrip("/"), None


def _mt_token(auth_info):
    auth_info = auth_info or {}
    tok = auth_info.get("api_key")
    return str(tok).strip() if tok else None


def _mt_id_site(id_site, auth_info):
    auth_info = auth_info or {}
    site = id_site or auth_info.get("id_site") or auth_info.get("idsite") or auth_info.get("site_id")
    if site in (None, ""):
        return None, "id_site is required"
    return str(site), None


def _mt_tracker_url(base, auth_info):
    auth_info = auth_info or {}
    custom = auth_info.get("tracker_url")
    if custom:
        return str(custom).rstrip("/"), None
    root, err = _mt_root(base)
    if err:
        return None, err
    return f"{root}/matomo.php", None


def _mt_event_fields(payload):
    body = payload if isinstance(payload, dict) else {}
    category = body.get("e_c") or body.get("event_category") or body.get("category")
    action = body.get("e_a") or body.get("event_action") or body.get("action")
    name = body.get("e_n") or body.get("event_name") or body.get("name")
    value = body.get("e_v") or body.get("event_value") or body.get("value")
    url = body.get("url")
    return category, action, name, value, url


def _mt_provision(category, action, name, status, message="ok"):
    event_key = "|".join(str(x) for x in (category, action, name or "") if x not in (None, ""))
    record = {"event_category": category, "event_action": action}
    if name not in (None, ""):
        record["event_name"] = name
    ids = [event_key] if event_key else []
    return {
        "records": [record] if record else [],
        "data_count": 1 if record else 0,
        "status": status,
        "message": message,
        "provision_ids": ids,
    }
