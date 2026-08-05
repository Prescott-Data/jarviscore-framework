import requests
from typing import Any, Dict, List, Optional

# POST /version1/messaging — https://developers.africastalking.com/docs/sms/sending/bulk
# Auth: apiKey header + username form field — https://developers.africastalking.com/docs/application
_AT_LIVE_ROOT = "https://api.africastalking.com"
_AT_SANDBOX_ROOT = "https://api.sandbox.africastalking.com"
_AT_MESSAGING_PATH = "/version1/messaging"


def africas_talking_create_message(auth_info: dict, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Send bulk SMS via POST /version1/messaging (form: username, to, message, bulkSMSMode). Official: https://developers.africastalking.com/docs/sms/sending/bulk"""
    try:
        if not isinstance(payload, dict) or not payload:
            return _at_provision([], 400, "payload must be a non-empty dict")
        api_root, err = _at_api_root(base_url)
        if err:
            return _at_provision([], 400, err)
        username = _at_username(auth_info)
        if not username:
            return _at_provision([], 400, "auth_info.username is required")
        headers, err = _at_headers(auth_info)
        if err:
            return _at_provision([], 401, err)
        to_value = payload.get("to")
        if to_value is None and payload.get("recipients") is not None:
            to_value = payload.get("recipients")
        to_numbers = _at_normalize_recipients(to_value)
        message = payload.get("message") or payload.get("text") or payload.get("body")
        if not to_numbers or not message:
            return _at_provision([], 400, "payload must include to (or recipients) and message")
        form = {
            "username": str(username),
            "to": to_numbers,
            "message": str(message),
            "bulkSMSMode": "1",
        }
        sender = payload.get("from") or payload.get("sender_id") or payload.get("senderId")
        if sender not in (None, ""):
            form["from"] = str(sender)
        enqueue = payload.get("enqueue")
        if enqueue in (True, 1, "1", "true", "True"):
            form["enqueue"] = "1"
        resp = requests.post(
            f"{api_root}{_AT_MESSAGING_PATH}",
            headers=headers,
            data=form,
            timeout=timeout,
            verify=verify_ssl,
        )
        status = resp.status_code
        if status >= 400:
            return _at_provision([], status, _at_err(resp))
        try:
            data = resp.json() if resp.content else {}
        except Exception:
            return _at_provision([], status, "invalid JSON response")
        sms_data = data.get("SMSMessageData") if isinstance(data, dict) else {}
        recipients = sms_data.get("Recipients") if isinstance(sms_data, dict) else []
        records: List[Dict[str, Any]] = [
            item for item in (recipients or []) if isinstance(item, dict)
        ]
        return _at_provision(records, status, "ok", _at_provision_ids(data))
    except Exception as e:
        return _at_provision([], 500, str(e))



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


def _at_normalize_recipients(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip()


def _at_provision(records, status, msg, provision_ids=None):
    recs = records if isinstance(records, list) else []
    ids = provision_ids if isinstance(provision_ids, list) else []
    return {
        "records": recs,
        "data_count": len(recs),
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _at_provision_ids(data):
    if not isinstance(data, dict):
        return []
    sms_data = data.get("SMSMessageData") or data.get("smsMessageData") or {}
    recipients = sms_data.get("Recipients") or sms_data.get("recipients") or []
    ids = []
    if isinstance(recipients, list):
        for item in recipients:
            if isinstance(item, dict):
                mid = item.get("messageId") or item.get("message_id")
                if mid not in (None, ""):
                    ids.append(str(mid))
    return ids


def _at_err(resp):
    return (resp.text if resp is not None else "request failed")[:1000]
