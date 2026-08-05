import requests
from typing import Any, Dict, List, Optional


def telegram_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Telegram Bot API: search updates. Official: https://core.telegram.org/bots/api"""
    try:
        root, _, err = _tg_root(base_url, auth_info)
        if err: return _tg_dataset([], 401, err)
        if not query: return _tg_dataset([], 400, "query is required")
        resp = requests.get(f"{root}/getUpdates", params={"limit": 100}, timeout=timeout, verify=verify_ssl)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get("ok", True): return _tg_dataset([], resp.status_code, _tg_err(resp, data))
        res = data.get("result") or []
        q = query.lower()
        matched = [u for u in res if isinstance(u, dict) and q in str(u).lower()]
        return _tg_dataset(matched[:limit], resp.status_code, "ok")
    except Exception as e: return _tg_dataset([], 500, str(e))


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
