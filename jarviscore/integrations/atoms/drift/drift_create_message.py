import requests
from typing import Any, Dict, Optional

# Drift create message — https://devdocs.drift.com/docs/creating-a-message
DRIFT_CONV_HOST = "https://driftapi.com"


def drift_create_message(auth_info: dict, conversation_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Create message (POST https://driftapi.com/conversations/{conversation_id}/messages). Bearer token via auth_info. Official: https://devdocs.drift.com/docs/creating-a-message"""
    try:
        if not conversation_id or not payload:
            return {"records": [], "data_count": 0, "status": 400, "message": "conversation_id and payload are required"}
        headers, err = _drift_auth(auth_info, json_body=True)
        if err:
            return {"records": [], "data_count": 0, "status": 401, "message": err}
        root = _drift_conv_root(base_url)
        body = payload if isinstance(payload, dict) and payload.get("type") else {"type": "chat", **(payload or {})}
        resp = _drift_post(f"{root}/conversations/{conversation_id}/messages", headers, body, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        data = resp.json() if resp.text else {}
        obj = _drift_message_model(data)
        prov = [str(obj.get("id"))] if isinstance(obj, dict) and obj.get("id") is not None else []
        out = {
            "records": [obj] if isinstance(obj, dict) else [],
            "data_count": 1 if isinstance(obj, dict) else 0,
            "status": resp.status_code,
            "message": "ok",
        }
        if prov:
            out["provision_ids"] = prov
        return out
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


def _drift_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _drift_message_model(data):
    if not isinstance(data, dict):
        return None
    inner = data.get("data")
    if isinstance(inner, dict):
        msgs = inner.get("messages")
        if isinstance(msgs, list) and msgs:
            return msgs[-1]
        if inner.get("id") is not None:
            return inner
    if data.get("id") is not None:
        return data
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
