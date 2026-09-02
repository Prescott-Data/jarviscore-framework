import requests
from typing import Any, Dict, List, Optional

# Drift list conversations — https://devdocs.drift.com/docs/list-conversations
DRIFT_LIST_HOST = "https://api.drift.com"


def drift_list_conversations(auth_info: dict, timeout: int = 30, verify_ssl: bool = True, limit: int = 25, base_url: str = None) -> dict:
    """List conversations (GET https://api.drift.com/conversations/list). Bearer token via auth_info. Official: https://devdocs.drift.com/docs/list-conversations"""
    try:
        headers, err = _drift_auth(auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 401, "message": err}
        root = _drift_list_root(base_url)
        records = []
        cursor = None
        status = 0
        cap = min(max(int(limit or 25), 1), 100)
        while len(records) < cap:
            params = {"limit": min(cap - len(records), 100)}
            if cursor:
                params["page_token"] = cursor
            resp = _drift_get(f"{root}/conversations/list", headers, params, timeout, verify_ssl)
            status = resp.status_code
            if status >= 400:
                return {"records": records, "data_count": len(records), "status": status, "message": resp.text[:1000]}
            data = resp.json() if resp.text else {}
            batch = data.get("data") or []
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
            cursor = _drift_page_token(data.get("links"))
            if not cursor or not batch:
                break
        return {"records": records[:cap], "data_count": len(records[:cap]), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _drift_list_root(base_url):
    root = (base_url or DRIFT_LIST_HOST).rstrip("/")
    if _host_is(root, "driftapi.com"):
        root = root.replace("driftapi.com", "api.drift.com")
    if root.endswith("/v1"):
        root = root[:-3]
    return root


def _drift_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    headers = {"Accept": "application/json", "Authorization": f"Bearer {str(token).strip()}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers, None


def _drift_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _drift_page_token(links):
    if not isinstance(links, dict):
        return None
    nxt = str(links.get("next") or "")
    if not nxt:
        return None
    query = nxt.split("?", 1)[-1]
    param = "page_" + "token"
    for part in query.split("&"):
        if part.startswith(param + "="):
            return part.split("=", 1)[1]
    return None


def _host_is(url, *domains):
    """True only if url's hostname equals or is a subdomain of one of domains."""
    from urllib.parse import urlparse
    u = str(url or "").strip()
    if "://" not in u:
        u = "https://" + u
    try:
        host = (urlparse(u).hostname or "").lower()
    except Exception:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)
