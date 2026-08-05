import requests
from typing import Any, Dict, List, Optional

# Wave GraphQL API — Official: https://developer.waveapps.com/hc/en-us/articles/360019588314-API-Reference

_GQL = "https://gql.waveapps.com/graphql/public"


def wave_accounting_search_records(auth_info: dict, business_id: str = "", customer_id: str = "", invoice_id: str = "", payment_id: str = "", name: str = "", query: str = "", limit: int = 25, timeout: int = 30, verify_ssl: bool = True, base_url: str = None) -> dict:
    """Wave GraphQL: search records. Official: https://developer.waveapps.com/hc/en-us/articles/360019588314-API-Reference"""
    try:
        bid = business_id or (auth_info or {}).get("business_id")
        if not query: return _wv_dataset([], 400, "query is required")
        if not bid: return _wv_dataset([], 400, "business_id is required")
        gql = "query SearchCustomers($id: ID!, $pageSize: Int!) { business(id: $id) { customers(page: 1, pageSize: $pageSize, sort: [NAME_ASC]) { edges { node { id name email } } } } }"
        data, status, err = _wv_post(gql, auth_info, base_url, {"id": str(bid), "pageSize": 50}, timeout, verify_ssl)
        if err: return _wv_dataset([], 401, err)
        if status >= 400 or (isinstance(data, dict) and data.get("errors")):
            return _wv_dataset([], status if status >= 400 else 400, str((data or {}).get("errors") or data)[:1000])
        edges = (((data.get("data") or {}).get("business") or {}).get("customers") or {}).get("edges") or [] if isinstance(data, dict) else []
        nodes = [e.get("node") for e in edges if isinstance(e, dict) and isinstance(e.get("node"), dict)]
        qv = query.lower()
        nodes = [n for n in nodes if qv in str(n.get("name", "")).lower() or qv in str(n.get("email", "")).lower()]
        return _wv_dataset(nodes[:limit], status, "ok")
    except Exception as e: return _wv_dataset([], 500, str(e))



def _wv_auth(auth_info):
    auth_info = auth_info or {}
    token = auth_info.get("access_token")
    if not token:
        return None, "auth_info.access_token is required"
    return {"Authorization": "Bearer " + str(token).strip(), "Content-Type": "application/json"}, None


def _wv_dataset(records, status, msg):
    recs = records if isinstance(records, list) else []
    return {"records": recs, "data_count": len(recs), "status": status, "message": msg}


def _wv_provision(data, status, msg, fallback_id=None):
    obj = data if isinstance(data, dict) else {}
    pid = obj.get("id") or fallback_id
    ids = [pid] if pid not in (None, "") else []
    rec = obj if obj else ({"id": pid} if ids else {})
    return {"records": [rec] if rec else [], "data_count": 1 if rec else 0, "status": status, "message": msg, "provision_ids": ids}


def _wv_post(query, auth_info, base_url=None, variables=None, timeout=30, verify_ssl=True):
    headers, err = _wv_auth(auth_info)
    if err:
        return None, 401, err
    resp = requests.post((base_url or _GQL), headers=headers, json={"query": query, "variables": variables or {}}, timeout=timeout, verify=verify_ssl)
    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {}
    return data, resp.status_code, None
