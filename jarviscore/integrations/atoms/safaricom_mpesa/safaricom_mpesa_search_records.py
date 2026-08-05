import requests
from typing import Any, Dict, List, Optional

def safaricom_mpesa_search_records(auth_info: dict, query: str, limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Query payment status by CheckoutRequestID. Official: https://developer.safaricom.co.ke/"""
    try:
        if not query:
            return _mp_dataset([], 400, "query (CheckoutRequestID) is required")
        auth_info = auth_info or {}
        shortcode = auth_info.get("business_short_code") or auth_info.get("shortcode")
        passkey = auth_info.get("passkey") or auth_info.get("online_passkey")
        if not shortcode or not passkey:
            return _mp_dataset([], 400, "auth_info.business_short_code and passkey are required")
        ts = _mp_timestamp()
        body_payload = {
            "BusinessShortCode": str(shortcode),
            "Password": _mp_password(shortcode, passkey, ts),
            "Timestamp": ts,
            "CheckoutRequestID": str(query),
        }
        resp, body, status, msg = _mp_post("/mpesa/stkpushquery/v1/query", base_url, auth_info, body_payload, timeout, verify_ssl)
        if status >= 400:
            return _mp_dataset([], status, msg)
        rec = dict(body) if isinstance(body, dict) else {}
        rec["record_type"] = "stk_query"
        return _mp_dataset([rec] if rec else [], status, msg)
    except Exception as e:
        return _mp_dataset([], 500, str(e))


# Safaricom M-Pesa Daraja API — Official docs: https://developer.safaricom.co.ke/


def _mp_root(base_url, auth_info):
    auth_info = auth_info or {}
    root = (base_url or auth_info.get("mpesa_url") or auth_info.get("daraja_url") or auth_info.get("base_url") or "https://sandbox.safaricom.co.ke").strip().rstrip("/")
    for suffix in ("/oauth/v1/generate", "/mpesa/stkpush/v1/processrequest"):
        if suffix in root:
            root = root.split(suffix)[0]
    return root, None


def _mp_timestamp():
    import datetime
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S")


def _mp_password(shortcode, passkey, timestamp):
    import base64
    raw = str(shortcode) + str(passkey) + str(timestamp)
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _mp_phone(value):
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return "254" + digits[1:]
    if digits.startswith("254"):
        return digits
    if len(digits) == 9:
        return "254" + digits
    return digits


def _mp_oauth(base_url, auth_info, timeout, verify_ssl):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if token:
        return str(token).strip(), None
    key = auth_info.get("username")
    secret = auth_info.get("password")
    if not key or not secret:
        return None, "auth_info requires username and password (or access_token)"
    import base64
    root, _ = _mp_root(base_url, auth_info)
    creds = base64.b64encode(f"{key}:{secret}".encode("utf-8")).decode("ascii")
    resp = requests.get(
        root + "/oauth/v1/generate",
        params={"grant_type": "client_credentials"},
        headers={"Authorization": f"Basic {creds}", "Accept": "application/json"},
        timeout=timeout,
        verify=verify_ssl,
    )
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400 or not body.get("access_token"):
        return None, (body.get("errorMessage") or body.get("error") or resp.text or "oauth failed")[:1000]
    return str(body.get("access_token")).strip(), None


def _mp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _mp_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("CheckoutRequestID") or obj.get("MerchantRequestID") or obj.get("ConversationID") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"CheckoutRequestID": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _mp_err(resp, body=None):
    if isinstance(body, dict):
        err = body.get("errorMessage") or body.get("errorMessage") or body.get("error")
        if not err:
            err = body.get("ResponseDescription") or body.get("ResultDesc")
        if err:
            return str(err)[:1000]
    return (resp.text if resp is not None else "request failed")[:1000]


def _mp_post(path, base_url, auth_info, json_body, timeout, verify_ssl):
    token, err = _mp_oauth(base_url, auth_info, timeout, verify_ssl)
    if err:
        return None, None, 401, err
    root, _ = _mp_root(base_url, auth_info)
    resp = requests.post(
        root + path,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
        json=json_body,
        timeout=timeout,
        verify=verify_ssl,
    )
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {}
    if resp.status_code >= 400:
        return resp, body, resp.status_code, _mp_err(resp, body)
    if isinstance(body, dict) and str(body.get("ResponseCode", "0")) not in ("0", "0.0"):
        return resp, body, 400, _mp_err(resp, body)
    return resp, body, resp.status_code, "ok"


def _mp_stk_fields(auth_info, payload):
    auth_info = auth_info or {}
    payload = payload if isinstance(payload, dict) else {}
    shortcode = payload.get("BusinessShortCode") or auth_info.get("business_short_code") or auth_info.get("shortcode")
    passkey = payload.get("Passkey") or auth_info.get("passkey") or auth_info.get("online_passkey")
    if not shortcode or not passkey:
        return None, "business_short_code and passkey are required"
    ts = payload.get("Timestamp") or _mp_timestamp()
    return {
        "BusinessShortCode": str(shortcode),
        "Password": payload.get("Password") or _mp_password(shortcode, passkey, ts),
        "Timestamp": ts,
        "TransactionType": payload.get("TransactionType") or auth_info.get("transaction_type") or "CustomerPayBillOnline",
        "Amount": int(payload.get("Amount") or payload.get("amount") or 0),
        "PartyA": _mp_phone(payload.get("PartyA") or payload.get("PhoneNumber") or payload.get("phone_number")),
        "PartyB": str(payload.get("PartyB") or shortcode),
        "PhoneNumber": _mp_phone(payload.get("PhoneNumber") or payload.get("phone_number") or payload.get("PartyA")),
        "CallBackURL": payload.get("CallBackURL") or payload.get("callback_url") or auth_info.get("callback_url"),
        "AccountReference": str(payload.get("AccountReference") or payload.get("account_reference") or "order")[:12],
        "TransactionDesc": str(payload.get("TransactionDesc") or payload.get("description") or "Payment")[:13],
    }, None


def _mp_cap(limit):
    return min(max(int(limit or 25), 1), 100)
