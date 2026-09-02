import requests
from typing import Any, Dict, List, Optional

# Drift list messages — https://devdocs.drift.com/docs/retrieve-a-conversations-messages
DRIFT_CONV_HOST = "https://driftapi.com"


def drift_list_messages(auth_info: dict, conversation_id: str, timeout: int = 30, verify_ssl: bool = True, limit: int = 50, base_url: str = None) -> dict:
    """List conversation messages (GET https://driftapi.com/conversations/{conversation_id}/messages). Bearer token via auth_info. Official: https://devdocs.drift.com/docs/retrieve-a-conversations-messages"""
    try:
        if not conversation_id:
            return {"records": [], "data_count": 0, "status": 400, "message": "conversation_id is required"}
        headers, err = _drift_auth(auth_info)
        if err:
            return {"records": [], "data_count": 0, "status": 401, "message": err}
        root = _drift_conv_root(base_url)
        records = []
        nxt = None
        status = 0
        cap = min(max(int(limit or 50), 1), 500)
        while len(records) < cap:
            params = {"next": nxt} if nxt else None
            resp = _drift_get(f"{root}/conversations/{conversation_id}/messages", headers, params, timeout, verify_ssl)
            status = resp.status_code
            if status >= 400:
                return {"records": records, "data_count": len(records), "status": status, "message": resp.text[:1000]}
            data = resp.json() if resp.text else {}
            batch = _drift_messages_batch(data)
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    if len(records) >= cap:
                        break
            pag = data.get("pagination") or {}
            nxt = pag.get("next")
            if not nxt or not batch:
                break
        return {"records": records[:cap], "data_count": len(records[:cap]), "status": status, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _drift_conv_root(base_url):
    root = (base_url or DRIFT_CONV_HOST).rstrip("/")
    if _host_is(root, "api.drift.com") and not _host_is(root, "driftapi.com"):
        root = root.replace("api.drift.com", "driftapi.com")
    if root.endswith("/conversations"):
        root = root[: -len("/conversations")]
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


def _drift_messages_batch(data):
    if not isinstance(data, dict):
        return []
    inner = data.get("data")
    if isinstance(inner, dict) and isinstance(inner.get("messages"), list):
        return inner["messages"]
    if isinstance(inner, list):
        return inner
    if isinstance(data.get("messages"), list):
        return data["messages"]
    return []


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
