import requests
from typing import Any, Dict, List, Optional

# WhatsApp Cloud API — Official: https://developers.facebook.com/docs/whatsapp/cloud-api

_WA_ROOT = "https://graph.facebook.com/v19.0"


def whatsapp_business_list_messages(auth_info: dict, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """WhatsApp Cloud API: List message templates. Official: https://developers.facebook.com/docs/whatsapp/cloud-api"""
    try:
        root, _ = _wa_root(base_url, auth_info)
        headers, aerr = _wa_auth(auth_info)
        if aerr: return _wa_dataset([], 401, aerr)
        # Message templates are WhatsApp Business Account (WABA) assets, not phone-number assets.
        waba, err = _wa_waba(auth_info)
        if err: return _wa_dataset([], 400, err)
        resp = requests.get(f"{root}/{waba}/message_templates", headers=headers, params={"limit": limit}, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _wa_dataset([], resp.status_code, _wa_err(resp))
        data = resp.json() if resp.content else {}
        items = data.get("data") if isinstance(data, dict) else []
        return _wa_dataset(items if isinstance(items, list) else [], resp.status_code, "ok")
    except Exception as e: return _wa_dataset([], 500, str(e))



def _wa_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("whatsapp_url") or _WA_ROOT).strip().rstrip("/")
    return root, None


def _wa_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    return {"Authorization": "Bearer " + str(token).strip(), "Accept": "application/json"}, None


def _wa_phone(auth_info):
    auth_info = auth_info or {}
    pid = auth_info.get("phone_number_id") or auth_info.get("phoneNumberId")
    if not pid:
        return None, "auth_info.phone_number_id is required"
    return str(pid), None


def _wa_waba(auth_info):
    auth_info = auth_info or {}
    waba = auth_info.get("whatsapp_business_account_id") or auth_info.get("waba_id") or auth_info.get("business_account_id")
    if not waba:
        return None, "auth_info.whatsapp_business_account_id is required"
    return str(waba), None


def _wa_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _wa_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    msgs = obj.get("messages") if isinstance(obj.get("messages"), list) else []
    pid = (msgs[0].get("id") if msgs else None) or obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _wa_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]
