import requests
from typing import Any, Dict, List, Optional

# LiveChat Agent Chat API — Official docs:
# Agent Chat API https://platform.text.com/docs/messaging/agent-chat-api
# Auth https://developers.livechatinc.com/docs/authorization/personal-access-tokens
LIVECHAT_AGENT_API = "https://api.livechatinc.com/v3.6/agent"


def livechat_get_conversation(auth_info: dict, conversation_id: str, thread_id: str = "", timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Get chat by ID via get_chat action. Official: https://platform.text.com/docs/messaging/agent-chat-api#get-chat"""
    try:
        cid = _lc_chat_id(conversation_id)
        if not cid:
            return {"records": [], "data_count": 0, "status": 400, "message": "conversation_id is required"}
        base, err = _lc_root(base_url)
        if err:
            return {"records": [], "data_count": 0, "status": 400, "message": err}
        body = {"chat_id": cid}
        if thread_id:
            body["thread_id"] = thread_id
        resp, aerr = _lc_post(base, "get_chat", body, auth_info, timeout, verify_ssl)
        if aerr:
            return {"records": [], "data_count": 0, "status": 401, "message": aerr}
        data = _lc_json(resp)
        if resp.status_code >= 400:
            return {"records": [], "data_count": 0, "status": resp.status_code, "message": _lc_error(data, resp.text)}
        records = _lc_records(data)
        return {"records": records, "data_count": len(records), "status": resp.status_code, "message": "ok"}
    except Exception as e:
        return {"records": [], "data_count": 0, "status": 500, "message": str(e)}



def _lc_root(base_url):
    root = (base_url or LIVECHAT_AGENT_API).rstrip("/")
    if "livechatinc.com" not in root:
        return None, "base_url must be https://api.livechatinc.com/v3.6/agent"
    return root, None


def _lc_auth_header(auth_info):
    auth_info = auth_info or {}
    username = auth_info.get("username")
    password = auth_info.get("password")
    if not username or not password:
        return None, "auth_info requires username and password"
    import base64
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return "Basic " + encoded, None


def _lc_headers(auth_info):
    auth, err = _lc_auth_header(auth_info)
    if err:
        return None, err
    return {"Accept": "application/json", "Content-Type": "application/json", "Authorization": auth}, None


def _lc_action_url(base, action):
    if base.endswith("/agent"):
        return f"{base}/action/{action}"
    return f"{base}/action/{action}"


def _lc_post(base, action, body, auth_info, timeout, verify_ssl):
    headers, err = _lc_headers(auth_info)
    if err:
        return None, err
    resp = requests.post(_lc_action_url(base, action), headers=headers, json=body or {}, timeout=timeout, verify=verify_ssl)
    return resp, None


def _lc_json(resp):
    try:
        return resp.json() if resp.text else {}
    except Exception:
        return {}


def _lc_error(data, fallback=""):
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("type") or fallback)[:1000]
        if data.get("type") == "Error":
            return str(data.get("message") or fallback)[:1000]
    return (fallback or "")[:1000]


def _lc_records(items):
    if isinstance(items, list):
        return [row for row in items if isinstance(row, dict)]
    if isinstance(items, dict) and items.get("id") is not None:
        return [items]
    return []


def _lc_cap(records, limit):
    cap = min(max(int(limit or 25), 1), 100)
    return records[:cap]


def _lc_provision_ids(data):
    if not isinstance(data, dict):
        return []
    for key in ("event_id", "chat_id", "thread_id", "id"):
        val = data.get(key)
        if val not in (None, ""):
            return [val]
    return []


def _lc_provision(data, status, message="ok"):
    ids = _lc_provision_ids(data)
    records = [data] if isinstance(data, dict) and data else []
    if ids and (not records or not records[0].get("id")):
        records = [{"id": ids[0]}]
    return {"records": records, "data_count": len(records), "status": status, "message": message, "provision_ids": ids}


def _lc_chat_id(conversation_id, chat_id=None):
    return str(chat_id or conversation_id or "")


def _lc_flatten_events(threads):
    out = []
    for thread in threads if isinstance(threads, list) else []:
        if not isinstance(thread, dict):
            continue
        tid = thread.get("id")
        for ev in thread.get("events") or []:
            if isinstance(ev, dict):
                row = dict(ev)
                if tid and "thread_id" not in row:
                    row["thread_id"] = tid
                out.append(row)
    return out
