import requests
from typing import Any, Dict, List, Optional

# GET /version1/messaging?username=&lastReceivedId= — https://developers.africastalking.com/docs/sms/fetch_messages
# Auth: apiKey header + username query param — https://developers.africastalking.com/docs/application
_AT_LIVE_ROOT = "https://api.africastalking.com"
_AT_SANDBOX_ROOT = "https://api.sandbox.africastalking.com"
_AT_MESSAGING_PATH = "/version1/messaging"


def africas_talking_list_messages(auth_info: dict, limit: int = 25, last_received_id: int = 0, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Fetch inbox SMS via GET /version1/messaging?username=&lastReceivedId=. Official: https://developers.africastalking.com/docs/sms/fetch_messages"""
    try:
        api_root, err = _at_api_root(base_url)
        if err:
            return _at_dataset([], 400, err)
        username = _at_username(auth_info)
        if not username:
            return _at_dataset([], 400, "auth_info.username is required")
        headers, err = _at_headers(auth_info)
        if err:
            return _at_dataset([], 401, err)
        cap = min(max(int(limit or 25), 1), 1000)
        records: List[Dict[str, Any]] = []
        cursor = max(int(last_received_id or 0), 0)
        status = 200
        pages = 0
        url = f"{api_root}{_AT_MESSAGING_PATH}"
        while len(records) < cap and pages < 50:
            pages += 1
            resp = requests.get(
                url,
                headers=headers,
                params={"username": str(username), "lastReceivedId": cursor},
                timeout=timeout,
                verify=verify_ssl,
            )
            status = resp.status_code
            if status >= 400:
                return _at_dataset(records, status, _at_err(resp))
            try:
                data = resp.json()
            except Exception:
                return _at_dataset(records, status, "invalid JSON response")
            batch = _at_parse_messages(data)
            if not batch:
                break
            max_id = cursor
            for item in batch:
                if isinstance(item, dict):
                    records.append(item)
                    item_id = _at_message_id_value(item)
                    if item_id is not None and item_id > max_id:
                        max_id = item_id
                    if len(records) >= cap:
                        break
            if max_id <= cursor:
                break
            cursor = max_id
        return _at_dataset(records[:cap], status, "ok")
    except Exception as e:
        return _at_dataset([], 500, str(e))



def _at_api_root(base_url):
    root = str(base_url or "").strip().rstrip("/")
    if root.endswith(_AT_MESSAGING_PATH):
        root = root[: -len(_AT_MESSAGING_PATH)]
    if root in (_AT_LIVE_ROOT, _AT_SANDBOX_ROOT):
        return root, None
    return None, (
        "base_url must be https://api.africastalking.com or "
        "https://api.sandbox.africastalking.com"
    )


def _at_headers(auth_info):
    auth_info = auth_info or {}
    api_key = auth_info.get("api_key")
    if not api_key:
        return None, "auth_info.api_key is required"
    return {"Accept": "application/json", "apiKey": str(api_key).strip()}, None


def _at_username(auth_info):
    auth_info = auth_info or {}
    return auth_info.get("username")


def _at_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _at_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]


def _at_parse_messages(data):
    if not isinstance(data, dict):
        return []
    sms_data = data.get("SMSMessageData") or data.get("smsMessageData") or {}
    messages = sms_data.get("Messages") or sms_data.get("messages") or []
    return messages if isinstance(messages, list) else []


def _at_message_id_value(message):
    if not isinstance(message, dict):
        return None
    mid = message.get("id")
    if mid is None:
        return None
    try:
        return int(mid)
    except (TypeError, ValueError):
        return None
