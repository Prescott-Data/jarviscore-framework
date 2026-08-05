import requests
from typing import Any, Dict, List, Optional

# Snapchat Marketing API — Official: https://marketingapi.snapchat.com/docs/
_SC_API_ROOT = "https://adsapi.snapchat.com/v1"

def snapchat_ads_create_campaign(auth_info: dict, ad_account_id: str, payload: Dict[str, Any], timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Snapchat Marketing API: create campaign. Official: https://marketingapi.snapchat.com/docs/"""
    try:
        if not isinstance(payload, dict) or not payload: return _sc_provision({}, 400, "payload is required")
        root, err = _sc_root(base_url)
        if err: return _sc_provision({}, 400, err)
        aid, err = _sc_ad_account(ad_account_id, auth_info)
        if err: return _sc_provision({}, 400, err)
        headers, aerr = _sc_auth(auth_info, json_body=True)
        if aerr: return _sc_provision({}, 401, aerr)
        campaigns = payload.get("campaigns") if isinstance(payload.get("campaigns"), list) else [payload]
        for c in campaigns:
            if isinstance(c, dict) and not c.get("ad_account_id"):
                c["ad_account_id"] = aid
        body = payload if isinstance(payload.get("campaigns"), list) else {"campaigns": campaigns}
        resp = requests.post(f"{root}/adaccounts/{aid}/campaigns", headers=headers, json=body, timeout=timeout, verify=verify_ssl)
        try: data = resp.json() if resp.content else {}
        except Exception: data = {}
        if resp.status_code >= 400: return _sc_provision(data if isinstance(data, dict) else {}, resp.status_code, _sc_err(resp))
        records = _sc_extract_list(data, "campaigns")
        obj = records[0] if records else (data if isinstance(data, dict) else {})
        return _sc_provision(obj, resp.status_code, "ok", fallback_id=obj.get("id") if isinstance(obj, dict) else None)
    except Exception as e: return _sc_provision({}, 500, str(e))



def _sc_root(base_url: str):
    root = (base_url or _SC_API_ROOT).rstrip("/")
    if "adsapi.snapchat.com" not in root:
        return None, "base_url must be Snapchat Ads API root (https://adsapi.snapchat.com/v1)"
    return root, None


def _sc_ad_account(ad_account_id: Optional[str], auth_info: Optional[Dict[str, Any]]):
    auth_info = auth_info or {}
    aid = ad_account_id or auth_info.get("ad_account_id") or auth_info.get("adAccountId")
    if aid in (None, ""):
        return None, "ad_account_id is required (or auth_info.ad_account_id)"
    return str(aid), None


def _sc_auth(auth_info: Optional[Dict[str, Any]], json_body: bool = False):
    auth_info = auth_info or {}
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info requires access_token"
    tok = str(token).strip()
    headers["Authorization"] = tok if tok.lower().startswith("bearer ") else f"Bearer {tok}"
    return headers, None


def _sc_cap(limit):
    return min(max(int(limit or 25), 1), 1000)


def _sc_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _sc_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {
        "records": [rec] if rec else [],
        "data_count": 1 if rec else 0,
        "status": status,
        "message": msg,
        "provision_ids": ids,
    }


def _sc_err(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            return str(data.get("debug_message") or data.get("display_message") or data)[:1000]
    except Exception:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:1000]


def _sc_extract_list(data, resource_key):
    records = []
    if not isinstance(data, dict):
        return records
    rows = data.get(resource_key) or []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get(resource_key[:-1] if resource_key.endswith("s") else resource_key), dict):
                inner_key = resource_key[:-1] if resource_key.endswith("s") else resource_key
                records.append(row[inner_key])
            elif isinstance(row, dict) and resource_key[:-1] in row:
                records.append(row[resource_key[:-1]])
    return records


def _sc_paging(resp, data, cap, records, resource_key):
    paging = data.get("paging") if isinstance(data, dict) else {}
    next_link = paging.get("next_link") if isinstance(paging, dict) else None
    if next_link and len(records) < cap:
        nresp = requests.get(next_link, headers=dict(resp.request.headers), timeout=30)
        if nresp.status_code < 400:
            ndata = nresp.json() if nresp.content else {}
            records.extend(_sc_extract_list(ndata, resource_key)[: cap - len(records)])
    return records


def _sc_match(record, query):
    q = str(query).lower()
    for key in ("id", "name", "status"):
        val = record.get(key)
        if val is not None and q in str(val).lower():
            return True
    return False
