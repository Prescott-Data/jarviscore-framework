import requests
from typing import Any, Dict, List, Optional

def rocket_chat_create_message(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Post a message to a room. Official: https://developer.rocket.chat/apidocs/authentication-api"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _rc_provision({}, 400, "payload is required")
        room_id = _rc_room_id(auth_info, payload)
        body_payload = dict(payload)
        if room_id and "roomId" not in body_payload and "channel" not in body_payload:
            body_payload["roomId"] = room_id
        if not body_payload.get("roomId") and not body_payload.get("channel"):
            return _rc_provision({}, 400, "payload.roomId/channel or auth_info.room_id is required")
        if "text" not in body_payload and "msg" in body_payload:
            body_payload["text"] = body_payload.pop("msg")
        root, err = _rc_root(base_url, auth_info)
        if err:
            return _rc_provision({}, 400, err)
        resp, body, status, msg = _rc_request("post", root + "/chat.postMessage", auth_info, json_body=body_payload, timeout=timeout, verify_ssl=verify_ssl)
        if status >= 400:
            return _rc_provision(body if isinstance(body, dict) else {}, status, msg)
        message = body.get("message") if isinstance(body.get("message"), dict) else body
        return _rc_provision(message if isinstance(message, dict) else {}, status, "ok")
    except Exception as e:
        return _rc_provision({}, 500, str(e))


# Rocket.Chat REST API v1 — Official docs: https://developer.rocket.chat/apidocs/authentication-api


def _rc_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("rocket_chat_url") or auth_info.get("base_url") or "").strip().rstrip("/")
    if not root:
        return None, "base_url is required"
    if not root.endswith("/api/v1"):
        if "/api/v1" in root:
            root = root.split("/api/v1")[0] + "/api/v1"
        else:
            root = root + "/api/v1"
    return root, None


def _rc_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("password")
    user_id = auth_info.get("username")
    if not token or not user_id:
        return None, "auth_info requires username and password"
    return {"X-Auth-Token": str(token).strip(), "X-User-Id": str(user_id).strip(), "Accept": "application/json"}, None


def _rc_cap(limit):
    return min(max(int(limit or 25), 1), 100)


def _rc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _rc_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("_id") or obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"_id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _rc_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("error") or body.get("message")
        if err:
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _rc_ok(body):
    if isinstance(body, dict) and body.get("success") is False:
        return False
    if isinstance(body, dict) and body.get("status") == "error":
        return False
    return True


def _rc_room_id(auth_info, payload=None):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    return payload.get("roomId") or payload.get("room_id") or payload.get("conversation_id") or auth_info.get("room_id") or auth_info.get("conversation_id") or auth_info.get("roomId")


def _rc_request(method, url, auth_info, params=None, json_body=None, timeout=30, verify_ssl=True):
    headers, err = _rc_auth(auth_info)
    if err:
        return None, None, 401, err
    if json_body is not None:
        headers = dict(headers)
        headers["Content-Type"] = "application/json"
    kwargs = {"headers": headers, "timeout": timeout, "verify": verify_ssl}
    if method == "get":
        resp = requests.get(url, params=params, **kwargs)
    elif method == "post":
        resp = requests.post(url, params=params, json=json_body, **kwargs)
    else:
        return None, None, 400, f"unsupported method {method}"
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400 or not _rc_ok(body):
        status = resp.status_code if resp.status_code >= 400 else 400
        return resp, body, status, _rc_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _rc_match(record, query):
    q = str(query).lower()
    for key in ("_id", "id", "name", "fname", "msg", "username"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
