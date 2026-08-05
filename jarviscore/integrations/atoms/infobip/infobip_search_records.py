import requests
from typing import Any, Dict, List, Optional

# Infobip Conversations API — https://www.infobip.com/docs/conversations/conversations-over-api/manage-conversations-over-api
INFOBIP_API = "https://api.infobip.com"


def infobip_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Search Infobip conversations by topic, status, or ID. Official: https://www.infobip.com/docs/conversations/conversations-over-api/manage-conversations-over-api"""
    try:
        if not query:
            return {"records": [], "data_count": 0, "status": 400, "message": "query is required"}
        api, err = _ib_api_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        headers, auth_err = _ib_auth(auth_info)
        if auth_err:
            return {"records": [], "data_count": 0, "status": 401, "message": auth_err}
        resp = _ib_get(f"{api}/ccaas/1/conversations", headers, {"limit": 100}, timeout, verify_ssl)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": resp.text[:1000]}
        needle = query.lower()
        matched = []
        for item in _ib_conversations(resp.json() if resp.text else {}):
            if not isinstance(item, dict):
                continue
            hay = " ".join(str(item.get(k, "")) for k in ("id", "topic", "summary", "status")).lower()
            if needle in hay:
                matched.append(item)
                if len(matched) >= limit:
                    break
        return {"records": matched, "data_count": len(matched), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _ib_api_root(base_url):
    root = (base_url or INFOBIP_API).rstrip("/")
    if "infobip.com" not in root:
        return None, "base_url must be https://api.infobip.com (or your Infobip regional base URL)"
    return root, None


def _ib_auth(auth_info, json_body=False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    api_key = auth_info.get("api_key")
    if not api_key:
        return None, "auth_info requires api_key"
    key = str(api_key).strip()
    if key.lower().startswith("app "):
        headers["Authorization"] = key
    elif key.lower().startswith("bearer "):
        headers["Authorization"] = key
    else:
        headers["Authorization"] = f"App {key}"
    return headers, None


def _ib_get(url, headers, params, timeout, verify_ssl):
    return requests.get(url, headers=headers, params=params, timeout=timeout, verify=verify_ssl)


def _ib_post(url, headers, body, timeout, verify_ssl):
    return requests.post(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _ib_put(url, headers, body, timeout, verify_ssl):
    return requests.put(url, headers=headers, json=body, timeout=timeout, verify=verify_ssl)


def _ib_conversations(data):
    if isinstance(data, dict):
        conv = data.get("conversations")
        if isinstance(conv, list):
            return conv
        if isinstance(data.get("id"), str):
            return [data]
    return []


def _ib_messages(data):
    if isinstance(data, dict):
        msgs = data.get("messages")
        if isinstance(msgs, list):
            return msgs
        if isinstance(data.get("id"), str):
            return [data]
    return []


def _ib_provision_id(data):
    if isinstance(data, dict) and data.get("id") not in (None, ""):
        return [data["id"]]
    return []


def _ib_conv_id(auth_info, payload, conversation_id=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    cid = (
        conversation_id
        or payload.get("conversation_id")
        or payload.get("conversationId")
        or auth_info.get("conversation_id")
        or auth_info.get("conversationId")
    )
    return str(cid).strip() if cid not in (None, "") else None
