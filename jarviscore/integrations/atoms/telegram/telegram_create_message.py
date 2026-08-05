import requests
from typing import Any, Dict, List, Optional


def telegram_create_message(auth_info: dict, chat_id: str, text: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Telegram Bot API: sendMessage. Official: https://core.telegram.org/bots/api"""
    try:
        root, _, err = _tg_root(base_url, auth_info)
        if err: return _tg_provision({}, 401, err)
        if not chat_id or not text: return _tg_provision({}, 400, "chat_id and text are required")
        resp = requests.post(f"{root}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=timeout, verify=verify_ssl)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get("ok", True): return _tg_provision({}, resp.status_code, _tg_err(resp, data))
        return _tg_provision(data, resp.status_code, "ok")
    except Exception as e: return _tg_provision({}, 500, str(e))


# Telegram Bot API — Official: https://core.telegram.org/bots/api


def _tg_root(base_url, auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("api_key")
    if not token:
        return None, None, "auth_info.bot_token is required"
    root = (base_url or f"https://api.telegram.org/bot{str(token).strip()}").strip().rstrip("/")
    if "/bot" not in root:
        root = f"https://api.telegram.org/bot{token}"
    return root, token, None


def _tg_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _tg_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    res = obj.get("result") if isinstance(obj.get("result"), dict) else obj
    pid = (res or {}).get("message_id") or (res or {}).get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = res if res else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _tg_err(resp, data=None):
    if isinstance(data, dict) and data.get("description"):
        return str(data["description"])[:1000]
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
