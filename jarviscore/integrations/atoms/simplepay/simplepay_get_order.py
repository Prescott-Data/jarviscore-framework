import requests
from typing import Any, Dict, List, Optional

# SimplePay Payroll API — Official: https://www.simplepay.co.za/api-docs/
_SP_API_ROOT = "https://api.payroll.simplepay.cloud/v1"

def simplepay_get_order(auth_info: dict, order_id: str, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """SimplePay: get payslip (order) by ID. Official: https://www.simplepay.co.za/api-docs/"""
    try:
        root, err = _sp_root(base_url)
        if err: return _sp_dataset([], 400, err)
        if not order_id: return _sp_dataset([], 400, "order_id is required (payslip id)")
        headers, aerr = _sp_auth(auth_info)
        if aerr: return _sp_dataset([], 401, aerr)
        resp = requests.get(f"{root}/payslips/{order_id}", headers=headers, timeout=timeout, verify=verify_ssl)
        if resp.status_code >= 400: return _sp_dataset([], resp.status_code, _sp_err(resp))
        data = resp.json() if resp.content else {}
        records = _sp_unwrap_items(data if isinstance(data, dict) else [data], "payslip")
        if not records and isinstance(data, dict):
            records = [data]
        return _sp_dataset(records[:1], resp.status_code, "ok")
    except Exception as e: return _sp_dataset([], 500, str(e))



def _sp_root(base_url: str):
    root = (base_url or _SP_API_ROOT).rstrip("/")
    if not root.endswith("/v1"):
        if "simplepay" not in root:
            return None, "base_url must be SimplePay API root (https://api.payroll.simplepay.cloud/v1)"
        root = root + "/v1" if not root.endswith("/v1") else root
    return root, None


def _sp_client_id(client_id: Optional[str], auth_info: Optional[Dict[str, Any]]):
    auth_info = auth_info or {}
    cid = client_id or auth_info.get("client_id") or auth_info.get("clientId")
    if cid in (None, ""):
        return None, "client_id is required (or auth_info.client_id)"
    return str(cid), None


def _sp_auth(auth_info: Optional[Dict[str, Any]], json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    key = auth_info.get("api_key")
    if not key:
        return None, "auth_info requires api_key or access_token"
    tok = str(key).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else tok
    return headers, None


def _sp_cap(limit):
    return min(max(int(limit or 25), 1), 500)


def _sp_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sp_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or obj.get("payslip_id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {
        "records": [rec] if rec else [],
        "data_count": 1 if rec else 0,
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _sp_err(resp):
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _sp_unwrap_items(data, key):
    items = []
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and isinstance(row.get(key), dict):
                items.append(row[key])
            elif isinstance(row, dict):
                items.append(row)
    elif isinstance(data, dict):
        nested = data.get(key)
        if isinstance(nested, dict):
            items = [nested]
        elif isinstance(nested, list):
            items = [x for x in nested if isinstance(x, dict)]
    return items


def _sp_match(record, query):
    q = str(query).lower()
    for key in ("id", "number", "first_name", "last_name", "email", "name", "date"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
